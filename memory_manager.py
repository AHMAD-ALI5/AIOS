"""
AIOS Memory Manager
Two-tier memory architecture: Redis STM (short-term) + ChromaDB LTM (long-term vector).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Optional

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.models import AgentType, MemoryEntry

logger = get_logger("memory")


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

class EmbeddingClient:
    """Thin wrapper around OpenAI embeddings API with batching support."""

    def __init__(self, config: AIOSConfig) -> None:
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                api_key = self.config.openai_api_key
                if not api_key:
                    raise RuntimeError("OPENAI_API_KEY not set")
                self._client = AsyncOpenAI(api_key=api_key)
            except ImportError:
                raise RuntimeError("openai package not installed")
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        client = self._get_client()
        response = await client.embeddings.create(
            model=self.config.llm.embedding_model,
            input=text[:8000],  # Truncate to avoid token limit errors
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        client = self._get_client()
        batch_size = self.config.llm.embedding_batch_size
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = [t[:8000] for t in texts[i : i + batch_size]]
            response = await client.embeddings.create(
                model=self.config.llm.embedding_model,
                input=batch,
            )
            all_embeddings.extend([d.embedding for d in response.data])
        return all_embeddings


# ---------------------------------------------------------------------------
# STM: Redis-backed short-term memory
# ---------------------------------------------------------------------------

class STMClient:
    """
    Short-Term Memory backed by Redis.
    Stores recent agent outputs with configurable TTL.
    Tracks access counts for LTM promotion decisions.
    """

    STM_PREFIX = "aios:stm:"
    ACCESS_PREFIX = "aios:stm_access:"

    def __init__(self, config: AIOSConfig) -> None:
        self.config = config
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            try:
                import redis.asyncio as redis
                self._pool = redis.ConnectionPool.from_url(
                    self.config.redis.url,
                    max_connections=self.config.redis.max_connections,
                    decode_responses=True,
                )
            except ImportError:
                raise RuntimeError("redis package not installed — pip install redis")
        return self._pool

    async def _get_client(self):
        import redis.asyncio as redis
        pool = await self._get_pool()
        return redis.Redis(connection_pool=pool)

    async def write(self, entry: MemoryEntry) -> bool:
        """Write a memory entry to STM with TTL."""
        try:
            client = await self._get_client()
            key = f"{self.STM_PREFIX}{entry.entry_id}"
            payload = entry.model_dump_json()
            ttl = self.config.memory.stm_ttl_seconds
            await client.setex(key, ttl, payload)
            # Also index by task_id for fast lookup
            await client.sadd(f"aios:stm_task:{entry.task_id}", entry.entry_id)
            await client.expire(f"aios:stm_task:{entry.task_id}", ttl)
            logger.debug(f"STM write: entry_id={entry.entry_id}, task_id={entry.task_id}")
            return True
        except Exception as exc:
            logger.error(f"STM write failed: {exc}")
            return False

    async def read(self, entry_id: str) -> Optional[MemoryEntry]:
        """Read an entry by ID and increment access count."""
        try:
            client = await self._get_client()
            key = f"{self.STM_PREFIX}{entry_id}"
            raw = await client.get(key)
            if not raw:
                return None
            entry = MemoryEntry.model_validate_json(raw)
            # Increment access count
            entry.access_count += 1
            entry.last_accessed = datetime.utcnow()
            ttl = self.config.memory.stm_ttl_seconds
            await client.setex(key, ttl, entry.model_dump_json())
            return entry
        except Exception as exc:
            logger.error(f"STM read failed: {exc}")
            return None

    async def get_by_task(self, task_id: str) -> list[MemoryEntry]:
        """Retrieve all STM entries associated with a task_id."""
        try:
            client = await self._get_client()
            entry_ids = await client.smembers(f"aios:stm_task:{task_id}")
            entries = []
            for eid in entry_ids:
                entry = await self.read(eid)
                if entry:
                    entries.append(entry)
            return entries
        except Exception as exc:
            logger.error(f"STM get_by_task failed: {exc}")
            return []

    async def get_high_access_entries(self, threshold: int) -> list[MemoryEntry]:
        """Find STM entries with access_count >= threshold for LTM promotion."""
        try:
            client = await self._get_client()
            keys = await client.keys(f"{self.STM_PREFIX}*")
            candidates = []
            for key in keys:
                raw = await client.get(key)
                if raw:
                    entry = MemoryEntry.model_validate_json(raw)
                    if entry.access_count >= threshold:
                        candidates.append(entry)
            return candidates
        except Exception as exc:
            logger.error(f"STM high-access scan failed: {exc}")
            return []

    async def count(self) -> int:
        """Return number of STM entries."""
        try:
            client = await self._get_client()
            keys = await client.keys(f"{self.STM_PREFIX}*")
            return len(keys)
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# LTM: ChromaDB-backed long-term vector memory
# ---------------------------------------------------------------------------

class LTMClient:
    """
    Long-Term Memory backed by ChromaDB vector database.
    Supports semantic (ANN cosine) retrieval.
    """

    def __init__(self, config: AIOSConfig) -> None:
        self.config = config
        self._client = None
        self._collection = None

    def _get_chroma(self):
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.HttpClient(
                    host=self.config.chromadb.host,
                    port=self.config.chromadb.port,
                )
                self._collection = self._client.get_or_create_collection(
                    name=self.config.memory.ltm_collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as exc:
                logger.warning(f"ChromaDB not available — LTM disabled: {exc}")
                self._client = None
        return self._collection

    def write(self, entry: MemoryEntry) -> bool:
        """Upsert a memory entry into the LTM vector store."""
        try:
            collection = self._get_chroma()
            if collection is None or entry.embedding is None:
                return False
            collection.upsert(
                ids=[entry.entry_id],
                embeddings=[entry.embedding],
                documents=[entry.content[:2000]],  # Truncate stored doc
                metadatas=[{
                    "task_id": entry.task_id,
                    "workflow_id": entry.workflow_id,
                    "agent_type": entry.agent_type.value,
                    "created_at": entry.created_at.isoformat(),
                    "last_accessed": entry.last_accessed.isoformat(),
                    "tier": "LTM",
                }],
            )
            logger.debug(f"LTM write: entry_id={entry.entry_id}")
            return True
        except Exception as exc:
            logger.error(f"LTM write failed: {exc}")
            return False

    def query(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """
        Top-k cosine ANN retrieval.

        C(q) = argTopK_{m ∈ M} cosine(q, m)
        """
        try:
            collection = self._get_chroma()
            if collection is None:
                return []
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count()),
                include=["documents", "metadatas", "distances"],
            )
            entries = []
            for i, doc in enumerate(results["documents"][0]):
                entries.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "similarity": 1.0 - results["distances"][0][i],
                })
            return entries
        except Exception as exc:
            logger.error(f"LTM query failed: {exc}")
            return []

    def count(self) -> int:
        try:
            collection = self._get_chroma()
            return collection.count() if collection else 0
        except Exception:
            return 0

    def delete_stale(self, staleness_threshold_seconds: int) -> int:
        """Delete LTM entries older than staleness threshold."""
        try:
            collection = self._get_chroma()
            if collection is None:
                return 0
            cutoff = (
                datetime.utcnow() - timedelta(seconds=staleness_threshold_seconds)
            ).isoformat()
            # ChromaDB filter by metadata
            results = collection.get(where={"created_at": {"$lt": cutoff}})
            if results["ids"]:
                collection.delete(ids=results["ids"])
                logger.info(f"LTM evicted {len(results['ids'])} stale entries")
                return len(results["ids"])
            return 0
        except Exception as exc:
            logger.error(f"LTM stale deletion failed: {exc}")
            return 0


# ---------------------------------------------------------------------------
# Unified Memory Manager
# ---------------------------------------------------------------------------

class MemoryManager:
    """
    AIOS Memory Manager: unified interface for STM (Redis) + LTM (ChromaDB).

    Provides:
    - write(): Store agent output in STM
    - load_context(): Hybrid STM exact + LTM semantic retrieval
    - consolidate(): Promote high-access STM entries to LTM, evict stale LTM
    """

    def __init__(self, config: Optional[AIOSConfig] = None) -> None:
        self.config = config or get_config()
        self.stm = STMClient(self.config)
        self.ltm = LTMClient(self.config)
        self.embedder = EmbeddingClient(self.config)
        self._hit_count = 0
        self._miss_count = 0

    @property
    def memory_hit_rate(self) -> float:
        total = self._hit_count + self._miss_count
        return self._hit_count / total if total > 0 else 0.0

    async def write(
        self,
        task_id: str,
        workflow_id: str,
        agent_type: AgentType,
        content: str,
        promote_to_ltm: bool = False,
    ) -> MemoryEntry:
        """
        Write agent output to STM. Optionally also write to LTM.
        """
        entry = MemoryEntry(
            task_id=task_id,
            workflow_id=workflow_id,
            agent_type=agent_type,
            content=content,
            tier="STM",
        )
        await self.stm.write(entry)

        if promote_to_ltm:
            try:
                embedding = await self.embedder.embed(content)
                entry.embedding = embedding
                entry.tier = "LTM"
                self.ltm.write(entry)
            except Exception as exc:
                logger.warning(f"LTM write skipped: {exc}")

        return entry

    async def load_context(
        self,
        task_spec_text: str,
        sibling_task_ids: Optional[list[str]] = None,
        top_k_ltm: Optional[int] = None,
    ) -> str:
        """
        Hybrid context retrieval:
        1. Exact STM lookup for sibling task outputs (recent shared context)
        2. Semantic ANN retrieval from LTM for domain knowledge

        Returns assembled context string ready for prompt injection.
        """
        top_k = top_k_ltm or self.config.memory.retrieval_top_k
        context_parts = []

        # --- STM exact match ---
        stm_results = []
        if sibling_task_ids:
            for tid in sibling_task_ids:
                entries = await self.stm.get_by_task(tid)
                stm_results.extend(entries)
        if stm_results:
            self._hit_count += len(stm_results)
            context_parts.append("=== Recent Task Outputs (Short-Term Memory) ===")
            for e in stm_results[:5]:  # Cap at 5 STM entries
                context_parts.append(
                    f"[Task {e.task_id} | {e.agent_type.value}]:\n{e.content[:500]}"
                )
        else:
            self._miss_count += 1

        # --- LTM semantic retrieval ---
        try:
            query_embedding = await self.embedder.embed(task_spec_text)
            ltm_results = self.ltm.query(query_embedding, top_k=top_k)
            if ltm_results:
                self._hit_count += 1
                context_parts.append("=== Relevant Prior Knowledge (Long-Term Memory) ===")
                for r in ltm_results:
                    sim = r.get("similarity", 0)
                    context_parts.append(
                        f"[similarity={sim:.2f}]:\n{r['content'][:400]}"
                    )
        except Exception as exc:
            logger.debug(f"LTM retrieval skipped: {exc}")

        if not context_parts:
            return ""
        return "\n\n".join(context_parts)

    async def get_memory_hit_score(
        self, task_id: str, sibling_task_ids: list[str]
    ) -> float:
        """
        Compute MH(v) ∈ [0,1]: fraction of required context available in STM.
        Used by the Scheduler's priority function.
        """
        if not sibling_task_ids:
            return 0.0
        hits = 0
        for tid in sibling_task_ids:
            entries = await self.stm.get_by_task(tid)
            if entries:
                hits += 1
        return hits / len(sibling_task_ids)

    async def consolidate(self) -> dict:
        """
        Memory consolidation:
        1. Promote high-access STM entries to LTM
        2. Evict stale LTM entries

        Minimises: L_mem = -Σ MH(v) + λ·Σ 1[age(m) > τ]
        """
        stats = {"promoted": 0, "evicted": 0}
        threshold = self.config.memory.promotion_threshold

        # Promote high-access STM entries
        candidates = await self.stm.get_high_access_entries(threshold)
        for entry in candidates:
            if entry.embedding is None:
                try:
                    embedding = await self.embedder.embed(entry.content)
                    entry.embedding = embedding
                except Exception:
                    continue
            if self.ltm.write(entry):
                stats["promoted"] += 1

        # Evict stale LTM entries
        evicted = self.ltm.delete_stale(self.config.memory.ltm_staleness_threshold)
        stats["evicted"] = evicted

        logger.info(
            f"Memory consolidation: promoted={stats['promoted']}, evicted={stats['evicted']}"
        )
        return stats

    async def run_consolidation_loop(self) -> None:
        """Run periodic memory consolidation in the background."""
        interval = self.config.memory.consolidation_interval_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                await self.consolidate()
            except Exception as exc:
                logger.error(f"Consolidation loop error: {exc}")

    async def get_stats(self) -> dict:
        stm_count = await self.stm.count()
        ltm_count = self.ltm.count()
        return {
            "stm_entries": stm_count,
            "ltm_entries": ltm_count,
            "hit_rate": round(self.memory_hit_rate, 3),
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
        }

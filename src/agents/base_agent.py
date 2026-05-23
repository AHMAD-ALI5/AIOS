"""
AIOS Base Execution Agent
Six-stage pipeline: Receive → Load Context → Invoke LLM → Execute Tools → Write Memory → Emit Result
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.memory.memory_manager import MemoryManager
from src.models import AgentType, TaskRecord, TaskResult

logger = get_logger("agents.base")


class BaseAgent(ABC):
    """
    Abstract base for all AIOS execution agents.

    Subclasses implement:
    - agent_type property
    - _build_prompt(task, context) → str
    - _parse_result(raw_output) → dict
    - (optional) _execute_tools(raw_output) → str
    """

    def __init__(
        self,
        config: Optional[AIOSConfig] = None,
        memory: Optional[MemoryManager] = None,
    ) -> None:
        self.config = config or get_config()
        self.memory = memory or MemoryManager(self.config)
        self.instance_id = f"{self.agent_type.value}:{uuid.uuid4().hex[:6]}"
        self._llm_client = self._build_llm_client()

    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        """Agent type identifier."""
        ...

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt for the LLM."""
        ...

    def _build_llm_client(self):
        try:
            from openai import AsyncOpenAI
            api_key = self.config.openai_api_key
            if not api_key:
                logger.warning(f"[{self.instance_id}] OPENAI_API_KEY not set")
                return None
            return AsyncOpenAI(api_key=api_key, timeout=self.config.llm.request_timeout)
        except ImportError:
            logger.error("openai package not installed")
            return None

    async def _invoke_llm(self, messages: list[dict]) -> tuple[str, dict]:
        """Invoke LLM and return (text, token_usage)."""
        if self._llm_client is None:
            raise RuntimeError("LLM client not available")
        model = self.config.llm.default_model
        response = await self._llm_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.config.llm.temperature,
            max_tokens=self.config.llm.max_tokens,
        )
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return response.choices[0].message.content.strip(), usage

    @abstractmethod
    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        """Build the messages list for this agent's LLM call."""
        ...

    def _parse_result(self, raw_output: str) -> dict:
        """Parse raw LLM output into structured data. Override for domain-specific parsing."""
        return {"raw": raw_output}

    async def _execute_tools(self, task: TaskRecord, raw_output: str) -> str:
        """
        Optional tool execution step. Override in subclasses that use tools.
        Default: return raw_output unchanged.
        """
        return raw_output

    async def execute(self, task: TaskRecord) -> TaskResult:
        """
        Six-stage pipeline:
        1. Receive task
        2. Load context from memory
        3. Invoke LLM
        4. Execute tools (if needed)
        5. Write result to memory
        6. Return TaskResult
        """
        start_time = time.time()
        logger.info(f"[{self.instance_id}] Starting task {task.task_id}")

        # Stage 1 & 2: Load context
        sibling_ids = list(task.spec.dependencies)
        try:
            context = await self.memory.load_context(
                task_spec_text=task.spec.description,
                sibling_task_ids=sibling_ids,
            )
        except Exception as exc:
            logger.warning(f"[{self.instance_id}] Context load failed (continuing without): {exc}")
            context = ""

        # Stage 3: Invoke LLM
        messages = self._build_prompt(task, context)
        try:
            raw_output, token_usage = await self._invoke_llm(messages)
        except Exception as exc:
            elapsed = time.time() - start_time
            raise RuntimeError(f"LLM invocation failed after {elapsed:.1f}s: {exc}") from exc

        # Stage 4: Tool execution
        try:
            processed_output = await self._execute_tools(task, raw_output)
        except Exception as exc:
            logger.warning(f"[{self.instance_id}] Tool execution failed, using raw output: {exc}")
            processed_output = raw_output

        # Stage 5: Write to memory
        try:
            await self.memory.write(
                task_id=task.task_id,
                workflow_id=task.workflow_id,
                agent_type=self.agent_type,
                content=processed_output,
            )
        except Exception as exc:
            logger.warning(f"[{self.instance_id}] Memory write failed: {exc}")

        # Stage 6: Build and return result
        elapsed = time.time() - start_time
        structured = self._parse_result(processed_output)
        result = TaskResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            agent_instance_id=self.instance_id,
            content=processed_output,
            structured_data=structured,
            memory_written=True,
            execution_time_seconds=elapsed,
            token_usage=token_usage,
        )
        logger.info(
            f"[{self.instance_id}] Completed task {task.task_id} "
            f"in {elapsed:.1f}s | tokens={token_usage.get('total_tokens', 0)}"
        )
        return result

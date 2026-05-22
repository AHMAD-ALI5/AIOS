"""Unit tests for AIOS Memory Manager (mocked backends)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import AgentType, MemoryEntry
from src.memory.memory_manager import MemoryManager


class TestMemoryManager:
    def _make_manager(self) -> MemoryManager:
        mgr = MemoryManager()
        # Mock out external clients
        mgr.stm = MagicMock()
        mgr.ltm = MagicMock()
        mgr.embedder = MagicMock()
        return mgr

    @pytest.mark.asyncio
    async def test_write_stores_to_stm(self):
        mgr = self._make_manager()
        mgr.stm.write = AsyncMock(return_value=True)
        entry = await mgr.write(
            task_id="t1",
            workflow_id="wf1",
            agent_type=AgentType.RESEARCH,
            content="Test content",
        )
        assert entry.task_id == "t1"
        assert entry.tier == "STM"
        mgr.stm.write.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_with_ltm_promotion(self):
        mgr = self._make_manager()
        mgr.stm.write = AsyncMock(return_value=True)
        mgr.ltm.write = MagicMock(return_value=True)
        mgr.embedder.embed = AsyncMock(return_value=[0.1] * 1536)

        entry = await mgr.write(
            task_id="t1",
            workflow_id="wf1",
            agent_type=AgentType.RESEARCH,
            content="Important content",
            promote_to_ltm=True,
        )
        mgr.embedder.embed.assert_awaited_once()
        mgr.ltm.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_context_stm_hit(self):
        mgr = self._make_manager()
        fake_entry = MemoryEntry(
            task_id="t0",
            workflow_id="wf1",
            agent_type=AgentType.RESEARCH,
            content="prior result content",
        )
        mgr.stm.get_by_task = AsyncMock(return_value=[fake_entry])
        mgr.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
        mgr.ltm.query = MagicMock(return_value=[])

        context = await mgr.load_context(
            task_spec_text="new task",
            sibling_task_ids=["t0"],
        )
        assert "prior result content" in context
        assert mgr._hit_count >= 1

    @pytest.mark.asyncio
    async def test_load_context_ltm_hit(self):
        mgr = self._make_manager()
        mgr.stm.get_by_task = AsyncMock(return_value=[])
        mgr.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
        mgr.ltm.query = MagicMock(return_value=[
            {"content": "ltm result", "similarity": 0.85, "metadata": {}}
        ])

        context = await mgr.load_context(
            task_spec_text="query text",
            sibling_task_ids=["t0"],
        )
        assert "ltm result" in context

    @pytest.mark.asyncio
    async def test_memory_hit_rate_tracking(self):
        mgr = self._make_manager()
        mgr.stm.get_by_task = AsyncMock(return_value=[])
        mgr.embedder.embed = AsyncMock(return_value=[0.0] * 1536)
        mgr.ltm.query = MagicMock(return_value=[])

        await mgr.load_context("task", sibling_task_ids=["t0"])
        assert mgr._miss_count == 1

    @pytest.mark.asyncio
    async def test_consolidation_promotes_high_access(self):
        mgr = self._make_manager()
        fake_entry = MemoryEntry(
            task_id="t1", workflow_id="wf1",
            agent_type=AgentType.RESEARCH, content="hot content",
            access_count=5,
        )
        mgr.stm.get_high_access_entries = AsyncMock(return_value=[fake_entry])
        mgr.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
        mgr.ltm.write = MagicMock(return_value=True)
        mgr.ltm.delete_stale = MagicMock(return_value=0)

        stats = await mgr.consolidate()
        assert stats["promoted"] == 1
        mgr.ltm.write.assert_called_once()

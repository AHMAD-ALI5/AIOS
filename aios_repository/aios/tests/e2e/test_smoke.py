"""
AIOS E2E Smoke Test
Tests the full runtime pipeline with mocked LLM calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.models import AgentType, DAG, TaskSpec, TaskState
from src.runtime import AIOSRuntime


SIMPLE_DAG = DAG(
    workflow_id="smoke_wf_001",
    objective="Briefly explain what a neural network is.",
    tasks=[
        TaskSpec(id="s1", type=AgentType.RESEARCH,
                 description="Find a concise definition of neural networks",
                 dependencies=[], estimated_cost=15.0),
        TaskSpec(id="s2", type=AgentType.WRITER,
                 description="Write a 100-word explanation of neural networks based on s1",
                 dependencies=["s1"], estimated_cost=10.0),
    ]
)

LLM_RESPONSE = MagicMock()
LLM_RESPONSE.choices = [MagicMock()]
LLM_RESPONSE.choices[0].message.content = "Neural networks are brain-inspired ML models."
LLM_RESPONSE.usage = MagicMock(prompt_tokens=50, completion_tokens=30, total_tokens=80)


@pytest.mark.asyncio
async def test_smoke_full_pipeline():
    """Full pipeline smoke test with mocked LLM and memory."""
    runtime = AIOSRuntime()

    # Mock planner
    runtime.planner.plan = AsyncMock(return_value=SIMPLE_DAG)

    # Mock collector
    runtime.collector.aggregate = AsyncMock(
        return_value="# Final Answer\n\nNeural networks are brain-inspired ML models."
    )

    # Mock memory
    runtime.memory.write = AsyncMock(return_value=MagicMock(entry_id="mem_001"))
    runtime.memory.load_context = AsyncMock(return_value="")
    runtime.memory.run_consolidation_loop = AsyncMock()

    # Mock the OpenAI client on every agent's _llm_client
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=LLM_RESPONSE)

    with patch("src.agents.base_agent.BaseAgent._build_llm_client", return_value=mock_client):
        # Rebuild runtime agents with mocked client
        runtime2 = AIOSRuntime()
        runtime2.planner.plan = AsyncMock(return_value=SIMPLE_DAG)
        runtime2.collector.aggregate = AsyncMock(
            return_value="# Final Answer\n\nNeural networks are brain-inspired ML models."
        )
        runtime2.memory.write = AsyncMock(return_value=MagicMock(entry_id="mem_001"))
        runtime2.memory.load_context = AsyncMock(return_value="")
        runtime2.memory.run_consolidation_loop = AsyncMock()

        # Patch _invoke_llm directly on the class
        async def fake_invoke(self_agent, messages):
            return "Neural networks are layered computational models inspired by the brain.", {"total_tokens": 80}

        with patch("src.agents.base_agent.BaseAgent._invoke_llm", fake_invoke):
            await runtime2.start()
            try:
                result = await runtime2.execute(
                    objective=SIMPLE_DAG.objective,
                    timeout_seconds=30,
                )
            finally:
                await runtime2.stop()

    assert result is not None
    assert result.workflow_id == SIMPLE_DAG.workflow_id
    assert result.status in (TaskState.COMPLETED, TaskState.TERMINAL_FAIL)

    total = result.metrics.get("total_tasks", 0)
    completed = result.metrics.get("completed_tasks", 0)
    print(f"\n✅ E2E smoke test: {completed}/{total} tasks completed")
    print(f"   Status: {result.status.value}")
    print(f"   Time: {result.total_execution_time_seconds:.1f}s")
    print(f"   Output preview: {(result.result or '')[:100]}")

    assert completed > 0, f"At least one task should complete (got {completed}/{total})"

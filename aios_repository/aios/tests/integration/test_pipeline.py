"""
Integration tests for the AIOS pipeline (mocked LLM + Redis backends).
These tests verify end-to-end orchestration without real API calls.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import AgentType, DAG, TaskDomain, TaskResult, TaskSpec, TaskState
from src.runtime import AIOSRuntime
from src.scheduler.scheduler import Scheduler


# ---------------------------------------------------------------------------
# Mock DAG (skips real LLM planning)
# ---------------------------------------------------------------------------

def make_simple_dag(workflow_id: str = "wf_integration") -> DAG:
    return DAG(
        workflow_id=workflow_id,
        objective="Write a brief summary of transformers",
        tasks=[
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="Research transformers",
                     dependencies=[], estimated_cost=10.0),
            TaskSpec(id="t2", type=AgentType.WRITER, description="Write summary",
                     dependencies=["t1"], estimated_cost=10.0),
        ]
    )


# ---------------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------------

class TestSchedulerIntegration:
    @pytest.mark.asyncio
    async def test_full_workflow_dispatch_and_complete(self):
        """Test that scheduler dispatches all tasks and marks workflow complete."""
        dispatched: list[str] = []

        async def fake_dispatch(record):
            dispatched.append(record.task_id)
            result = TaskResult(
                task_id=record.task_id,
                agent_type=record.spec.type,
                agent_instance_id="test:001",
                content=f"Result for {record.task_id}",
            )
            await asyncio.sleep(0.01)
            await sched.on_task_completed(record.workflow_id, record.task_id, result)

        dag = make_simple_dag()
        sched = Scheduler(dispatch_fn=fake_dispatch)
        await sched.register_workflow(dag)

        # Run scheduler for a few ticks
        for _ in range(20):
            await sched._tick()
            await asyncio.sleep(0.02)

        assert sched.is_workflow_complete(dag.workflow_id)
        assert "t1" in dispatched
        assert "t2" in dispatched
        # t2 must be dispatched after t1
        assert dispatched.index("t2") > dispatched.index("t1")

    @pytest.mark.asyncio
    async def test_parallel_independent_tasks_dispatched_together(self):
        """Three independent tasks should all reach READY simultaneously."""
        dag = DAG(
            workflow_id="wf_parallel",
            objective="Parallel test",
            tasks=[
                TaskSpec(id="t1", type=AgentType.RESEARCH, description="A", dependencies=[]),
                TaskSpec(id="t2", type=AgentType.CODE, description="B", dependencies=[]),
                TaskSpec(id="t3", type=AgentType.WRITER, description="C", dependencies=[]),
            ]
        )
        sched = Scheduler()
        await sched.register_workflow(dag)
        progress = sched.get_workflow_progress("wf_parallel")
        # All three should be READY (pending=0, or ready queue has 3)
        t1 = sched.get_task_record("wf_parallel", "t1")
        t2 = sched.get_task_record("wf_parallel", "t2")
        t3 = sched.get_task_record("wf_parallel", "t3")
        assert all(r.state == TaskState.READY for r in [t1, t2, t3])


# ---------------------------------------------------------------------------
# Runtime integration (mocked LLM)
# ---------------------------------------------------------------------------

class TestRuntimeIntegration:
    @pytest.mark.asyncio
    async def test_execute_with_mocked_planner_and_agents(self):
        """Full runtime execute() with mocked planner output and agent LLM calls."""
        runtime = AIOSRuntime()

        # Mock planner to return a fixed DAG
        dag = make_simple_dag("wf_mock")
        runtime.planner.plan = AsyncMock(return_value=dag)

        # Mock agent LLM calls
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is the agent response."
        mock_response.usage = MagicMock(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        )

        # Mock collector
        runtime.collector.aggregate = AsyncMock(return_value="Final synthesized output.")

        # Mock memory operations
        runtime.memory.write = AsyncMock(return_value=MagicMock(entry_id="e1"))
        runtime.memory.load_context = AsyncMock(return_value="")
        runtime.memory.run_consolidation_loop = AsyncMock()

        with patch("src.agents.base_agent.BaseAgent._invoke_llm",
                   new=AsyncMock(return_value=("Agent output text", {"total_tokens": 150}))):
            await runtime.start()
            result = await runtime.execute(
                objective="Write a summary of transformers",
                timeout_seconds=30,
            )
            await runtime.stop()

        assert result.workflow_id == "wf_mock"
        assert result.status == TaskState.COMPLETED
        assert result.result == "Final synthesized output."

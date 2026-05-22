"""Unit tests for the AIOS Scheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import AgentType, DAG, TaskRecord, TaskResult, TaskSpec, TaskState
from src.scheduler.scheduler import Scheduler, compute_critical_path, compute_priority


# ---------------------------------------------------------------------------
# Critical path tests
# ---------------------------------------------------------------------------

class TestCriticalPath:
    def _make_dag(self, specs: list[dict]) -> list[TaskSpec]:
        return [
            TaskSpec(
                id=s["id"],
                type=AgentType.RESEARCH,
                description="test",
                dependencies=s.get("deps", []),
                estimated_cost=s.get("cost", 10.0),
            )
            for s in specs
        ]

    def test_single_node(self):
        tasks = self._make_dag([{"id": "t1", "cost": 20.0}])
        cp = compute_critical_path(tasks)
        assert cp["t1"] == 20.0

    def test_linear_chain(self):
        # t1 → t2 → t3, costs 10, 20, 30
        tasks = self._make_dag([
            {"id": "t1", "cost": 10.0},
            {"id": "t2", "cost": 20.0, "deps": ["t1"]},
            {"id": "t3", "cost": 30.0, "deps": ["t2"]},
        ])
        cp = compute_critical_path(tasks)
        assert cp["t1"] == 60.0   # 10 + 20 + 30
        assert cp["t2"] == 50.0   # 20 + 30
        assert cp["t3"] == 30.0   # leaf

    def test_parallel_branches(self):
        # t1 forks to t2, t3, then t4 joins
        tasks = self._make_dag([
            {"id": "t1", "cost": 5.0},
            {"id": "t2", "cost": 10.0, "deps": ["t1"]},
            {"id": "t3", "cost": 30.0, "deps": ["t1"]},  # longer branch
            {"id": "t4", "cost": 5.0, "deps": ["t2", "t3"]},
        ])
        cp = compute_critical_path(tasks)
        # CP from t1: 5 + max(10+5, 30+5) = 5 + 35 = 40
        assert cp["t1"] == 40.0
        assert cp["t3"] == 35.0  # 30 + 5

    def test_unknown_dependency_raises(self):
        tasks = [
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="x",
                     dependencies=["nonexistent"], estimated_cost=10.0)
        ]
        with pytest.raises(ValueError, match="unknown dependency"):
            compute_critical_path(tasks)


# ---------------------------------------------------------------------------
# Priority function tests
# ---------------------------------------------------------------------------

class TestPriority:
    def _make_record(self, task_id: str, cost: float = 10.0, mh: float = 0.0) -> TaskRecord:
        return TaskRecord(
            spec=TaskSpec(
                id=task_id,
                type=AgentType.RESEARCH,
                description="test",
                estimated_cost=cost,
                metadata={"memory_hit_score": mh},
            ),
            workflow_id="wf1",
        )

    def test_priority_formula(self):
        rec = self._make_record("t1", cost=20.0, mh=0.5)
        cp = {"t1": 50.0}
        p = compute_priority(rec, cp, alpha=0.3, beta=0.5, gamma=0.2)
        expected = 0.3 * 20.0 + 0.5 * 50.0 + 0.2 * 0.5
        assert abs(p - expected) < 1e-6

    def test_higher_cp_increases_priority(self):
        rec = self._make_record("t1", cost=10.0, mh=0.0)
        cp_low = {"t1": 10.0}
        cp_high = {"t1": 100.0}
        assert compute_priority(rec, cp_high) > compute_priority(rec, cp_low)

    def test_higher_mh_increases_priority(self):
        rec_low = self._make_record("t1", mh=0.0)
        rec_high = self._make_record("t1", mh=1.0)
        cp = {"t1": 20.0}
        assert compute_priority(rec_high, cp) > compute_priority(rec_low, cp)


# ---------------------------------------------------------------------------
# Scheduler integration tests
# ---------------------------------------------------------------------------

class TestScheduler:
    def _make_dag(self, task_specs: list[dict]) -> DAG:
        tasks = [
            TaskSpec(
                id=s["id"],
                type=AgentType(s.get("type", "research")),
                description=s.get("desc", "test"),
                dependencies=s.get("deps", []),
                estimated_cost=s.get("cost", 10.0),
            )
            for s in task_specs
        ]
        return DAG(objective="test", tasks=tasks, workflow_id="wf_test")

    @pytest.mark.asyncio
    async def test_register_workflow_roots_ready(self):
        dag = self._make_dag([
            {"id": "t1", "deps": []},
            {"id": "t2", "deps": ["t1"]},
        ])
        sched = Scheduler()
        await sched.register_workflow(dag)
        progress = sched.get_workflow_progress("wf_test")
        assert progress is not None
        # Only t1 should be READY; t2 is PENDING
        t1 = sched.get_task_record("wf_test", "t1")
        t2 = sched.get_task_record("wf_test", "t2")
        assert t1.state == TaskState.READY
        assert t2.state == TaskState.PENDING

    @pytest.mark.asyncio
    async def test_completion_promotes_successors(self):
        dag = self._make_dag([
            {"id": "t1", "deps": []},
            {"id": "t2", "deps": ["t1"]},
        ])
        sched = Scheduler()
        await sched.register_workflow(dag)
        # Complete t1
        result = TaskResult(
            task_id="t1", agent_type=AgentType.RESEARCH,
            agent_instance_id="test:001", content="done",
        )
        await sched.on_task_completed("wf_test", "t1", result)
        t2 = sched.get_task_record("wf_test", "t2")
        assert t2.state == TaskState.READY

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        dag = self._make_dag([{"id": "t1", "deps": []}])
        sched = Scheduler()
        sched.config.scheduler.max_retries = 2
        await sched.register_workflow(dag)
        # Fail once
        await sched.on_task_failed("wf_test", "t1", "transient error")
        t1 = sched.get_task_record("wf_test", "t1")
        assert t1.state == TaskState.RETRYING
        assert t1.retry_count == 1

    @pytest.mark.asyncio
    async def test_terminal_fail_after_max_retries(self):
        dag = self._make_dag([{"id": "t1", "deps": []}])
        sched = Scheduler()
        sched.config.scheduler.max_retries = 2
        await sched.register_workflow(dag)
        for _ in range(3):
            await sched.on_task_failed("wf_test", "t1", "persistent error")
        t1 = sched.get_task_record("wf_test", "t1")
        assert t1.state == TaskState.TERMINAL_FAIL

    @pytest.mark.asyncio
    async def test_workflow_complete_when_all_done(self):
        dag = self._make_dag([
            {"id": "t1"}, {"id": "t2"},
        ])
        sched = Scheduler()
        await sched.register_workflow(dag)
        for tid in ["t1", "t2"]:
            await sched.on_task_completed(
                "wf_test", tid,
                TaskResult(task_id=tid, agent_type=AgentType.RESEARCH,
                           agent_instance_id="x", content="ok"),
            )
        assert sched.is_workflow_complete("wf_test")

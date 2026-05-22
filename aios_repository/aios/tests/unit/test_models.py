"""Unit tests for AIOS data models and evaluation metrics."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from src.models import (
    AgentType, BusMessage, DAG, MessageType, TaskRecord,
    TaskResult, TaskSpec, TaskState,
)
from evaluation.metrics import MUETracker, WorkflowEvalResult, TaskEvalResult


class TestModels:
    def test_dag_get_roots(self):
        dag = DAG(
            objective="test",
            tasks=[
                TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=[]),
                TaskSpec(id="t2", type=AgentType.CODE, description="x", dependencies=["t1"]),
                TaskSpec(id="t3", type=AgentType.WRITER, description="x", dependencies=[]),
            ]
        )
        roots = dag.get_roots()
        assert "t1" in roots
        assert "t3" in roots
        assert "t2" not in roots

    def test_dag_get_successors(self):
        dag = DAG(
            objective="test",
            tasks=[
                TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=[]),
                TaskSpec(id="t2", type=AgentType.CODE, description="x", dependencies=["t1"]),
                TaskSpec(id="t3", type=AgentType.WRITER, description="x", dependencies=["t1"]),
            ]
        )
        succs = dag.get_successors("t1")
        assert set(succs) == {"t2", "t3"}

    def test_task_record_execution_time(self):
        spec = TaskSpec(id="t1", type=AgentType.RESEARCH, description="x")
        record = TaskRecord(spec=spec, workflow_id="wf1")
        record.started_at = datetime.utcnow()
        record.completed_at = record.started_at + timedelta(seconds=5.0)
        assert abs(record.execution_time_seconds - 5.0) < 0.1

    def test_bus_message_serialization(self):
        msg = BusMessage(
            sender="research:abc123",
            recipient="scheduler",
            task_id="t1",
            workflow_id="wf1",
            message_type=MessageType.ACK_COMPLETE,
            payload={"result": "done"},
        )
        json_str = msg.model_dump_json()
        restored = BusMessage.model_validate_json(json_str)
        assert restored.task_id == "t1"
        assert restored.message_type == MessageType.ACK_COMPLETE


class TestMUETracker:
    def test_perfect_hit_rate(self):
        tracker = MUETracker()
        for _ in range(10):
            tracker.record(hit=True)
        assert tracker.mue == 1.0

    def test_zero_hit_rate(self):
        tracker = MUETracker()
        for _ in range(5):
            tracker.record(hit=False)
        assert tracker.mue == 0.0

    def test_mixed_hit_rate(self):
        tracker = MUETracker()
        tracker.record(True)
        tracker.record(True)
        tracker.record(False)
        tracker.record(False)
        assert abs(tracker.mue - 0.5) < 1e-9

    def test_empty_tracker_returns_zero(self):
        tracker = MUETracker()
        assert tracker.mue == 0.0

    def test_reset(self):
        tracker = MUETracker()
        tracker.record(True)
        tracker.reset()
        assert tracker.mue == 0.0
        assert tracker._total == 0


class TestWorkflowEvalResult:
    def _make_result(self, completed_flags: list[bool], rqs_scores: list[float], times: list[float]):
        task_results = [
            TaskEvalResult(
                task_id=f"t{i}",
                completed=c,
                rqs_score=s,
                execution_time_seconds=t,
            )
            for i, (c, s, t) in enumerate(zip(completed_flags, rqs_scores, times))
        ]
        return WorkflowEvalResult(
            workflow_id="wf1",
            objective="test",
            task_results=task_results,
        )

    def test_tcr_all_complete(self):
        r = self._make_result([True, True, True], [8.0, 9.0, 7.0], [10.0, 20.0, 15.0])
        assert r.tcr == 1.0

    def test_tcr_partial(self):
        r = self._make_result([True, False, True, False], [8.0, 0.0, 7.0, 0.0], [10.0, 5.0, 15.0, 3.0])
        assert r.tcr == 0.5

    def test_avg_rqs(self):
        r = self._make_result([True, True], [6.0, 8.0], [10.0, 20.0])
        assert abs(r.avg_rqs - 7.0) < 1e-9

    def test_atl(self):
        r = self._make_result([True, True], [8.0, 8.0], [10.0, 30.0])
        assert abs(r.atl - 20.0) < 1e-9

    def test_wms_single_task(self):
        r = self._make_result([True], [8.0], [10.0])
        assert r.wms == 1.0

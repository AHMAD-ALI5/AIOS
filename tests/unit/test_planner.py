"""Unit tests for the AIOS Planner (DAG validation logic)."""

from __future__ import annotations

import pytest

from src.models import AgentType, TaskSpec
from src.planner.planner import _is_acyclic, _validate_dag_schema


class TestDAGValidation:
    def test_valid_linear_chain(self):
        raw = {
            "tasks": [
                {"id": "t1", "type": "research", "description": "search", "dependencies": [], "estimated_cost": 30},
                {"id": "t2", "type": "writer", "description": "write", "dependencies": ["t1"], "estimated_cost": 20},
            ]
        }
        tasks = _validate_dag_schema(raw)
        assert len(tasks) == 2
        assert tasks[0].type == AgentType.RESEARCH
        assert tasks[1].type == AgentType.WRITER

    def test_missing_tasks_key_raises(self):
        with pytest.raises(ValueError, match="'tasks' key"):
            _validate_dag_schema({"subtasks": []})

    def test_empty_tasks_raises(self):
        with pytest.raises(ValueError):
            _validate_dag_schema({"tasks": []})

    def test_duplicate_ids_raise(self):
        raw = {
            "tasks": [
                {"id": "t1", "type": "research", "description": "a", "dependencies": [], "estimated_cost": 10},
                {"id": "t1", "type": "writer", "description": "b", "dependencies": [], "estimated_cost": 10},
            ]
        }
        with pytest.raises(ValueError, match="Duplicate"):
            _validate_dag_schema(raw)

    def test_unknown_agent_type_defaults_to_research(self):
        raw = {
            "tasks": [
                {"id": "t1", "type": "nonexistent_type", "description": "x",
                 "dependencies": [], "estimated_cost": 10},
            ]
        }
        tasks = _validate_dag_schema(raw)
        assert tasks[0].type == AgentType.RESEARCH

    def test_acyclic_valid_dag(self):
        tasks = [
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=[]),
            TaskSpec(id="t2", type=AgentType.CODE, description="x", dependencies=["t1"]),
            TaskSpec(id="t3", type=AgentType.WRITER, description="x", dependencies=["t1", "t2"]),
        ]
        assert _is_acyclic(tasks) is True

    def test_cyclic_dag_detected(self):
        tasks = [
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=["t2"]),
            TaskSpec(id="t2", type=AgentType.CODE, description="x", dependencies=["t1"]),
        ]
        assert _is_acyclic(tasks) is False

    def test_self_loop_detected(self):
        tasks = [
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=["t1"]),
        ]
        assert _is_acyclic(tasks) is False

    def test_disconnected_forest_is_acyclic(self):
        tasks = [
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=[]),
            TaskSpec(id="t2", type=AgentType.CODE, description="x", dependencies=[]),
            TaskSpec(id="t3", type=AgentType.WRITER, description="x", dependencies=[]),
        ]
        assert _is_acyclic(tasks) is True

    def test_unknown_dependency_raises(self):
        tasks = [
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="x", dependencies=["ghost"]),
        ]
        with pytest.raises(ValueError, match="unknown dependency"):
            _is_acyclic(tasks)

#!/usr/bin/env python3
"""
AIOS Smoke Test Script
Verifies imports, config loading, and basic instantiation.
Run: python scripts/smoke_test.py
"""

import sys
import traceback
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []


def check(name: str, fn):
    try:
        fn()
        results.append((PASS, name, None))
        print(f"  {PASS} {name}")
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  {FAIL} {name}: {e}")


print("\n━━━ AIOS Smoke Test ━━━\n")

# ── Import checks ──────────────────────────────────────────────
print("[ Imports ]")

check("import pydantic", lambda: __import__("pydantic"))
check("import yaml", lambda: __import__("yaml"))
check("import src.models", lambda: __import__("src.models"))
check("import src.config", lambda: __import__("src.config"))
check("import src.logging_config", lambda: __import__("src.logging_config"))
check("import src.planner.planner", lambda: __import__("src.planner.planner"))
check("import src.scheduler.scheduler", lambda: __import__("src.scheduler.scheduler"))
check("import src.memory.memory_manager", lambda: __import__("src.memory.memory_manager"))
check("import src.communication.message_bus", lambda: __import__("src.communication.message_bus"))
check("import src.agents.base_agent", lambda: __import__("src.agents.base_agent"))
check("import src.agents.research_agent", lambda: __import__("src.agents.research_agent"))
check("import src.agents.code_agent", lambda: __import__("src.agents.code_agent"))
check("import src.agents.writer_agent", lambda: __import__("src.agents.writer_agent"))
check("import src.agents.analysis_agent", lambda: __import__("src.agents.analysis_agent"))
check("import src.agents.collector_agent", lambda: __import__("src.agents.collector_agent"))
check("import src.agents.factory", lambda: __import__("src.agents.factory"))
check("import src.runtime", lambda: __import__("src.runtime"))
check("import src.gateway.app", lambda: __import__("src.gateway.app"))
check("import src.monitoring.telemetry", lambda: __import__("src.monitoring.telemetry"))
check("import evaluation.metrics", lambda: __import__("evaluation.metrics"))

# ── Config loading ─────────────────────────────────────────────
print("\n[ Configuration ]")

def _config_load():
    from src.config import get_config
    cfg = get_config()
    assert cfg.scheduler.alpha == 0.3
    assert cfg.scheduler.beta == 0.5
    assert cfg.scheduler.gamma == 0.2
    assert cfg.memory.retrieval_top_k == 5
    assert cfg.llm.temperature == 0.2

check("Config loads from YAML", _config_load)

def _config_weights():
    from src.config import get_config
    cfg = get_config()
    total = cfg.scheduler.alpha + cfg.scheduler.beta + cfg.scheduler.gamma
    assert abs(total - 1.0) < 1e-9, f"Weights don't sum to 1.0: {total}"

check("Scheduler weights sum to 1.0", _config_weights)

# ── Model instantiation ────────────────────────────────────────
print("\n[ Models ]")

def _create_dag():
    from src.models import DAG, AgentType, TaskSpec
    dag = DAG(
        objective="test",
        tasks=[
            TaskSpec(id="t1", type=AgentType.RESEARCH, description="research",
                     dependencies=[], estimated_cost=10.0),
            TaskSpec(id="t2", type=AgentType.WRITER, description="write",
                     dependencies=["t1"], estimated_cost=15.0),
        ]
    )
    assert len(dag.get_roots()) == 1
    assert dag.get_roots()[0] == "t1"
    assert dag.get_successors("t1") == ["t2"]

check("DAG instantiation and traversal", _create_dag)

def _dag_serialization():
    from src.models import DAG, AgentType, TaskSpec
    dag = DAG(
        objective="serialize test",
        tasks=[TaskSpec(id="t1", type=AgentType.CODE, description="code it", dependencies=[])]
    )
    json_str = dag.model_dump_json()
    restored = DAG.model_validate_json(json_str)
    assert restored.tasks[0].id == "t1"

check("DAG JSON serialization roundtrip", _dag_serialization)

# ── Scheduler logic ────────────────────────────────────────────
print("\n[ Scheduler ]")

def _critical_path():
    from src.models import AgentType, TaskSpec
    from src.scheduler.scheduler import compute_critical_path
    tasks = [
        TaskSpec(id="t1", type=AgentType.RESEARCH, description="x",
                 dependencies=[], estimated_cost=10.0),
        TaskSpec(id="t2", type=AgentType.CODE, description="x",
                 dependencies=["t1"], estimated_cost=20.0),
    ]
    cp = compute_critical_path(tasks)
    assert cp["t1"] == 30.0
    assert cp["t2"] == 20.0

check("Critical path computation", _critical_path)

def _priority_fn():
    from src.models import AgentType, TaskRecord, TaskSpec
    from src.scheduler.scheduler import compute_priority
    record = TaskRecord(
        spec=TaskSpec(id="t1", type=AgentType.RESEARCH, description="x",
                      estimated_cost=20.0, metadata={"memory_hit_score": 0.5}),
        workflow_id="wf1",
    )
    p = compute_priority(record, {"t1": 50.0}, alpha=0.3, beta=0.5, gamma=0.2)
    expected = 0.3 * 20 + 0.5 * 50 + 0.2 * 0.5
    assert abs(p - expected) < 1e-9

check("Priority function (π = α·w + β·CP + γ·MH)", _priority_fn)

# ── Planner validation ─────────────────────────────────────────
print("\n[ Planner ]")

def _dag_acyclicity():
    from src.models import AgentType, TaskSpec
    from src.planner.planner import _is_acyclic
    acyclic = [
        TaskSpec(id="a", type=AgentType.RESEARCH, description="x", dependencies=[]),
        TaskSpec(id="b", type=AgentType.CODE, description="x", dependencies=["a"]),
    ]
    cyclic = [
        TaskSpec(id="a", type=AgentType.RESEARCH, description="x", dependencies=["b"]),
        TaskSpec(id="b", type=AgentType.CODE, description="x", dependencies=["a"]),
    ]
    assert _is_acyclic(acyclic) is True
    assert _is_acyclic(cyclic) is False

check("DAG acyclicity detection", _dag_acyclicity)

# ── FastAPI app creation ───────────────────────────────────────
print("\n[ Gateway ]")

def _app_creation():
    from src.gateway.app import create_app
    app = create_app()
    assert app.title == "AIOS — Agentic AI Operating System"
    routes = [r.path for r in app.routes]
    assert "/v1/health" in routes
    assert "/v1/tasks" in routes

check("FastAPI app creates successfully", _app_creation)

# ── Evaluation metrics ─────────────────────────────────────────
print("\n[ Evaluation ]")

def _mue_tracker():
    from evaluation.metrics import MUETracker
    t = MUETracker()
    for _ in range(3): t.record(True)
    for _ in range(1): t.record(False)
    assert abs(t.mue - 0.75) < 1e-9

check("MUE tracker", _mue_tracker)

# ── Summary ────────────────────────────────────────────────────
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total = len(results)

print(f"\n━━━ Results: {passed}/{total} passed, {failed} failed ━━━\n")

if failed > 0:
    print("Failed checks:")
    for icon, name, err in results:
        if icon == FAIL:
            print(f"  {FAIL} {name}: {err}")
    sys.exit(1)
else:
    print("All smoke tests passed! 🎉\n")
    sys.exit(0)

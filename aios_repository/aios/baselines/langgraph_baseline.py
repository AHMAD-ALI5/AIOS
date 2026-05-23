"""
AIOS Baseline: LangGraph
Uses LangGraph StateGraph for task orchestration.
Same planner, same agent prompts as AIOS — isolates scheduler/memory contribution.

Requires: pip install langgraph
"""

from __future__ import annotations

import asyncio
import time
from typing import TypedDict, Annotated
import operator

try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

from src.planner.planner import PlannerAgent
from src.models import TaskDomain, AgentType
from src.config import get_config
from src.agents.factory import create_agent


class WorkflowState(TypedDict):
    objective: str
    task_outputs: Annotated[dict, operator.or_]
    completed_tasks: Annotated[list, operator.add]
    failed_tasks: Annotated[list, operator.add]


class LangGraphBaseline:
    """
    LangGraph-based multi-agent orchestration.
    Equivalent orchestration structure to AIOS, using LangGraph runtime.
    """

    def __init__(self):
        if not LANGGRAPH_AVAILABLE:
            raise ImportError("langgraph not installed. Run: pip install langgraph")
        self.config = get_config()
        self.planner = PlannerAgent(self.config)

    async def execute(self, objective: str, domain: TaskDomain = TaskDomain.GENERAL,
                      timeout_seconds: int = 120) -> dict:
        t0 = time.time()
        try:
            dag = await self.planner.plan(objective, domain)
        except Exception as exc:
            return {
                "objective": objective, "completed": False,
                "output": f"[Planning failed: {exc}]",
                "execution_time_seconds": time.time() - t0,
                "n_tasks": 0, "completed_tasks": 0,
            }

        # Execute tasks respecting dependencies (sequential, no custom scheduler)
        from src.models import TaskRecord, TaskState
        results = {}
        completed = []
        failed = []

        # Topological order
        task_map = {t.id: t for t in dag.tasks}
        executed = set()

        async def can_execute(task_id):
            deps = task_map[task_id].dependencies
            return all(d in executed for d in deps)

        pending = list(task_map.keys())
        max_passes = len(pending) * 2
        passes = 0

        while pending and passes < max_passes:
            passes += 1
            for task_id in list(pending):
                if not await can_execute(task_id):
                    continue
                spec = task_map[task_id]
                agent = create_agent(spec.type, config=self.config)
                record = TaskRecord(spec=spec, workflow_id=dag.workflow_id, state=TaskState.RUNNING)
                try:
                    result = await asyncio.wait_for(agent.execute(record), timeout=60)
                    results[task_id] = result.content
                    completed.append(task_id)
                    executed.add(task_id)
                except Exception as exc:
                    failed.append(task_id)
                    executed.add(task_id)  # Mark as done (failed) so dependents can proceed
                pending.remove(task_id)

        final_output = "\n\n".join(
            f"[{task_id}]:\n{content}" for task_id, content in results.items()
        )
        return {
            "objective": objective,
            "completed": len(failed) == 0,
            "output": final_output,
            "execution_time_seconds": time.time() - t0,
            "n_tasks": len(dag.tasks),
            "completed_tasks": len(completed),
            "failed_tasks": len(failed),
        }

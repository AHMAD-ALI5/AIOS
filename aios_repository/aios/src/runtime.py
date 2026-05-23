"""
AIOS Runtime
Central orchestration engine: wires together Planner, Scheduler, Agents, Memory, and Bus.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from src.agents.collector_agent import CollectorAgent
from src.agents.factory import create_agent
from src.communication.message_bus import MessageBus
from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.memory.memory_manager import MemoryManager
from src.monitoring.telemetry import metrics
import time as _time
from src.models import (
    AgentType, DAG, TaskDomain, TaskRecord, TaskResult,
    TaskState, WorkflowResultResponse, WorkflowStatusResponse,
)
from src.planner.planner import PlannerAgent
from src.scheduler.scheduler import Scheduler

logger = get_logger("runtime")


class AIOSRuntime:
    """
    The AIOS Runtime is the top-level orchestration object.

    Usage:
        runtime = AIOSRuntime()
        await runtime.start()
        result = await runtime.execute(objective="Explain transformers", timeout=300)
        await runtime.stop()
    """

    def __init__(self, config: Optional[AIOSConfig] = None) -> None:
        self.config = config or get_config()
        self.memory = MemoryManager(self.config)
        self.planner = PlannerAgent(self.config)
        self.scheduler = Scheduler(self.config, dispatch_fn=self._dispatch_task)
        self.message_bus = MessageBus(self.config)
        self.collector = CollectorAgent(config=self.config, memory=self.memory)
        self._workflows: dict[str, dict] = {}  # workflow_id → meta
        self._running = False
        self._dispatch_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Start background services."""
        self._running = True
        self._dispatch_tasks = set()
        # Start scheduler loop
        asyncio.create_task(self.scheduler.start())
        # Start memory consolidation loop
        asyncio.create_task(self.memory.run_consolidation_loop())
        logger.info("AIOS Runtime started")

    async def stop(self) -> None:
        """Stop background services."""
        self._running = False
        await self.scheduler.stop()
        if hasattr(self, '_dispatch_tasks'):
            for task in list(self._dispatch_tasks):
                if not task.done():
                    task.cancel()
            if self._dispatch_tasks:
                await asyncio.gather(*self._dispatch_tasks, return_exceptions=True)
        logger.info("AIOS Runtime stopped")

    async def submit(
        self,
        objective: str,
        domain: TaskDomain = TaskDomain.GENERAL,
        timeout_seconds: Optional[int] = None,
    ) -> str:
        """
        Submit an objective and return the workflow_id immediately.
        Caller polls get_status() / get_result() for completion.
        """
        dag = await self.planner.plan(objective, domain)
        await self.scheduler.register_workflow(dag)
        metrics.increment("tasks_submitted_total", len(dag.tasks))
        metrics.set_gauge("active_workflows", len(self._workflows) + 1)
        self._workflows[dag.workflow_id] = {
            "objective": objective,
            "dag": dag,
            "created_at": datetime.utcnow(),
            "timeout_seconds": timeout_seconds or self.config.gateway.task_timeout_seconds,
        }
        logger.info(f"Submitted workflow {dag.workflow_id}: {objective[:60]}...")
        return dag.workflow_id

    async def execute(
        self,
        objective: str,
        domain: TaskDomain = TaskDomain.GENERAL,
        timeout_seconds: Optional[int] = None,
    ) -> WorkflowResultResponse:
        """
        Submit and block until completion (or timeout).
        Convenience method for non-streaming use cases.
        """
        workflow_id = await self.submit(objective, domain, timeout_seconds)
        timeout = timeout_seconds or self.config.gateway.task_timeout_seconds
        start = time.time()

        while True:
            if time.time() - start > timeout:
                raise TimeoutError(f"Workflow {workflow_id} timed out after {timeout}s")
            if self.scheduler.is_workflow_complete(workflow_id):
                break
            await asyncio.sleep(0.5)

        return await self.get_result(workflow_id)

    def get_status(self, workflow_id: str) -> Optional[WorkflowStatusResponse]:
        """Return current workflow status."""
        meta = self._workflows.get(workflow_id)
        if not meta:
            return None
        progress = self.scheduler.get_workflow_progress(workflow_id)
        if not progress:
            return None
        dag: DAG = meta["dag"]
        created_at: datetime = meta["created_at"]
        records = self.scheduler.get_all_task_records(workflow_id)
        # Determine overall state
        if progress["is_complete"]:
            if progress["failed"] > 0 and progress["completed"] == 0:
                overall = TaskState.TERMINAL_FAIL
            elif progress["failed"] > 0:
                overall = TaskState.COMPLETED  # Partial success
            else:
                overall = TaskState.COMPLETED
        elif progress["running"] > 0:
            overall = TaskState.RUNNING
        else:
            overall = TaskState.PENDING

        return WorkflowStatusResponse(
            workflow_id=workflow_id,
            objective=meta["objective"],
            overall_state=overall,
            progress_percent=progress["progress_percent"],
            tasks_total=progress["total"],
            tasks_completed=progress["completed"],
            tasks_failed=progress["failed"],
            tasks_running=progress["running"],
            elapsed_seconds=round((datetime.utcnow() - created_at).total_seconds(), 1),
            created_at=created_at,
            task_states={tid: r.state.value for tid, r in records.items()},
        )

    async def get_result(self, workflow_id: str) -> WorkflowResultResponse:
        """Aggregate and return the final workflow result."""
        meta = self._workflows.get(workflow_id)
        if not meta:
            raise KeyError(f"Unknown workflow: {workflow_id}")

        records = self.scheduler.get_all_task_records(workflow_id)
        dag: DAG = meta["dag"]
        created_at: datetime = meta["created_at"]

        completed_results = [
            r.result for r in records.values()
            if r.state == TaskState.COMPLETED and r.result is not None
        ]
        failed_count = sum(1 for r in records.values() if r.state == TaskState.TERMINAL_FAIL)

        # Run collector agent to synthesize
        final_text = ""
        if completed_results:
            try:
                final_text = await self.collector.aggregate(
                    objective=meta["objective"],
                    task_results=completed_results,
                    workflow_id=workflow_id,
                )
            except Exception as exc:
                logger.error(f"Collector failed: {exc}")
                final_text = "\n\n".join(r.content for r in completed_results)

        completed_at = datetime.utcnow()
        elapsed = (completed_at - created_at).total_seconds()

        status = TaskState.COMPLETED if failed_count == 0 else TaskState.TERMINAL_FAIL
        if failed_count > 0 and completed_results:
            status = TaskState.COMPLETED  # Partial success

        metrics = {
            "total_tasks": len(records),
            "completed_tasks": len(completed_results),
            "failed_tasks": failed_count,
            "total_execution_seconds": round(elapsed, 1),
            "memory_stats": {},  # Populated async if needed
        }

        return WorkflowResultResponse(
            workflow_id=workflow_id,
            objective=meta["objective"],
            status=status,
            result=final_text,
            task_results=completed_results,
            metrics=metrics,
            total_execution_time_seconds=elapsed,
            created_at=created_at,
            completed_at=completed_at,
        )

    async def _dispatch_task(self, record: TaskRecord) -> None:
        """
        Dispatches a TaskRecord to the appropriate execution agent.
        Called by the Scheduler for each READY task.
        """
        task = asyncio.current_task()
        if task and hasattr(self, '_dispatch_tasks'):
            self._dispatch_tasks.add(task)
            task.add_done_callback(self._dispatch_tasks.discard)

        agent_type = record.spec.type
        metrics.increment("tasks_submitted_total")

        if agent_type == AgentType.COLLECTOR:
            # Collector is handled separately at the end
            await self.scheduler.on_task_completed(
                record.workflow_id,
                record.task_id,
                TaskResult(
                    task_id=record.task_id,
                    agent_type=AgentType.COLLECTOR,
                    agent_instance_id="runtime",
                    content="[Deferred to final aggregation]",
                ),
            )
            return

        t0 = _time.time()
        agent = create_agent(agent_type, config=self.config, memory=self.memory)
        try:
            result = await agent.execute(record)
            elapsed = _time.time() - t0
            metrics.increment("tasks_completed_total")
            metrics.record_histogram("task_execution_duration_seconds", elapsed)
            await self.scheduler.on_task_completed(
                record.workflow_id, record.task_id, result
            )
        except Exception as exc:
            elapsed = _time.time() - t0
            metrics.increment("tasks_failed_total")
            metrics.record_histogram("task_execution_duration_seconds", elapsed)
            logger.error(f"Agent execution failed for {record.task_id}: {exc}")
            await self.scheduler.on_task_failed(
                record.workflow_id, record.task_id, str(exc)
            )

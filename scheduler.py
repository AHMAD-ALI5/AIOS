"""
AIOS Scheduler
Priority-aware, dependency-tracking task scheduler inspired by OS process scheduling.
"""

from __future__ import annotations

import asyncio
import heapq
import time
from datetime import datetime
from typing import Callable, Coroutine, Optional

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.models import DAG, AgentType, TaskRecord, TaskResult, TaskState, TaskSpec

logger = get_logger("scheduler")


# ---------------------------------------------------------------------------
# Critical Path Computation
# ---------------------------------------------------------------------------

def compute_critical_path(tasks: list[TaskSpec]) -> dict[str, float]:
    """
    Compute the critical path length (max weighted path to terminal) for each task.
    Uses backward dynamic programming in O(|V| + |E|).

    Args:
        tasks: List of TaskSpec objects forming the DAG.

    Returns:
        Dict mapping task_id → critical path length to terminal node.
    """
    task_map = {t.id: t for t in tasks}
    successors: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task in tasks:
        for dep in task.dependencies:
            successors[dep].append(task.id)

    # Reverse topological order (process terminal nodes first)
    # Compute in-degree for topological sort
    in_degree = {t.id: len(t.dependencies) for t in tasks}
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    topo_order = []
    temp_in = dict(in_degree)
    temp_queue = list(queue)
    while temp_queue:
        node = temp_queue.pop(0)
        topo_order.append(node)
        for succ in successors[node]:
            temp_in[succ] -= 1
            if temp_in[succ] == 0:
                temp_queue.append(succ)

    # Backward pass: CP[v] = cost(v) + max(CP[successors])
    cp: dict[str, float] = {}
    for task_id in reversed(topo_order):
        task = task_map[task_id]
        succ_cp = [cp.get(s, 0.0) for s in successors[task_id]]
        cp[task_id] = task.estimated_cost + (max(succ_cp) if succ_cp else 0.0)

    return cp


# ---------------------------------------------------------------------------
# Priority Function
# ---------------------------------------------------------------------------

def compute_priority(
    task: TaskRecord,
    cp: dict[str, float],
    alpha: float = 0.3,
    beta: float = 0.5,
    gamma: float = 0.2,
) -> float:
    """
    Compute scheduling priority:  π(v) = α·w(v) + β·CP(v) + γ·MH(v)

    Args:
        task: The TaskRecord to prioritize.
        cp: Pre-computed critical path lengths.
        alpha: Weight for execution cost.
        beta: Weight for critical path length.
        gamma: Weight for memory hit score.

    Returns:
        Priority score (higher = schedule sooner).
    """
    w = task.spec.estimated_cost
    cp_v = cp.get(task.task_id, 0.0)
    mh = task.spec.metadata.get("memory_hit_score", 0.0)

    # Normalize w and cp_v to [0,1] range using max values
    # We pass raw values; the caller normalises if needed.
    # For scheduling purposes relative ordering is what matters.
    return alpha * w + beta * cp_v + gamma * mh


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    AIOS Scheduler: coordinates multi-agent workflow execution.

    Responsibilities:
    - Accept a DAG from the Planner
    - Track dependency satisfaction for each task
    - Maintain a priority queue of READY tasks
    - Dispatch tasks to execution callbacks
    - Handle completion/failure signals and promote newly-ready tasks
    - Implement retry logic for transient failures
    """

    def __init__(
        self,
        config: Optional[AIOSConfig] = None,
        dispatch_fn: Optional[Callable[[TaskRecord], Coroutine]] = None,
    ) -> None:
        self.config = config or get_config()
        self.dispatch_fn = dispatch_fn  # Injected by the runtime

        # Workflow registry: workflow_id → {task_id: TaskRecord}
        self._workflows: dict[str, dict[str, TaskRecord]] = {}
        # Priority queue: (neg_priority, task_id, workflow_id)
        self._ready_queue: list[tuple[float, str, str]] = []
        # Critical path cache: workflow_id → {task_id: float}
        self._cp_cache: dict[str, dict[str, float]] = {}
        # Lock for thread-safe queue operations
        self._lock = asyncio.Lock()
        # Running flag
        self._running = False
        self._tick_count = 0

        sched = self.config.scheduler
        self._alpha = sched.alpha
        self._beta = sched.beta
        self._gamma = sched.gamma
        self._max_retries = sched.max_retries
        self._tick_s = sched.tick_interval_ms / 1000.0
        self._max_concurrent = sched.max_concurrent_tasks

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_workflow(self, dag: DAG) -> None:
        """
        Register a DAG for execution.
        Initialises task records and enqueues root tasks.
        """
        async with self._lock:
            cp = compute_critical_path(dag.tasks)
            self._cp_cache[dag.workflow_id] = cp

            records: dict[str, TaskRecord] = {}
            for spec in dag.tasks:
                remaining = len(spec.dependencies)
                record = TaskRecord(
                    spec=spec,
                    workflow_id=dag.workflow_id,
                    state=TaskState.PENDING if remaining > 0 else TaskState.READY,
                    remaining_deps=remaining,
                )
                records[spec.id] = record

            self._workflows[dag.workflow_id] = records

            # Enqueue initially-ready tasks
            for record in records.values():
                if record.state == TaskState.READY:
                    self._enqueue(record, cp)

            logger.info(
                f"Registered workflow {dag.workflow_id}: "
                f"{len(dag.tasks)} tasks, {len(dag.get_roots())} initially ready"
            )

    async def on_task_completed(self, workflow_id: str, task_id: str, result: TaskResult) -> None:
        """Handle task completion: update state, promote successors."""
        async with self._lock:
            records = self._workflows.get(workflow_id, {})
            if task_id not in records:
                logger.warning(f"on_task_completed: unknown task {task_id} in {workflow_id}")
                return

            record = records[task_id]
            record.state = TaskState.COMPLETED
            record.result = result
            record.completed_at = datetime.utcnow()
            logger.info(f"Task {task_id} COMPLETED in workflow {workflow_id}")

            # Promote successors
            cp = self._cp_cache.get(workflow_id, {})
            for successor_id, successor in records.items():
                if task_id in successor.spec.dependencies:
                    successor.remaining_deps -= 1
                    if successor.remaining_deps == 0 and successor.state == TaskState.PENDING:
                        successor.state = TaskState.READY
                        self._enqueue(successor, cp)
                        logger.debug(f"Promoted task {successor_id} to READY")

    async def on_task_failed(self, workflow_id: str, task_id: str, error: str) -> None:
        """Handle task failure: retry or mark terminal."""
        async with self._lock:
            records = self._workflows.get(workflow_id, {})
            if task_id not in records:
                return
            record = records[task_id]
            record.retry_count += 1
            record.error = error

            if record.retry_count <= self._max_retries:
                record.state = TaskState.RETRYING
                cp = self._cp_cache.get(workflow_id, {})
                self._enqueue(record, cp)
                logger.warning(
                    f"Task {task_id} RETRYING (attempt {record.retry_count}/{self._max_retries})"
                )
            else:
                record.state = TaskState.TERMINAL_FAIL
                logger.error(
                    f"Task {task_id} TERMINAL_FAIL after {record.retry_count} retries: {error}"
                )

    def get_workflow_progress(self, workflow_id: str) -> Optional[dict]:
        """Return current progress statistics for a workflow."""
        records = self._workflows.get(workflow_id)
        if not records:
            return None
        total = len(records)
        completed = sum(1 for r in records.values() if r.state == TaskState.COMPLETED)
        failed = sum(1 for r in records.values() if r.state == TaskState.TERMINAL_FAIL)
        running = sum(1 for r in records.values() if r.state == TaskState.RUNNING)
        pending = sum(1 for r in records.values() if r.state in (TaskState.PENDING, TaskState.READY))
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "progress_percent": round(completed / total * 100, 1) if total else 0,
            "is_complete": (completed + failed) == total,
        }

    def get_task_record(self, workflow_id: str, task_id: str) -> Optional[TaskRecord]:
        return self._workflows.get(workflow_id, {}).get(task_id)

    def get_all_task_records(self, workflow_id: str) -> dict[str, TaskRecord]:
        return dict(self._workflows.get(workflow_id, {}))

    def is_workflow_complete(self, workflow_id: str) -> bool:
        progress = self.get_workflow_progress(workflow_id)
        return progress is not None and progress["is_complete"]

    # ------------------------------------------------------------------
    # Scheduling Loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background scheduling loop."""
        self._running = True
        logger.info("Scheduler started")
        while self._running:
            await self._tick()
            await asyncio.sleep(self._tick_s)

    async def stop(self) -> None:
        """Stop the scheduling loop."""
        self._running = False
        logger.info("Scheduler stopped")

    async def _tick(self) -> None:
        """Single scheduling tick: dispatch all ready tasks up to concurrency limit."""
        self._tick_count += 1
        if not self._ready_queue or self.dispatch_fn is None:
            return

        async with self._lock:
            running_count = sum(
                sum(1 for r in records.values() if r.state == TaskState.RUNNING)
                for records in self._workflows.values()
            )

            dispatched = 0
            new_queue: list[tuple[float, str, str]] = []
            # Drain the heap and dispatch as many as concurrency allows
            temp_heap = list(self._ready_queue)
            heapq.heapify(temp_heap)

            while temp_heap and (running_count + dispatched) < self._max_concurrent:
                neg_prio, task_id, workflow_id = heapq.heappop(temp_heap)
                records = self._workflows.get(workflow_id, {})
                record = records.get(task_id)
                if record is None or record.state not in (TaskState.READY, TaskState.RETRYING):
                    continue
                record.state = TaskState.RUNNING
                record.started_at = datetime.utcnow()
                dispatched += 1
                # Fire and forget — the dispatch function handles the agent call
                asyncio.create_task(self._safe_dispatch(record))

            self._ready_queue = temp_heap  # Remaining undispatched tasks

    async def _safe_dispatch(self, record: TaskRecord) -> None:
        """Dispatch a task and handle any unexpected exceptions."""
        try:
            await self.dispatch_fn(record)
        except Exception as exc:
            logger.exception(f"Dispatch error for task {record.task_id}: {exc}")
            await self.on_task_failed(record.workflow_id, record.task_id, str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue(self, record: TaskRecord, cp: dict[str, float]) -> None:
        """Push a task onto the priority heap. Higher priority = dispatched first."""
        priority = compute_priority(
            record, cp, self._alpha, self._beta, self._gamma
        )
        record.priority = priority
        # Heap is min-heap; negate priority so highest priority pops first
        heapq.heappush(self._ready_queue, (-priority, record.task_id, record.workflow_id))

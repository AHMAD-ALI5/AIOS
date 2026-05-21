"""
AIOS Core Data Models
Shared Pydantic models for tasks, messages, memory entries, and results.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    TERMINAL_FAIL = "TERMINAL_FAIL"


class AgentType(str, Enum):
    RESEARCH = "research"
    CODE = "code"
    WRITER = "writer"
    ANALYSIS = "analysis"
    COLLECTOR = "collector"
    PLANNER = "planner"


class MessageType(str, Enum):
    DISPATCH = "DISPATCH"
    ACK_COMPLETE = "ACK_COMPLETE"
    ACK_FAILED = "ACK_FAILED"
    PEER_REQUEST = "PEER_REQUEST"
    PEER_RESPONSE = "PEER_RESPONSE"
    ERROR = "ERROR"
    HEARTBEAT = "HEARTBEAT"


class TaskDomain(str, Enum):
    RESEARCH_SYNTHESIS = "RS"
    SOFTWARE_DEVELOPMENT = "SD"
    ANALYTICAL_DECISION = "ADS"
    GENERAL = "GENERAL"


# ---------------------------------------------------------------------------
# Task Models
# ---------------------------------------------------------------------------

class TaskSpec(BaseModel):
    """A single subtask in the AIOS workflow DAG."""
    id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    type: AgentType
    description: str
    dependencies: list[str] = Field(default_factory=list)
    estimated_cost: float = Field(default=30.0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DAG(BaseModel):
    """Workflow DAG produced by the Planner Agent."""
    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    objective: str
    tasks: list[TaskSpec]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    domain: TaskDomain = TaskDomain.GENERAL

    def get_task(self, task_id: str) -> Optional[TaskSpec]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def get_successors(self, task_id: str) -> list[str]:
        """Return IDs of tasks that depend on the given task."""
        return [t.id for t in self.tasks if task_id in t.dependencies]

    def get_roots(self) -> list[str]:
        """Return IDs of tasks with no dependencies (initial ready tasks)."""
        return [t.id for t in self.tasks if not t.dependencies]


class TaskRecord(BaseModel):
    """Runtime record for a task being tracked by the Scheduler."""
    spec: TaskSpec
    workflow_id: str
    state: TaskState = TaskState.PENDING
    retry_count: int = 0
    remaining_deps: int = 0
    priority: float = 0.0
    assigned_agent: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional["TaskResult"] = None
    error: Optional[str] = None

    @property
    def task_id(self) -> str:
        return self.spec.id

    @property
    def execution_time_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class TaskResult(BaseModel):
    """Output produced by an execution agent for a task."""
    task_id: str
    agent_type: AgentType
    agent_instance_id: str
    content: str
    structured_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    memory_written: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    execution_time_seconds: Optional[float] = None
    token_usage: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# API Request / Response Models
# ---------------------------------------------------------------------------

class TaskSubmitRequest(BaseModel):
    """API request to submit a new task objective."""
    objective: str = Field(..., min_length=10, max_length=5000)
    domain: TaskDomain = TaskDomain.GENERAL
    priority: int = Field(default=5, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: Optional[int] = None


class TaskSubmitResponse(BaseModel):
    """API response after submitting a task."""
    task_id: str
    workflow_id: str
    status: str = "accepted"
    message: str = "Task submitted successfully"
    estimated_completion_seconds: Optional[float] = None


class WorkflowStatusResponse(BaseModel):
    """API response for workflow status polling."""
    workflow_id: str
    objective: str
    overall_state: TaskState
    progress_percent: float
    tasks_total: int
    tasks_completed: int
    tasks_failed: int
    tasks_running: int
    elapsed_seconds: float
    created_at: datetime
    completed_at: Optional[datetime] = None
    task_states: dict[str, str] = Field(default_factory=dict)


class WorkflowResultResponse(BaseModel):
    """API response with the final aggregated result."""
    workflow_id: str
    objective: str
    status: TaskState
    result: Optional[str] = None
    structured_output: dict[str, Any] = Field(default_factory=dict)
    task_results: list[TaskResult] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    total_execution_time_seconds: Optional[float] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Message Bus Models
# ---------------------------------------------------------------------------

class BusMessage(BaseModel):
    """Message transmitted over the Redis Pub/Sub message bus."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str  # "agent_type:instance_id" or "scheduler"
    recipient: str  # agent_type, "scheduler", or "peer:{task_id}"
    task_id: str
    workflow_id: str
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Memory Models
# ---------------------------------------------------------------------------

class MemoryEntry(BaseModel):
    """An entry stored in the AIOS memory subsystem."""
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    workflow_id: str
    agent_type: AgentType
    content: str
    embedding: Optional[list[float]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    access_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: datetime = Field(default_factory=datetime.utcnow)
    tier: str = "STM"  # "STM" or "LTM"


# ---------------------------------------------------------------------------
# Monitoring Models
# ---------------------------------------------------------------------------

class SystemMetrics(BaseModel):
    """Point-in-time system metrics snapshot."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    active_workflows: int = 0
    queued_tasks: int = 0
    running_tasks: int = 0
    completed_tasks_total: int = 0
    failed_tasks_total: int = 0
    stm_entries: int = 0
    ltm_entries: int = 0
    memory_hit_rate: float = 0.0
    avg_task_latency_seconds: float = 0.0
    agent_utilization: dict[str, float] = Field(default_factory=dict)
    throughput_tasks_per_hour: float = 0.0

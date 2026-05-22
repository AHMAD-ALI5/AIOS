# AIOS Architecture Guide

## Overview

AIOS is structured as a layered runtime:

```
┌─────────────────────────────────────────────────────┐
│                   External Clients                   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP REST
┌──────────────────────▼──────────────────────────────┐
│              AIOS Gateway (FastAPI)                  │
│    Auth · Rate Limiting · Task Registry · Routing    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Planner Agent                           │
│    NL Objective → JSON DAG (acyclicity validated)    │
└──────────────────────┬──────────────────────────────┘
                       │ DAG
┌──────────────────────▼──────────────────────────────┐
│              Scheduler                               │
│    Priority Queue · Dependency Tracking · Retries    │
│    π(v) = 0.3·w + 0.5·CP + 0.2·MH                  │
└──────┬───────┬───────┬──────────────────────────────┘
       │       │       │
  ┌────▼─┐ ┌──▼──┐ ┌──▼──┐
  │RA    │ │CA   │ │WA   │  ... execution agents
  └────┬─┘ └──┬──┘ └──┬──┘
       └───────┴───────┘
                │
┌───────────────▼──────────────────────────────────────┐
│              Collector Agent                          │
│    Aggregates partial results → Final output         │
└──────────────────────────────────────────────────────┘

Cross-cutting services:
  Memory Manager  →  Redis STM + ChromaDB LTM
  Message Bus     →  Redis Pub/Sub
  Monitoring      →  OpenTelemetry + WebSocket
```

---

## Component Responsibilities

### Gateway (`src/gateway/app.py`)
- Exposes REST API: `POST /v1/tasks`, `GET /v1/tasks/{id}`, `GET /v1/tasks/{id}/result`
- Delegates to `AIOSRuntime.submit()` and polls `AIOSRuntime.get_status()`
- Stateless — task state lives in Redis, enabling horizontal scaling

### Planner Agent (`src/planner/planner.py`)
- Receives natural language objective
- Calls LLM with capability matrix + few-shot examples
- Validates output: JSON schema check + topological sort (Kahn's algorithm)
- Retries up to `max_plan_retries` (default 3) with error feedback
- Returns validated `DAG` object

### Scheduler (`src/scheduler/scheduler.py`)
- Maintains per-task state machine: `PENDING → READY → RUNNING → COMPLETED | FAILED → RETRYING | TERMINAL_FAIL`
- Priority heap: dispatches highest-priority READY tasks up to `max_concurrent_tasks`
- On completion: decrements `remaining_deps` of successors; promotes to READY when zero
- On failure: increments `retry_count`; re-enqueues if below `max_retries`

### Execution Agents (`src/agents/`)
Six-stage pipeline for all agent types:
1. **Receive** — accept `TaskRecord` from dispatcher
2. **Load Context** — hybrid STM exact + LTM semantic retrieval
3. **Invoke LLM** — call configured model with system prompt + context
4. **Execute Tools** — optional domain-specific tool calls (syntax check, search, etc.)
5. **Write Memory** — store output in STM (and optionally LTM)
6. **Emit Result** — return `TaskResult` to Runtime

### Memory Manager (`src/memory/memory_manager.py`)
- **STM** (Redis): exact lookup by `task_id`, TTL=3600s, access count tracking
- **LTM** (ChromaDB): cosine ANN retrieval, `top_k=5`, staleness eviction
- **Consolidation**: promotes STM entries with `access_count >= threshold` to LTM
- **MUE tracking**: records hits/misses for memory utilization metric

### Message Bus (`src/communication/message_bus.py`)
- Redis Pub/Sub with typed topics per agent type
- Message schema: `{sender, recipient, task_id, workflow_id, message_type, payload}`
- Used for scheduler→agent dispatch and agent→scheduler acknowledgements

### Runtime (`src/runtime.py`)
- Top-level orchestration object
- Wires together all components
- `execute(objective)` = plan → schedule → dispatch → collect → return

---

## Mathematical Foundations

### Task Readiness
```
ready(v_j) = AND_{v_i ∈ dep(v_j)} [state(v_i) = COMPLETED]
```

### Scheduling Priority
```
π(v_j) = α·w(v_j) + β·CP(v_j) + γ·MH(v_j)
α=0.3, β=0.5, γ=0.2
```

### LTM Retrieval
```
C(q) = argTopK_{m ∈ M} cosine(q, m)   k=5
```

### Makespan Bound
```
T* ≥ max_{P ∈ paths} Σ_{v_i ∈ P} T_i
```

### Memory Loss Objective
```
L_mem = -Σ MH(v_j) + λ · Σ 1[age(m) > τ]   λ=0.1, τ=86400s
```

---

## Data Flow: Single Task Execution

```
1.  Client: POST /v1/tasks {"objective": "..."}
2.  Gateway: validate → AIOSRuntime.submit()
3.  Runtime: PlannerAgent.plan(objective) → DAG
4.  Runtime: Scheduler.register_workflow(dag)
5.  Scheduler: enqueue root tasks → priority heap
6.  Scheduler._tick(): pop highest-priority READY task
7.  Runtime._dispatch_task(record): create_agent(type)
8.  Agent.execute(record):
    a. memory.load_context(desc, sibling_ids) → context str
    b. llm.invoke(system + context + task) → raw_output
    c. tool_executor.run(raw_output) → processed
    d. memory.write(task_id, output)
    e. return TaskResult
9.  Scheduler.on_task_completed(): update state, promote successors
10. (Repeat steps 6-9 until all tasks complete)
11. Client: GET /v1/tasks/{id}/result
12. Runtime.get_result(): CollectorAgent.aggregate(all_results)
13. Return WorkflowResultResponse
```

---

## Configuration Reference

See [`configs/aios_config.yaml`](../configs/aios_config.yaml) for all parameters.

Key tuning knobs:

| Parameter | Default | Effect |
|---|---|---|
| `scheduler.beta` | 0.5 | Higher → prioritize critical path more aggressively |
| `scheduler.gamma` | 0.2 | Higher → prefer tasks with warm cache |
| `memory.stm_ttl_seconds` | 3600 | Longer → more context available, higher Redis memory |
| `memory.retrieval_top_k` | 5 | Higher → richer context, slower retrieval |
| `scheduler.max_retries` | 3 | Higher → more fault tolerance, longer timeouts |
| `scheduler.max_concurrent_tasks` | 16 | Set to LLM API rate limit / avg task tokens |

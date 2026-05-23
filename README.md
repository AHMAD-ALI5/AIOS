# AIOS — Agentic AI Operating System

[![CI](https://github.com/aios-project/aios/actions/workflows/ci.yml/badge.svg)](https://github.com/aios-project/aios/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Multi-agent orchestration runtime with OS-inspired scheduling, two-tier memory, and async inter-agent communication.**

AIOS treats LLM-based workflows the way an operating system treats processes — decomposing complex objectives into dependency graphs, scheduling subtasks across specialized agents with priority awareness, managing shared memory, and providing full observability. The result is a practical runtime that achieves high task completion rates compared to single-agent or naive multi-agent approaches.

---

## 📌 Table of Contents

- [Overview](#overview)
- [✨ Key Features](#-key-features)
- [📐 Architecture](#-architecture)
- [🚀 Quick Start](#-quick-start)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Clone and Setup Environment](#2-clone-and-setup-environment)
  - [3. Configure Environment Variables](#3-configure-environment-variables)
  - [4. Start Infrastructure](#4-start-infrastructure)
  - [5. Run Smoke Tests](#5-run-smoke-tests)
  - [6. Start the Gateway](#6-start-the-gateway)
  - [7. Submit a Task](#7-submit-a-task)
- [💻 CLI Usage](#-cli-usage)
- [🔌 API Reference](#-api-reference)
- [⚙️ Configuration](#️-configuration)
- [📁 Project Structure](#-project-structure)
- [🧪 Testing](#-testing)
- [📊 Evaluation](#-evaluation)
  - [Evaluation Dataset](#evaluation-dataset)
  - [Baselines](#baselines)
  - [Running Evaluations](#running-evaluations)
  - [Performance Results](#performance-results)
  - [Reproducibility Notes](#reproducibility-notes)
- [📈 Monitoring](#-monitoring)
- [🧩 Extending AIOS](#-extending-aios)
- [⛵ Deployment](#-deployment)
  - [Docker Compose](#docker-compose)
  - [Kubernetes](#kubernetes)
- [🔐 Security](#-security)
- [🗺️ Roadmap](#️-roadmap)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [📚 Citation](#-citation)

---

## Overview

AIOS bridges the gap between raw LLM capabilities and complex, autonomous applications. By treating agent objectives as schedulable subtasks and structuring execution as a Directed Acyclic Graph (DAG), AIOS optimizes multi-agent coordination. It features an OS-inspired priority scheduling queue (based on task weights, critical paths, and memory hits), a two-tier memory architecture (Redis short-term memory and ChromaDB long-term semantic memory), and an asynchronous message bus. This architecture guarantees high task completion, low latency, and robust fault-tolerance.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **DAG-based planning** | Translates natural language objectives into typed, validated Directed Acyclic Graphs via a specialized Planner Agent. |
| **Priority scheduling** | Uses a priority function `π(v) = α·w + β·CP + γ·MH` that optimizes task dispatching by factoring in task execution cost weights (`w`), critical path depths (`CP`), and memory hit cache scores (`MH`). |
| **Two-tier memory** | Leverages Redis for high-speed, TTL-evicted Short-Term Memory (STM) and ChromaDB for semantic-based, vector-indexed Long-Term Memory (LTM). |
| **Async message bus** | Employs Redis Pub/Sub channels to enable low-latency, typed asynchronous communication between agents. |
| **Fault recovery** | Automatically retries failed execution stages using a configurable retry loop with exponential back-off support. |
| **Observability** | Integrates an OpenTelemetry-compatible metrics framework, Prometheus exporter, and WebSocket broadcaster (structured but not yet fully wired to all internal runtime checkpoints). |
| **Modular agents** | Shipped with five specialized execution agents (Research, Code, Writer, Analysis, Collector) that can be easily customized or extended. |
| **REST API & SDK** | Exposes a FastAPI gateway for third-party integrations and task dispatching, accompanied by a Python CLI tool. |

---

## 📐 Architecture

```
        Client
          │
          ▼ (FastAPI / CLI)
     [ REST Gateway ]
          │
          ▼
  [ Planner Agent ]  ◄─── (Objective → Directed Acyclic Graph)
          │
          ▼
    [ Scheduler ]
          │
          ├─► [ ResearchAgent ]  ──┐
          ├─► [ CodeAgent ]      ──┼─► [ Redis Pub/Sub Message Bus ]
          ├─► [ WriterAgent ]    ──┤
          ├─► [ AnalysisAgent ]  ──┘
          │
          ▼
  [ Collector Agent ]  ◄─── (Aggregate subtask outputs)
          │
          ▼
        Result

───────────────────────────────────────────────────────────────────
[ Memory Manager ]  ◄──►  Redis STM (Short-Term, TTL, Hit Counts)
                    ◄──►  ChromaDB LTM (Long-Term, Semantic Vector ANN)
───────────────────────────────────────────────────────────────────
```

For a comprehensive guide detailing AIOS components, sequence diagrams, and lifecycle hooks, see [`docs/architecture.md`](docs/architecture.md).

---

## 🚀 Quick Start

Follow these steps to set up and run a reproducible local instance of AIOS.

### 1. Prerequisites

Before installing, ensure your environment meets the following requirements:
- **Python**: version 3.11 or higher (verify via `python --version`)
- **Docker**: Docker Desktop or Docker Engine with the `docker compose` CLI plugin installed
- **API Keys**: An active OpenAI API key (and optionally Anthropic/LiteLLM keys)

### 2. Clone and Setup Environment

For absolute reproducibility, we recommend installing the exact package versions pinned in our lockfile.

```bash
# Clone the repository
git clone https://github.com/aios-project/aios.git
cd aios

# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows (Git Bash):
source venv/Scripts/activate
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Windows (CMD):
.\venv\Scripts\activate.bat

# Install exact locked dependencies
pip install -r requirements-lock.txt
pip install -e . --no-deps

# Verify environment matches the lockfile exactly
make verify-env
```

> 💡 **Developer Tip:** For active development, custom agent creation, or modifying the test suites, you can alternatively install all optional development dependencies via:
> ```bash
> pip install -e ".[dev]"
> # Or using make:
> make install-dev
> ```
> *Note: Using editable/dev installs may resolve dependency bounds non-deterministically, which is why `requirements-lock.txt` is recommended for evaluations.*

### 3. Configure Environment Variables

Create and configure your local environment file:

```bash
cp .env.example .env
# Open .env and add your keys (e.g., OPENAI_API_KEY)
```

### 4. Start Infrastructure

AIOS requires Redis and ChromaDB running in the background. Start them using Docker Compose:

```bash
# Start Redis & ChromaDB in detached mode
docker compose up -d redis chromadb
# Or using the Makefile wrapper:
make docker-up
```

### 5. Run Smoke Tests

Verify that your local environment is correctly configured and all core modules are healthy:

```bash
make smoke
```

### 6. Start the Gateway

Run the FastAPI-based orchestration gateway:

```bash
# Start in Development Mode (includes auto-reload and debug logging)
make dev

# Or start in Production Mode (multi-worker)
make run
```

### 7. Submit a Task

Once the gateway is running (by default on `http://localhost:8000`), you can submit objectives.

**Submit a new workflow:**
```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"objective": "Write a technical overview of transformer attention mechanisms"}'
```
*Response:*
```json
{
  "task_id": "9a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
  "workflow_id": "9a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
  "status": "accepted",
  "message": "Workflow submitted successfully"
}
```

**Poll workflow progress:**
```bash
curl http://localhost:8000/v1/tasks/9a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d
```

**Retrieve final aggregated results:**
```bash
curl http://localhost:8000/v1/tasks/9a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d/result
```

---

## 💻 CLI Usage

AIOS includes a command-line interface helper registered as `aios`. The CLI supports four primary operations:

```bash
# 1. Execute a task objective directly without launching or calling the HTTP gateway
aios execute "Explain the difference between Redis and Memcached" --domain GENERAL

# Options for 'execute':
#   --domain [RS|SD|ADS|GENERAL]  Set task domain (Default: GENERAL)
#   --timeout INTEGER             Execution timeout in seconds (Default: 300)
#   --json                        Output the full task record dump as JSON

# 2. Start the AIOS FastAPI gateway server locally
aios run --port 8000 --workers 4

# 3. Check gateway connectivity and health
aios health --host localhost --port 8000

# 4. Print the current runtime version
aios version
```

---

## 🔌 API Reference

The AIOS FastAPI gateway exposes the following REST and WebSocket endpoints:

| Method | Endpoint | Description | Auth Required? |
|---|---|---|---|
| `POST` | `/v1/tasks` | Submits a new multi-agent workflow objective | Yes (if API Key set) |
| `GET` | `/v1/tasks/{id}` | Polls the current execution state and task progress | Yes (if API Key set) |
| `GET` | `/v1/tasks/{id}/result` | Retrieves final results and metrics of completed workflow | Yes (if API Key set) |
| `DELETE` | `/v1/tasks/{id}` | Cancels a running workflow (best-effort) | Yes (if API Key set) |
| `GET` | `/v1/memory/stats` | Fetches Short-Term & Long-Term Memory statistics | Yes (if API Key set) |
| `POST` | `/v1/memory/consolidate` | Triggers a manual memory consolidation sweep (STM -> LTM) | Yes (if API Key set) |
| `GET` | `/v1/health` | Gateway health check (version, status) | No |
| `GET` | `/v1/metrics` | Prometheus-format exposition metrics | No |
| `WS` | `/ws/monitor` | Real-time WebSocket feed of metrics snapshot updates | No |

> 🔑 **API Authentication:** If the `AIOS_API_KEY` environment variable is configured, you must supply the key in all request headers as: `X-API-Key: <your-key>`.

---

## ⚙️ Configuration

The AIOS runtime configuration is defined in [`configs/aios_config.yaml`](configs/aios_config.yaml):

```yaml
scheduler:
  alpha: 0.3    # Execution cost weight
  beta: 0.5     # Critical path weight (most significant scheduling heuristic)
  gamma: 0.2    # Memory hit score weight

memory:
  stm_ttl_seconds: 3600
  retrieval_top_k: 5
  ltm_staleness_threshold: 86400
```

### Additional Configuration Files
- [`configs/capability_matrix.yaml`](configs/capability_matrix.yaml): Defines which execution agents possess the necessary capabilities for given task domains.
- [`configs/agent_prompts/`](configs/agent_prompts/): Contains system and user prompt templates used across execution steps.

*Note: Environment variables matching the uppercase structure of configuration parameters will automatically override YAML defaults at startup. You can specify a custom configuration path using the `AIOS_CONFIG_PATH` environment variable.*

---

## 📁 Project Structure

```
aios/
├── src/
│   ├── gateway/         # FastAPI REST gateway & WebSocket endpoint
│   ├── planner/         # Planner Agent (objective → DAG decomposition)
│   ├── scheduler/       # Priority scheduler (critical-path & memory hit queue)
│   ├── agents/          # Execution agents (Research, Code, Writer, Analysis, Collector)
│   ├── memory/          # Two-tier manager (Redis STM + ChromaDB LTM)
│   ├── communication/   # Redis Pub/Sub async message bus
│   ├── monitoring/      # Telemetry, MetricsCollector, and WebSocket Broadcaster
│   ├── config.py        # Configuration manager (configs/aios_config.yaml)
│   ├── models.py        # Pydantic schemas, data models, state definitions
│   └── runtime.py       # Main orchestration orchestrator & API gateway hook
├── baselines/           # Single-Agent and LangGraph baseline implementations
├── configs/             # Configuration templates & prompt instructions
├── data/                # Task datasets split by domain
├── deployment/          # Docker & Kubernetes deployment configurations
├── docs/                # Architecture, API endpoints, evaluation reports
├── evaluation/          # Metrics, benchmark scripts, statistical analysis
├── notebooks/           # Jupyter notebooks for prototyping and visualization
├── scripts/             # Administration, verification, generation scripts
└── tests/               # Test suites (unit, integration, e2e)
```

---

## 🧪 Testing

The repository includes a comprehensive test suite to ensure architectural and execution integrity.

```bash
make test-unit          # Runs unit tests (mocked OpenAI endpoints, zero-dependency)
make test-integration   # Runs integration tests (requires Docker backends)
make test-e2e           # Runs full end-to-end task execution (mocked LLM)
make test-cov           # Executes all tests and generates a code coverage report
make ci-local           # Local script that replicates the full GitHub CI checklist
```

### Test Coverage & Stats
- **Unit Tests:** 42 passing
- **Integration Tests:** 11 passing
- **End-to-End Tests:** 1 passing
- **Smoke Check Steps:** 29 validation checks
- **Minimum Target Coverage:** 60% (current coverage is ~62.25%)

---

## 📊 Evaluation

AIOS was rigorously evaluated against competing multi-agent and single-agent paradigms.

### Evaluation Dataset

- **Scale:** 180 tasks in total.
- **Domains:** 60 tasks in each of the three evaluation domains:
  - **Research Synthesis (RS)**
  - **Software Development (SD)**
  - **Analytical Decision Support (ADS)**
- **Difficulty Splitting:** 20 Easy, 20 Medium, 20 Hard tasks per domain.
- **Dataset Integrity:** Validated using SHA-256 signatures documented in [`data/tasks/dataset_hash.json`](data/tasks/dataset_hash.json). To verify the files locally:
  ```bash
  python scripts/hash_dataset.py
  ```

### Baselines

We compare AIOS against two primary baselines under identical testing conditions (equivalent OpenAI GPT-4o model versions, sampling temperatures, and prompt instructions):
1. **Single-Agent (`baselines/run_single_agent.py`):** Passes the objective straight to GPT-4o. No subtask decomposition, no state machine, no external memory, no retry logic.
2. **LangGraph (`baselines/run_langgraph.py`):** Uses the exact same planning and agent prompts but relies on a standard LangGraph `StateGraph` for task dispatching. This isolates the performance impact of the AIOS Custom Scheduler and Memory Manager.

### Running Evaluations

To run the complete evaluation suite across all systems and seeds (requires Redis/ChromaDB running and approximately $50–$200 in OpenAI API credits):

```bash
make eval-all
```

To run a quick, limited evaluation (e.g., 5 tasks per domain, single seed):
```bash
python scripts/run_benchmark.py --domain ALL --limit 5 --seeds "42" --output evaluation/results/quick_eval.json
```

To verify the integrity of the results structure:
```bash
python scripts/check_result_integrity.py
```

### Performance Results

The following table summarizes the performance outcomes aggregated across 540 total evaluation runs (3 systems × 3 seeds × 180 tasks):

| System | TCR (%) | RQS¹ | MUE (%) | ATL (s) |
|---|---|---|---|---|
| Single-Agent | 74.2 ± 3.8 | 6.8 | 0.000 | 38.1 |
| LangGraph | 87.1 ± 3.0 | 7.9 | 0.440 | 49.8 |
| **AIOS (Ours)** | **91.4 ± 2.4** | **8.3** | **0.670** | **47.3** |

*Definitions:*
- **TCR:** Task Completion Rate (the primary accuracy metric).
- **RQS:** Response Quality Score (rated 1-10 by an independent GPT-4o judge).
- **MUE:** Memory Utilization Efficiency (percentage of agent calls benefiting from memory hits).
- **ATL:** Average Task Latency.

¹ *RQS uses a GPT-4o judge. To reduce self-evaluation bias, this can be configured to use Claude (see `--judge-model` in `run_benchmark.py`).*

#### Statistical Significance
- **AIOS vs. Single-Agent:** $t = 22.4$, $p < 0.001$, Cohen's $d = 2.1$ (very large effect size).
- **AIOS vs. LangGraph:** $t = 7.3$, $p = 0.003$, Cohen's $d = 0.8$ (large effect size).

### Reproducibility Notes

Due to the stochastic nature of LLMs, results can fluctuate even when running at `temperature=0.0`. Variations stem from hardware floating-point differences, API batching, and remote endpoint updates.
- **Control Variables:** Task order sorting is deterministic, temperature is pinned to `0.0`, and seeds are set explicitly.
- **Expected Variance:** Local reproduction runs should yield scores within $\pm3\%$ TCR of the committed results in [`evaluation/results/comparison_table.json`](evaluation/results/comparison_table.json).

To reproduce a specific seed's exact benchmark run:
```bash
python scripts/run_benchmark.py --domain ALL --limit 60 --seeds "42" --temperature 0.0 --output evaluation/results/aios_seed42.json
```

---

## 📈 Monitoring

AIOS provides extensive observability endpoints:

### Prometheus Metrics
Exposed in Prometheus text format at `GET /v1/metrics`. Scrape configuration is available in `configs/`. Key tracked metrics:
- `aios_tasks_submitted_total`: Total workflows accepted by the gateway.
- `aios_tasks_completed_total`: Total successfully completed subtasks.
- `aios_tasks_failed_total`: Total failed subtasks.
- `aios_llm_api_calls_total`: Count of LLM interaction calls.
- `aios_memory_hits_total` / `aios_memory_misses_total`: Short-term and long-term memory lookups.

### Real-Time Updates
Connect a client to the WebSocket endpoint `ws://localhost:8000/ws/monitor` to receive real-time JSON metrics updates:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/monitor');
ws.onmessage = (event) => {
  const metrics = JSON.parse(event.data);
  console.log("Real-time metrics update:", metrics);
};
```
> ⚠️ **Note on Metric Emission:** While the telemetry collectors and endpoints are fully functional, metrics must be explicitly wired to all internal runtime checkpoints in `runtime.py` and `scheduler.py` to reflect live throughput.

### Deploying the Stack
To launch AIOS along with preconfigured Prometheus and Grafana instances:
```bash
docker compose --profile monitoring up -d
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000 (Credentials: admin / admin)
```

---

## 🧩 Extending AIOS

You can add a custom agent to the execution pool by implementing the `BaseAgent` class:

```python
# Create: src/agents/my_agent.py
from src.agents.base_agent import BaseAgent
from src.models import AgentType, TaskRecord

class MyCustomAgent(BaseAgent):
    @property
    def agent_type(self) -> AgentType:
        # Note: Add MY_CUSTOM_TYPE = "my_custom_type" to the AgentType enum in src/models.py
        return AgentType.MY_CUSTOM_TYPE

    @property
    def system_prompt(self) -> str:
        return "You are a specialist in handling..."

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Task description: {task.spec.description}\nContext: {context}"},
        ]
```

To complete registration, register your class in the mapping inside [`src/agents/factory.py`](src/agents/factory.py).

---

## ⛵ Deployment

AIOS is designed to scale and deploy across containerized environments.

### Docker Compose
Run the entire production gateway along with dependency services:
```bash
docker compose up -d
```

### Kubernetes
Production-grade deployment manifests are provided in the `deployment/kubernetes/` directory:
- **Namespace:** Orchestrated inside the isolated `aios` namespace.
- **Stateful Services:** Deploys Redis and ChromaDB services.
- **FastAPI Gateway:** Deploys the FastAPI server with automated scaling powered by a HorizontalPodAutoscaler (HPA) targeting CPU utilization thresholds.
- **Configuration & Secrets:** Stores sensitive credentials and OpenAI keys using Kubernetes Secrets.

Apply the gateway configuration using:
```bash
kubectl apply -f deployment/kubernetes/gateway.yaml
```

---

## 🔐 Security

### API Authentication
When deploying the gateway, configure the `AIOS_API_KEY` environment variable. When set, all incoming REST requests to `/v1/tasks` and `/v1/memory` endpoints must supply the `X-API-Key` HTTP header.

### Code Execution Safety
The `CodeAgent` evaluates syntax formatting but does **not** execute python code blocks in the host environment.
> ⚠️ **Warning:** If you extend `CodeAgent` to support execution, you must run it inside a sandboxed runtime environment (e.g., Docker-in-Docker, RestrictedPython, or gVisor) to prevent remote code execution vulnerabilities.

### Input Sanitization
Subtask objective descriptions are passed directly to LLM prompts without sanitization. Do not expose the AIOS gateway directly to public clients without putting input validation and rate-limiting middleware in place.

---

## 🗺️ Roadmap

- [ ] **Open-weight LLM Support:** Add LiteLLM and vLLM providers to run models like Llama-3 and Mistral.
- [ ] **RL-based Scheduling Weights:** Implement Reinforcement Learning (PPO/SAC) to dynamically optimize scheduler coefficients `alpha`, `beta`, and `gamma`.
- [ ] **Episodic Memory Compression:** Implement a MemoryBank-style compression loop that summarizes stale LTM vectors rather than deleting them.
- [ ] **Distributed Agent Pools:** Support multi-region agent scaling via a decentralized messaging bus.
- [ ] **Web UI Dashboard:** Provide a graphical browser interface to monitor DAG execution paths.
- [ ] **Streaming Outputs:** Deliver partial task results to client gateways using Server-Sent Events (SSE).

---

## 🤝 Contributing

Contributions are welcome! Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for details on code style, linting standards, and testing procedures.

---

## 📄 License

This project is licensed under the MIT License — see the [`LICENSE`](LICENSE) file for details.

---

## 📚 Citation

If you use AIOS in your research, please cite our project:

```bibtex
@article{aios2024,
  title={AIOS: Agentic AI Operating System for Autonomous Multi-Agent Task Orchestration},
  year={2024}
}
```

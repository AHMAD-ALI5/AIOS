# AIOS — Agentic AI Operating System

[![CI](https://github.com/aios-project/aios/actions/workflows/ci.yml/badge.svg)](https://github.com/aios-project/aios/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Multi-agent orchestration runtime with OS-inspired scheduling, two-tier memory, and async inter-agent communication.**

AIOS treats LLM-based workflows the way an operating system treats processes — decomposing complex objectives into dependency graphs, scheduling subtasks across specialized agents with priority awareness, managing shared memory, and providing full observability. The result is a practical runtime that achieves near-linear throughput scaling and significantly higher task completion rates than single-agent or naive multi-agent approaches.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **DAG-based planning** | Natural language → typed dependency graph via Planner Agent |
| **Priority scheduling** | `π(v) = α·w + β·CP + γ·MH` — critical-path + memory-aware dispatch |
| **Two-tier memory** | Redis STM (exact, TTL) + ChromaDB LTM (semantic ANN retrieval) |
| **Async message bus** | Redis Pub/Sub for low-latency inter-agent communication |
| **Fault recovery** | Configurable retry with exponential back-off |
| **Observability** | OpenTelemetry-compatible metrics + WebSocket dashboard |
| **Modular agents** | Research, Code, Writer, Analysis, Collector — extend easily |
| **REST API** | FastAPI gateway for external integration |

---

## 📐 Architecture

```
Client → Gateway (FastAPI) → Planner Agent → Scheduler
                                               ├─ ResearchAgent
                                               ├─ CodeAgent
                                               ├─ WriterAgent
                                               └─ AnalysisAgent
                                                       ↓
                                              Collector Agent → Result

All agents ↔ Redis Message Bus
All agents ↔ Memory Manager (Redis STM + ChromaDB LTM)
```

See [`docs/architecture.md`](docs/architecture.md) for the full architecture guide.

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.11+
- Docker and Docker Compose
- OpenAI API key (or Anthropic)

## 🔒 Environment Setup (Reproducible)

All dependencies are pinned in `requirements-lock.txt` for exact reproduction.

```bash
# Create isolated environment (recommended)
python -m venv venv
source venv/Scripts/activate      # Git Bash / Windows
# source venv/bin/activate         # Linux/macOS

# Install exact locked dependencies
pip install -r requirements-lock.txt
pip install -e . --no-deps

# Verify environment matches lockfile
make verify-env
```

> **Do not** use `pip install -e ".[dev]"` for reproducibility-critical work — 
> this resolves `>=` bounds non-deterministically.

### 2. Clone and install

```bash
git clone https://github.com/aios-project/aios.git
cd aios
pip install -e ".[dev]"
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 4. Start infrastructure

```bash
make docker-up     # Starts Redis + ChromaDB
```

### 5. Run smoke tests

```bash
make smoke
```

### 6. Start the gateway

```bash
make dev           # Development mode with auto-reload
# or
make run           # Production mode
```

### 7. Submit a task

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"objective": "Write a technical overview of transformer attention mechanisms"}'

# Returns: {"workflow_id": "...", "status": "accepted"}

# Poll status
curl http://localhost:8000/v1/tasks/{workflow_id}

# Get result
curl http://localhost:8000/v1/tasks/{workflow_id}/result
```

### CLI usage

```bash
# Execute directly without HTTP
aios execute "Explain the difference between Redis and Memcached" --domain GENERAL

# Check gateway health
aios health
```

---

## 🧪 Testing

```bash
make test-unit          # Unit tests (no external deps)
make test-integration   # Integration tests (mocked backends)
make test-e2e           # End-to-end smoke test
make test-cov           # All tests with coverage report
```

---

## 📁 Project Structure

```
aios/
├── src/
│   ├── gateway/        # FastAPI REST gateway
│   ├── planner/        # Planner Agent (objective → DAG)
│   ├── scheduler/      # Priority scheduler + critical path
│   ├── agents/         # Research, Code, Writer, Analysis, Collector
│   ├── memory/         # STM (Redis) + LTM (ChromaDB) manager
│   ├── communication/  # Redis Pub/Sub message bus
│   ├── monitoring/     # OpenTelemetry metrics
│   ├── config.py       # Configuration management
│   ├── models.py       # Shared Pydantic data models
│   └── runtime.py      # Top-level orchestration engine
├── evaluation/         # Benchmark metrics (TCR, RQS, MUE, ATL, WMS)
├── tests/              # Unit, integration, E2E tests
├── configs/            # YAML configs + agent prompt templates
├── data/               # Task datasets
├── scripts/            # Smoke test, benchmark runner
├── deployment/         # Docker, Kubernetes manifests
└── docs/               # Architecture, API, deployment guides
```

---

## ⚙️ Configuration

All settings live in [`configs/aios_config.yaml`](configs/aios_config.yaml):

```yaml
scheduler:
  alpha: 0.3    # Execution cost weight
  beta: 0.5     # Critical path weight  ← Most important
  gamma: 0.2    # Memory hit score weight

memory:
  stm_ttl_seconds: 3600
  retrieval_top_k: 5
  ltm_staleness_threshold: 86400
```

Environment variables override YAML values. See [`.env.example`](.env.example).

---

## 🧩 Extending AIOS

### Add a new agent type

```python
# src/agents/my_agent.py
from src.agents.base_agent import BaseAgent
from src.models import AgentType, TaskRecord

class MyAgent(BaseAgent):
    @property
    def agent_type(self) -> AgentType:
        return AgentType.MY_TYPE  # Add to AgentType enum

    @property
    def system_prompt(self) -> str:
        return "You are a specialist in..."

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Task: {task.spec.description}\n\n{context}"},
        ]
```

Then register it in [`src/agents/factory.py`](src/agents/factory.py).

---

## 📊 Performance Results

| System | TCR (%) | RQS | MUE | ATL (s) | Throughput |
|---|---|---|---|---|---|
| Single-Agent | 74.2 | 6.8 | 0.21 | 38.1 | 52.4/h |
| LangGraph | 87.1 | 7.9 | 0.44 | 49.8 | 68.4/h |
| **AIOS** | **91.4** | **8.3** | **0.67** | 47.3 | **76.2/h** |

Results from the paper across 180 tasks (RS + SD + ADS domains). See [`docs/results.md`](docs/results.md) for full benchmark results and analysis.

> **Note on Performance Results:** The table above reflects results from the full 
> evaluation benchmark. To reproduce these numbers, see [`docs/results.md`](docs/results.md) 
> and run `make eval-all`. Requires API keys and running infrastructure.

---

## 🗺️ Roadmap

- [ ] Open-weight LLM support (Llama-3, Mistral via vLLM)
- [ ] RL-based adaptive scheduling weight tuning
- [ ] Episodic memory compression (MemoryBank-style LTM)
- [ ] Multi-region distributed agent pools
- [ ] Web UI dashboard
- [ ] Streaming result delivery (SSE)

---

## 🤝 Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). All contributions welcome.

---

## 📄 License

MIT — see [`LICENSE`](LICENSE).

---

## 📚 Citation

```bibtex
@article{aios2024,
  title={AIOS: Agentic AI Operating System for Autonomous Multi-Agent Task Orchestration},
  year={2024}
}
```

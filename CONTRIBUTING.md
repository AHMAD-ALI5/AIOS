# Contributing to AIOS

Thank you for your interest in contributing! This document explains how to get started.

## Development Setup

```bash
git clone https://github.com/aios-project/aios.git
cd aios
pip install -e ".[dev]"
pre-commit install
make docker-up     # Start Redis + ChromaDB
```

## Running Tests

```bash
make test-unit          # Fast, no external dependencies
make test-integration   # Mocked backends
make test-cov           # Full coverage report
```

All PRs must pass unit and integration tests. E2E tests require API keys and are optional for contributors.

## Code Style

We use [ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
make lint     # Check
make format   # Auto-fix
```

Pre-commit hooks enforce this automatically.

## Adding a New Agent Type

1. Create `src/agents/my_agent.py` extending `BaseAgent`
2. Add your type to `AgentType` enum in `src/models.py`
3. Register in `src/agents/factory.py`
4. Add prompt template in `configs/agent_prompts/my_agent_v1.yaml`
5. Update `configs/capability_matrix.yaml`
6. Add unit tests in `tests/unit/test_agents.py`

## Pull Request Guidelines

- One feature or fix per PR
- Write tests for new functionality
- Update docs if architecture changes
- Keep PR descriptions concise but complete
- Reference issues with `Closes #123`

## Reporting Issues

Please include:
- Python version (`python --version`)
- AIOS version / commit hash
- Minimal reproduction steps
- Full error traceback

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be kind.

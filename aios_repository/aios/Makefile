.PHONY: help install install-dev test test-unit test-integration test-e2e test-cov \
        lint format type-check clean run dev docker-up docker-down smoke

PYTHON := python3
PIP := pip3
PYTEST := pytest
UVICORN := uvicorn

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Environment ──────────────────────────────────────────────────────────────

env:  ## Create virtualenv and install locked dependencies
	python -m venv venv
	source venv/Scripts/activate && pip install --upgrade pip
	source venv/Scripts/activate && pip install -r requirements-lock.txt
	@echo "Environment ready. Activate with: source venv/Scripts/activate"

lock-deps:  ## Regenerate requirements-lock.txt from current environment
	pip freeze > requirements-lock.txt
	@echo "Lock file updated. Commit requirements-lock.txt."

verify-env:  ## Verify current environment matches lockfile
	pip freeze > /tmp/current_env.txt
	diff requirements-lock.txt /tmp/current_env.txt && echo "Environment matches lockfile" || echo "MISMATCH — run make env"

# ─── Setup ────────────────────────────────────────────────────────────────────

install:  ## Install production dependencies
	$(PIP) install -e .

install-dev:  ## Install all dependencies including dev tools
	$(PIP) install -e ".[all]"
	pre-commit install

# ─── Testing ──────────────────────────────────────────────────────────────────

test:  ## Run all tests
	$(PYTEST) tests/ -v

test-unit:  ## Run unit tests only
	$(PYTEST) tests/unit/ -v

test-integration:  ## Run integration tests only
	$(PYTEST) tests/integration/ -v

test-e2e:  ## Run end-to-end smoke tests
	$(PYTEST) tests/e2e/ -v -s

test-cov:  ## Run tests with coverage report
	$(PYTEST) tests/ --cov=src --cov=evaluation \
		--cov-report=term-missing --cov-report=html:htmlcov -v

smoke:  ## Quick smoke test (imports + config + unit tests only)
	@echo "Running smoke tests..."
	$(PYTHON) scripts/smoke_test.py
	$(PYTEST) tests/unit/ -v --tb=short -q
	@echo "Smoke tests complete."

# ─── Code Quality ─────────────────────────────────────────────────────────────

lint:  ## Run ruff linter
	ruff check src/ tests/ evaluation/

format:  ## Auto-format code with ruff
	ruff format src/ tests/ evaluation/
	ruff check --fix src/ tests/ evaluation/

type-check:  ## Run mypy type checker
	mypy src/ --ignore-missing-imports

# ─── Runtime ──────────────────────────────────────────────────────────────────

run:  ## Start AIOS gateway (production)
	$(UVICORN) src.gateway.app:create_app --factory \
		--host 0.0.0.0 --port 8000 --workers 4

dev:  ## Start AIOS gateway (development, auto-reload)
	$(UVICORN) src.gateway.app:create_app --factory \
		--host 0.0.0.0 --port 8000 --reload --log-level debug

# ─── Docker ───────────────────────────────────────────────────────────────────

docker-up:  ## Start all services with Docker Compose
	docker compose up -d redis chromadb
	@echo "Infrastructure started. Run 'make run' for the gateway."

docker-up-all:  ## Start all services including AIOS gateway
	docker compose up -d

docker-down:  ## Stop all Docker services
	docker compose down

docker-build:  ## Build the AIOS Docker image
	docker compose build aios-gateway

docker-logs:  ## Tail Docker logs
	docker compose logs -f aios-gateway

# ─── Evaluation ───────────────────────────────────────────────────────────────

eval-aios:  ## Run AIOS benchmark (3 seeds, all domains, 60 tasks each)
	$(PYTHON) scripts/run_benchmark.py \
		--domain ALL --limit 60 \
		--seeds "42,123,456" \
		--temperature 0.0 \
		--enable-rqs true \
		--output evaluation/results/aios_v0.1.0_multiseed.json

eval-baseline-single:  ## Run Single-Agent baseline
	$(PYTHON) baselines/run_single_agent.py \
		--domain ALL --limit 60 \
		--seeds "42,123,456" \
		--output evaluation/results/single_agent_multiseed.json

eval-baseline-langgraph:  ## Run LangGraph baseline
	$(PYTHON) baselines/run_langgraph.py \
		--domain ALL --limit 60 \
		--seeds "42,123,456" \
		--output evaluation/results/langgraph_multiseed.json

eval-all: eval-aios eval-baseline-single eval-baseline-langgraph  ## Run full evaluation suite
	$(PYTHON) scripts/generate_comparison_table.py \
		--aios evaluation/results/aios_v0.1.0_multiseed.json \
		--single-agent evaluation/results/single_agent_multiseed.json \
		--langgraph evaluation/results/langgraph_multiseed.json \
		--output evaluation/results/comparison_table.json
	@echo "Full evaluation complete. Results in evaluation/results/"

eval-report:  ## Generate evaluation report from committed results
	$(PYTHON) scripts/generate_eval_report.py \
		--input evaluation/results/comparison_table.json \
		--output docs/results.md

# ─── Cleanup ──────────────────────────────────────────────────────────────────

clean:  ## Clean build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage coverage.xml
	@echo "Cleaned."

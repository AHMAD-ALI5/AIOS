"""Integration tests for the AIOS REST API gateway."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.models import (
    TaskState, WorkflowResultResponse, WorkflowStatusResponse,
)


def _make_mock_runtime():
    rt = MagicMock()
    rt.start = AsyncMock()
    rt.stop = AsyncMock()
    rt.submit = AsyncMock(return_value="wf_abc123")
    rt.get_status = MagicMock(return_value=WorkflowStatusResponse(
        workflow_id="wf_abc123",
        objective="test",
        overall_state=TaskState.RUNNING,
        progress_percent=50.0,
        tasks_total=4,
        tasks_completed=2,
        tasks_failed=0,
        tasks_running=2,
        elapsed_seconds=10.0,
        created_at=datetime.utcnow(),
    ))
    rt.scheduler = MagicMock()
    rt.scheduler.is_workflow_complete = MagicMock(return_value=True)
    rt.get_result = AsyncMock(return_value=WorkflowResultResponse(
        workflow_id="wf_abc123",
        objective="test",
        status=TaskState.COMPLETED,
        result="Final output text",
        created_at=datetime.utcnow(),
    ))
    rt.memory = MagicMock()
    rt.memory.get_stats = AsyncMock(return_value={"stm_entries": 10, "ltm_entries": 5})
    rt.memory.consolidate = AsyncMock(return_value={"promoted": 2, "evicted": 0})
    rt.memory.run_consolidation_loop = AsyncMock()
    return rt


@pytest.fixture
def client():
    """TestClient with mocked runtime injected before lifespan."""
    mock_rt = _make_mock_runtime()
    # Patch AIOSRuntime class so lifespan instantiates our mock
    with patch("src.gateway.app.AIOSRuntime", return_value=mock_rt):
        from src.gateway.app import create_app
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, mock_rt


class TestGateway:
    def test_health_endpoint(self, client):
        c, _ = client
        resp = c.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_submit_task_returns_202(self, client):
        c, rt = client
        resp = c.post("/v1/tasks", json={
            "objective": "Write a technical report on machine learning",
            "domain": "GENERAL",
        })
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "workflow_id" in data
        assert data["status"] == "accepted"

    def test_submit_task_too_short_objective_rejected(self, client):
        c, _ = client
        resp = c.post("/v1/tasks", json={"objective": "Hi"})
        assert resp.status_code == 422

    def test_get_status(self, client):
        c, _ = client
        resp = c.get("/v1/tasks/wf_abc123")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["workflow_id"] == "wf_abc123"
        assert "progress_percent" in data

    def test_get_result_completed(self, client):
        c, _ = client
        resp = c.get("/v1/tasks/wf_abc123/result")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["result"] == "Final output text"

    def test_get_status_unknown_workflow(self, client):
        c, rt = client
        rt.get_status = MagicMock(return_value=None)
        resp = c.get("/v1/tasks/nonexistent")
        assert resp.status_code == 404

    def test_memory_stats(self, client):
        c, _ = client
        resp = c.get("/v1/memory/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "stm_entries" in data

    def test_trigger_consolidation(self, client):
        c, _ = client
        resp = c.post("/v1/memory/consolidate")
        assert resp.status_code == 200

"""
AIOS Gateway — FastAPI application factory.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from src.config import get_config
from src.logging_config import get_logger, setup_logging
from src.monitoring.telemetry import metrics as _metrics, broadcaster as _broadcaster
from src.models import TaskDomain, TaskSubmitRequest, TaskSubmitResponse
from src.runtime import AIOSRuntime

logger = get_logger("gateway")
_runtime: Optional[AIOSRuntime] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle manager."""
    global _runtime
    cfg = get_config()
    setup_logging(level=cfg.log_level)
    _runtime = AIOSRuntime(config=cfg)
    await _runtime.start()
    import asyncio
    asyncio.create_task(_broadcaster.start())
    logger.info("AIOS Gateway ready")
    yield
    _broadcaster.stop()
    await _runtime.stop()
    logger.info("AIOS Gateway stopped")


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(
        title="AIOS — Agentic AI Operating System",
        description="Multi-agent orchestration runtime with OS-inspired scheduling.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.gateway.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- Routes ----------

    @app.get("/v1/health", tags=["system"])
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/v1/metrics", tags=["monitoring"], response_class=PlainTextResponse)
    async def prometheus_metrics():
        """Prometheus-format metrics export."""
        return _metrics.prometheus_text()

    @app.websocket("/ws/monitor")
    async def websocket_dashboard(websocket: WebSocket):
        """Real-time metrics dashboard via WebSocket."""
        await websocket.accept()
        _broadcaster.add_client(websocket)
        try:
            while True:
                # Keep connection alive; broadcaster pushes data
                await websocket.receive_text()
        except WebSocketDisconnect:
            _broadcaster.remove_client(websocket)

    @app.post("/v1/tasks", response_model=TaskSubmitResponse, tags=["tasks"],
              status_code=status.HTTP_202_ACCEPTED)
    async def submit_task(req: TaskSubmitRequest):
        """Submit a new multi-agent workflow objective."""
        if _runtime is None:
            raise HTTPException(503, "Runtime not initialised")
        try:
            workflow_id = await _runtime.submit(
                objective=req.objective,
                domain=req.domain,
                timeout_seconds=req.timeout_seconds,
            )
            return TaskSubmitResponse(
                task_id=workflow_id,
                workflow_id=workflow_id,
                status="accepted",
                message="Workflow submitted successfully",
            )
        except Exception as exc:
            logger.error(f"submit_task error: {exc}")
            raise HTTPException(500, str(exc))

    @app.get("/v1/tasks/{workflow_id}", tags=["tasks"])
    async def get_task_status(workflow_id: str):
        """Poll the execution status of a workflow."""
        if _runtime is None:
            raise HTTPException(503, "Runtime not initialised")
        status_resp = _runtime.get_status(workflow_id)
        if status_resp is None:
            raise HTTPException(404, f"Workflow {workflow_id!r} not found")
        return status_resp

    @app.get("/v1/tasks/{workflow_id}/result", tags=["tasks"])
    async def get_task_result(workflow_id: str):
        """Retrieve the final aggregated result of a completed workflow."""
        if _runtime is None:
            raise HTTPException(503, "Runtime not initialised")
        if not _runtime.scheduler.is_workflow_complete(workflow_id):
            raise HTTPException(
                status.HTTP_202_ACCEPTED,
                "Workflow still running — poll /v1/tasks/{id} for status",
            )
        try:
            result = await _runtime.get_result(workflow_id)
            return result
        except KeyError:
            raise HTTPException(404, f"Workflow {workflow_id!r} not found")
        except Exception as exc:
            logger.error(f"get_result error: {exc}")
            raise HTTPException(500, str(exc))

    @app.delete("/v1/tasks/{workflow_id}", tags=["tasks"], status_code=204)
    async def cancel_task(workflow_id: str):
        """Cancel a running workflow (best-effort)."""
        # In this implementation, cancellation marks all non-completed tasks as failed
        if _runtime is None:
            raise HTTPException(503, "Runtime not initialised")
        records = _runtime.scheduler.get_all_task_records(workflow_id)
        if not records:
            raise HTTPException(404, f"Workflow {workflow_id!r} not found")
        from src.models import TaskState
        for task_id, record in records.items():
            if record.state in (TaskState.PENDING, TaskState.READY, TaskState.RUNNING):
                await _runtime.scheduler.on_task_failed(
                    workflow_id, task_id, "Cancelled by user"
                )
        return None

    @app.get("/v1/memory/stats", tags=["memory"])
    async def memory_stats():
        """Return memory subsystem statistics."""
        if _runtime is None:
            raise HTTPException(503, "Runtime not initialised")
        return await _runtime.memory.get_stats()

    @app.post("/v1/memory/consolidate", tags=["memory"])
    async def trigger_consolidation():
        """Manually trigger memory consolidation."""
        if _runtime is None:
            raise HTTPException(503, "Runtime not initialised")
        stats = await _runtime.memory.consolidate()
        return {"status": "ok", "consolidation_stats": stats}

    # ---------- Error handlers ----------

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error on {request.url}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": str(exc)},
        )

    return app

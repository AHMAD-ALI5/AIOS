"""
AIOS Monitoring
OpenTelemetry-compatible metrics and WebSocket dashboard support.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Optional, Set

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.models import SystemMetrics

logger = get_logger("monitoring")


class MetricsCollector:
    """
    Collects and exposes AIOS system metrics.
    Compatible with Prometheus scraping and OpenTelemetry export.
    """

    def __init__(self, config: Optional[AIOSConfig] = None) -> None:
        self.config = config or get_config()
        self._counters: dict[str, float] = {
            "tasks_submitted_total": 0,
            "tasks_completed_total": 0,
            "tasks_failed_total": 0,
            "llm_api_calls_total": 0,
            "memory_hits_total": 0,
            "memory_misses_total": 0,
        }
        self._gauges: dict[str, float] = {
            "active_workflows": 0,
            "queued_tasks": 0,
            "running_tasks": 0,
            "stm_entries": 0,
            "ltm_entries": 0,
            "memory_hit_rate": 0.0,
        }
        self._histograms: dict[str, list[float]] = {
            "task_execution_duration_seconds": [],
            "llm_api_latency_ms": [],
            "scheduler_dispatch_latency_ms": [],
        }
        self._start_time = time.time()

    def increment(self, counter: str, value: float = 1.0) -> None:
        if counter in self._counters:
            self._counters[counter] += value

    def set_gauge(self, gauge: str, value: float) -> None:
        self._gauges[gauge] = value

    def record_histogram(self, name: str, value: float) -> None:
        if name in self._histograms:
            self._histograms[name].append(value)
            # Keep last 1000 samples
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]

    def snapshot(self) -> SystemMetrics:
        """Return current metrics snapshot."""
        latencies = self._histograms["task_execution_duration_seconds"]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        uptime_hours = (time.time() - self._start_time) / 3600
        total_completed = self._counters["tasks_completed_total"]
        throughput = total_completed / uptime_hours if uptime_hours > 0 else 0.0

        return SystemMetrics(
            timestamp=datetime.utcnow(),
            active_workflows=int(self._gauges.get("active_workflows", 0)),
            queued_tasks=int(self._gauges.get("queued_tasks", 0)),
            running_tasks=int(self._gauges.get("running_tasks", 0)),
            completed_tasks_total=int(self._counters["tasks_completed_total"]),
            failed_tasks_total=int(self._counters["tasks_failed_total"]),
            stm_entries=int(self._gauges.get("stm_entries", 0)),
            ltm_entries=int(self._gauges.get("ltm_entries", 0)),
            memory_hit_rate=round(self._gauges.get("memory_hit_rate", 0.0), 3),
            avg_task_latency_seconds=round(avg_latency, 2),
            throughput_tasks_per_hour=round(throughput, 1),
        )

    def prometheus_text(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        for name, value in self._counters.items():
            lines.append(f"# TYPE aios_{name} counter")
            lines.append(f"aios_{name} {value}")
        for name, value in self._gauges.items():
            lines.append(f"# TYPE aios_{name} gauge")
            lines.append(f"aios_{name} {value}")
        for name, samples in self._histograms.items():
            if samples:
                avg = sum(samples) / len(samples)
                lines.append(f"# TYPE aios_{name} histogram")
                lines.append(f"aios_{name}_count {len(samples)}")
                lines.append(f"aios_{name}_sum {sum(samples):.3f}")
                lines.append(f"aios_{name}_avg {avg:.3f}")
        return "\n".join(lines)


# Global metrics instance
metrics = MetricsCollector()


class DashboardBroadcaster:
    """
    Broadcasts real-time metrics to WebSocket dashboard clients.
    """

    def __init__(self, interval_seconds: int = 5) -> None:
        self._clients: Set = set()
        self._interval = interval_seconds
        self._running = False

    def add_client(self, websocket) -> None:
        self._clients.add(websocket)
        logger.debug(f"Dashboard client connected ({len(self._clients)} total)")

    def remove_client(self, websocket) -> None:
        self._clients.discard(websocket)
        logger.debug(f"Dashboard client disconnected ({len(self._clients)} total)")

    async def start(self) -> None:
        self._running = True
        while self._running:
            if self._clients:
                snapshot = metrics.snapshot()
                payload = json.dumps(snapshot.model_dump(), default=str)
                dead = set()
                for ws in self._clients:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.add(ws)
                self._clients -= dead
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        self._running = False


broadcaster = DashboardBroadcaster()

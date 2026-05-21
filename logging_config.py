"""
AIOS Logging Configuration
Structured JSON logging with configurable levels and optional file output.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional
import json
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production use."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra fields attached to the record
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                try:
                    json.dumps(value)  # Only include JSON-serializable extras
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)
        return json.dumps(log_entry)


def setup_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure AIOS logging.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, use structured JSON formatting (recommended for production)
        log_file: Optional file path to write logs to
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_output:
        console_handler.setFormatter(JSONFormatter())
    else:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
        console_handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    root_logger.addHandler(console_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())  # Always JSON in files
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "openai", "anthropic", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with AIOS prefix."""
    return logging.getLogger(f"aios.{name}")

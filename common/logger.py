"""Structured JSON logger with contextual metadata support."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """Formats log records into structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "message": record.getMessage(),
        }

        # Add trace / task context if present
        for attr in ("task_id", "node_id", "sla_class", "decision_latency_ms", "event_id", "error_code"):
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def get_logger(name: str, component: str | None = None) -> logging.Logger:
    """Obtain or configure a structured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

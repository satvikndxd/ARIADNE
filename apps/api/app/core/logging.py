"""Structured JSON logging.

Every record carries: timestamp, service, level, event, request_id, analysis_id,
user_id and (where known) latency_ms.  Stack traces stay in the developer log —
they are never returned to the client (see ``core/errors.py``).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
analysis_id_var: ContextVar[str] = ContextVar("analysis_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "service": settings.service_name,
            "severity": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
            "request_id": request_id_var.get(),
            "analysis_id": analysis_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class StructuredLogger(logging.Logger):
    """Logger accepting ``log.info("event", key=value, ...)`` structured fields."""

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False, stacklevel=1, **fields):
        merged = dict(extra or {})
        merged.update(fields)
        super()._log(level, msg, args, exc_info=exc_info, extra=merged, stack_info=stack_info,
                     stacklevel=stacklevel + 1)


logging.setLoggerClass(StructuredLogger)


class PlainFormatter(logging.Formatter):
    """Human-readable formatter used for local scripts."""

    def format(self, record: logging.LogRecord) -> str:
        extra = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")}
        tail = (" " + " ".join(f"{k}={v}" for k, v in extra.items())) if extra else ""
        out = f"{record.levelname:<7} {record.name:<26} {record.getMessage()}{tail}"
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        return out


def configure_logging(json_output: bool = True, level: str | None = None) -> None:
    root = logging.getLogger()
    root.setLevel((level or settings.log_level).upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    root.addHandler(handler)
    for noisy in ("uvicorn.access", "httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    return logging.getLogger(name)  # type: ignore[return-value]


class Timer:
    """Context manager measuring latency in milliseconds for structured logs."""

    def __init__(self) -> None:
        self.ms: float = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = round((time.perf_counter() - self._t0) * 1000, 2)

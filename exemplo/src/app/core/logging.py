"""Logging estruturado em JSON para CloudWatch/Datadog."""
from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


_SERVICE = os.environ.get("DD_SERVICE", "faturamento-bff")
_ENV = os.environ.get("DD_ENV", os.environ.get("STAGE","dev"))
_VERSION = os.environ.get("DD_VERSION", "unknown")
_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").upper()
_LEVEL = getattr(logging, _LEVEL_NAME, logging.INFO)
# Tamanho maximo da mensagem antes de truncar (CloudWatch/DD tem limites por evento)
_MAX_MESSAGE_LEN = int(os.environ.get("LOG_MAX_MESSAGE_LEN", "10000"))

# Campos que o contexto/evento NAO pode sobrescrever
_RESERVED = {
    "timestamp",
    "status",
    "logger",
    "service",
    "env",
    "version",
    "dd.trace_id",
    "dd.span_id",
}

_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default=None)

# --- ddtrace resolvido UMA vez (sem custo de import/except por log) ----------
try:
    from ddtrace import tracer as _tracer  # type: ignore
except Exception:  # ddtrace ausente em runtime
    _tracer = None


# --- Contexto por request -----------------------------------------------------
def bind_context(**fields: Any) -> None:
    """Adiciona campos ao contexto do request atual (ignora None)."""
    current = _context.get() or {}
    _context.set({**current, **{k: v for k, v in fields.items() if v is not None}})


def clear_context() -> None:
    """Limpa o contexto. Deve ser chamado ao fim de cada request/invocacao."""
    _context.set(None)


def _dd_trace_ids() -> dict[str, str]:
    if _tracer is None:
        return {}
    try:
        span = _tracer.current_span()
        if not span:
            return {}
        return {"dd.trace_id": str(span.trace_id), "dd.span_id": str(span.span_id)}
    except Exception:
        return {}


def _safe_update(payload: dict[str, Any], extra: dict[str, Any] | None) -> None:
    """Aplica extra sem sobrescrever campos reservados e sem incluir None."""
    if extra is None:
        return
    for k, v in extra.items():
        if v is None:
            continue
        if k in _RESERVED:
            continue
        payload[k] = v


# --- Formatter -------------------------------------------------------------------------------
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if len(message) > _MAX_MESSAGE_LEN:
            message = message[:_MAX_MESSAGE_LEN] + "...[truncated]"

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "status": record.levelname.lower(),
            "logger": record.name,
            "message": message,
            "service": _SERVICE,
            "env": _ENV,
            "version": _VERSION,
        }

        # Correlacao / contexto (sem quebrar campos reservados)
        _safe_update(payload, _context.get() or {})
        payload.update(_dd_trace_ids())  # trace ids sempre confiaveis

        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            _safe_update(payload, ctx)

        if record.exc_info:
            payload["error"] = {
                "kind": getattr(record.exc_info[0], "__name__", "Error"),
                "stack": self.formatException(record.exc_info),
            }

        return json.dumps(payload, ensure_ascii=False, default=str)


# --- Setup -------------------------------------------------------------------------------------
def setup_logging() -> None:
    """Configura o root logger. Idempotente (seguro em cold start de Lambda)."""
    root = logging.getLogger()
    root.setLevel(_LEVEL)

    # Ja configurado por este modulo?
    if any(getattr(h, "_faturamento_json", False) for h in root.handlers):
        return

    # Remove handlers pre-existentes (a Lambda injeta um handler proprio)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()  # stdout -> CloudWatch -> Datadog
    handler.setFormatter(_JsonFormatter())
    handler._faturamento_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # Reduz ruido de libs comuns em BFF
    for noisy in ("uvicorn.access", "botocore", "boto3", "urllib3", "aiobotocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: str,
    level: str = "info",
    **fields: Any,
) -> None:
    """Emite um evento nomeado com contexto adicional.

    Ex.: log_event(log, "invoice.created", invoice_id="123", amount=99.9)
    """
    logger.log(
        getattr(logging, level.upper(), logging.INFO),
        event,
        extra={"ctx": {"event": event, **fields}},
    )

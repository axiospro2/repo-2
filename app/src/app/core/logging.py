"""Logging estruturado (JSON) pronto para o Datadog.

Por que JSON: o Datadog parseia logs JSON automaticamente — cada chave vira um atributo
pesquisável/facetável, sem grok parsing. Não configuramos nada na infra; basta o log sair
em JSON no stdout que a integração do Datadog (Lambda extension/forwarder) coleta.

Convenção de uso (NÃO logar "estou aqui" — só eventos com contexto):
  - Evento de NEGÓCIO:  log_event(logger, "faturamento.persistido", conglomerado_doc=..., qtd=...)
  - Evento TÉCNICO:     log_event(logger, "parametros.fetch", level="debug", latency_ms=..., cache_hit=...)
  - Erro:               logger.exception("faturamento.erro", extra={"ctx": {...}})

Correlação: `bind_context(request_id=...)` deixa todo log subsequente da invocação carregar
o request_id (via contextvars). Se o ddtrace estiver presente em runtime, injeta dd.trace_id/span_id.
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Atributos padrão do Datadog: "status" (nivel), "service", "message", "timestamp".
_SERVICE = os.environ.get("DD_SERVICE", "faturamento-save")
_ENV = os.environ.get("DD_ENV", os.environ.get("STAGE", "dev"))
_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Contexto da invocação (request_id e o que mais for vinculado), propagado sem passar à mão.
_context: ContextVar[dict] = ContextVar("log_context", default={})

_bff_correlation_id: ContextVar[str | None] = ContextVar("bff_correlation_id", default=None)


def bind_context(**fields: Any) -> None:
    """Adiciona campos ao contexto desta invocação (todos os logs seguintes os carregam)."""
    _context.set({**_context.get(), **{k: v for k, v in fields.items() if v is not None}})


def set_bff_correlation_id(correlation_id: str | None) -> None:
    """Define o correlation ID vindo do BFF (x-itau-correlationid header)."""
    _bff_correlation_id.set(correlation_id)


def get_bff_correlation_id() -> str | None:
    """Obtém o correlation ID do BFF, se houver sido definido."""
    return _bff_correlation_id.get()


def clear_context() -> None:
    _context.set({})
    _bff_correlation_id.set(None)


def _dd_trace_ids() -> dict:
    """Se o ddtrace estiver disponível, correlaciona log<->trace no Datadog. Opcional."""
    try:
        from ddtrace import tracer  # type: ignore

        span = tracer.current_span()
        if span:
            return {"dd.trace_id": str(span.trace_id), "dd.span_id": str(span.span_id)}
    except Exception:
        pass
    return {}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "status": record.levelname.lower(),  # Datadog usa "status"
            "logger": record.name,
            "message": record.getMessage(),
            "service": _SERVICE,
            "env": _ENV,
        }
        payload.update(_context.get())
        payload.update(_dd_trace_ids())
        # Campos extras passados via extra={"ctx": {...}}.
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            payload.update(ctx)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """Configura o root logger uma vez (idempotente entre invocações da Lambda quente)."""
    root = logging.getLogger()
    root.setLevel(_LEVEL)
    if any(getattr(h, "_faturamento_json", False) for h in root.handlers):
        return
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    handler._faturamento_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, level: str = "info", **fields: Any) -> None:
    """Loga um evento nomeado com contexto. `event` é o nome do evento (negócio ou técnico).

    Sai cedo se o nível estiver desabilitado (ex.: `debug` com `LOG_LEVEL=INFO`) — evita
    montar o dict/serializar argumentos à toa em toda chamada do hot path.
    """
    levelno = getattr(logging, level.upper(), logging.INFO)
    if not logger.isEnabledFor(levelno):
        return
    logger.log(levelno, event, extra={"ctx": {"event": event, **fields}})

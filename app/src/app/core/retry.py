"""Política de retry (tenacity) para chamadas a integrações externas (serviço de parâmetros).

Retry só em falhas transitórias (rede/timeout/5xx). Backoff exponencial com jitter.
Cada tentativa loga um evento técnico (`integracao.retry`) — visível no Datadog.
"""

from __future__ import annotations

import logging
import urllib.error

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

from app.core.logging import get_logger
from app.core.settings import settings

_logger = get_logger("integracao.retry")

# Erros considerados transitórios (vale retry).
_TRANSIENTES = (urllib.error.URLError, TimeoutError, ConnectionError)


def http_retry(func):
    """Decorator: aplica retry com backoff às chamadas HTTP de integração."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.parametros_retries),
        wait=wait_exponential_jitter(initial=0.1, max=2.0),
        retry=retry_if_exception_type(_TRANSIENTES),
        before_sleep=before_sleep_log(_logger, logging.WARNING),
    )(func)

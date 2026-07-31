"""Política de retry (tenacity) para chamadas a integrações externas (serviço de parâmetros).

Retry só em falhas transitórias (rede/timeout/5xx). Backoff exponencial com jitter.
Cada tentativa loga um evento técnico (`integracao.retry`) — visível no Datadog.
"""

from __future__ import annotations

import logging

import urllib3.exceptions
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.logging import get_logger
from app.core.settings import settings

_logger = get_logger("integracao.retry")


class ErroServidorIntegracao(Exception):
    """Levantada pelos adapters quando a integração responde 5xx — transitório, vale retry.

    4xx (exceto quando o adapter já trata, ex. 404) NÃO cai aqui de propósito: erro do
    cliente não se resolve tentando de novo, só adiciona latência à resposta de erro.
    """


# Erros considerados transitórios (vale retry): falha de rede/timeout (urllib3) ou 5xx.
_TRANSIENTES = (urllib3.exceptions.HTTPError, ErroServidorIntegracao, TimeoutError, ConnectionError)


def http_retry(func):
    """Decorator: aplica retry com backoff às chamadas HTTP de integração."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.parametros_retries),
        wait=wait_exponential_jitter(initial=0.1, max=2.0),
        retry=retry_if_exception_type(_TRANSIENTES),
        before_sleep=before_sleep_log(_logger, logging.WARNING),
    )(func)

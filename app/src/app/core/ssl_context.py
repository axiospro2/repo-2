"""Contexto SSL customizado para as chamadas HTTP de integração (NJ6, Endpoint).

Extraído de `adapters/nj6.py`/`adapters/endpoint.py`, onde a mesma função existia
duplicada verbatim nos dois módulos. Independente do contexto SSL da autenticação
OAuth2 (`core/oauth2.py::_get_ssl_context`), que resolve a CA bundle por caminhos
fixos de Lambda Layer — este aqui lê `SSL_CERT_FILE`/`SSL_CERT_DIR` do ambiente.
"""

from __future__ import annotations

import os
import ssl

from app.core.logging import get_logger, log_event

_logger = get_logger("faturamento.ssl")


def criar_contexto_ssl() -> ssl.SSLContext | None:
    """Cria um contexto SSL que valida certificados com a CA bundle fornecida.

    Retorna `None` (sem contexto customizado) se nem `SSL_CERT_FILE` nem
    `SSL_CERT_DIR` estiverem configurados.
    """
    cert_file = os.environ.get("SSL_CERT_FILE", "").strip()
    cert_dir = os.environ.get("SSL_CERT_DIR", "").strip()

    if not cert_file and not cert_dir:
        return None

    try:
        context = ssl.create_default_context()

        if cert_file and os.path.isfile(cert_file):
            context.load_verify_locations(cafile=cert_file)
            log_event(_logger, "ssl.certificado_carregado", level="debug", arquivo=cert_file)

        if cert_dir and os.path.isdir(cert_dir):
            context.load_verify_locations(capath=cert_dir)
            log_event(_logger, "ssl.diretorio_carregado", level="debug", diretorio=cert_dir)

        return context
    except Exception as e:
        log_event(
            _logger,
            "ssl.erro_contexto",
            level="warning",
            erro=str(e),
            cert_file=cert_file,
            cert_dir=cert_dir,
        )
        return None

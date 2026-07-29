"""Endpoint de Faturamento — Integração HTTP real com Gestão Balanço.

O Endpoint real (gestaobalanco) devolve os spreads de faturamento.
A eleição do **melhor balanço** (R1/R2/R3) é regra NOSSA e mora em `domain/eleicao.py` —
aqui o adapter só carrega os dados e chama `eleger`.

Retorna `None` quando não há balanço elegível (→ input MANUAL na tela).
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
import uuid
from datetime import date
from typing import Optional

from app.adapters.auth import TokenProvider, build_token_provider
from app.core.logging import get_logger, log_event
from app.core.retry import http_retry
from app.domain.eleicao import ResultadoFaturamento, eleger  # re-exportado p/ compat de imports

_logger = get_logger("faturamento.endpoint")

__all__ = ["ResultadoFaturamento", "HttpEndpoint"]

def _criar_contexto_ssl() -> ssl.SSLContext | None:
    """Cria um contexto SSL que valida certificados com a CA bundle fornecida."""
    cert_file = os.environ.get("SSL_CERT_FILE", "").strip()
    cert_dir = os.environ.get("SSL_CERT_DIR", "").strip()

    if not cert_file and not cert_dir:
        return None

    try:
        context = ssl.create_default_context()

        if cert_file and os.path.isfile(cert_file):
            context.load_verify_locations(cafile=cert_file)
            log_event(_logger, "ssl.certificado_carregado", level="debug",
                      arquivo=cert_file)

        if cert_dir and os.path.isdir(cert_dir):
            context.load_verify_locations(capath=cert_dir)
            log_event(_logger, "ssl.diretorio_carregado", level="debug",
                      diretorio=cert_dir)

        return context
    except Exception as e:
        log_event(_logger, "ssl.erro_contexto", level="warning",
                  erro=str(e), cert_file=cert_file, cert_dir=cert_dir)
        return None


class HttpEndpoint:
    """Integração real com Gestão Balanço (spreads de faturamento) via HTTP.

    Chama: GET {base_url}/gestaobalanco/v1/spreads-faturamento?subgrupo={documento}

    A eleição R1/R2/R3 continua nossa. É fallback: em falha, devolve None
    (o marcador fica MANUAL, não derruba a leitura).
    """

    def __init__(self, base_url: str, timeout: float = 5.0, token: TokenProvider | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or build_token_provider()

    def buscar(self, documento_raiz: str, asof: Optional[str] = None) -> Optional[ResultadoFaturamento]:
        try:
            spreads = self._buscar_spreads(documento_raiz)
            ref = date.fromisoformat(asof) if asof else date.today()
            return eleger(spreads, ref)
        except Exception as e:  # fallback: não derruba a leitura
            log_event(_logger, "endpoint.indisponivel", level="error", erro=str(e), tipo_erro=type(e).__name__)
            return None

    @http_retry
    def _buscar_spreads(self, documento_raiz: str) -> list[dict]:
        """Busca spreads de faturamento para um subgrupo/documento.

        Com retry automático em caso de timeout/erro transitório.
        """
        # Gerar correlation-id único (UUID)
        correlation_id = str(uuid.uuid4())

        # Montar headers
        headers = self._token.auth_headers()  # Authorization: Bearer <JWT>
        headers["x-itau-apikey"] = os.environ.get("ITAU_API_KEY", "")
        headers["x-itau-correlationid"] = correlation_id
        headers["Content-Type"] = "application/json"

        # Montar URL
        url = f"{self.base_url}/gestaobalanco/v1/spreads-faturamento?subgrupo={urllib.parse.quote(documento_raiz)}"

        # Log da requisição
        log_event(
            _logger, "endpoint.requisicao",
            level="info",
            url=url,
            documento=documento_raiz,
            correlation_id=correlation_id,
        )

        try:
            # Fazer requisição
            req = urllib.request.Request(url, method="GET", headers=headers)

            # Usar contexto SSL se estiver configurado
            ssl_context = _criar_contexto_ssl()

            if ssl_context:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context) as response:
                    data = json.loads(response.read().decode("utf-8"))
            else:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))

            # Log de sucesso
            log_event(
                _logger, "endpoint.sucesso",
                level="info",
                documento=documento_raiz,
                correlation_id=correlation_id,
                status_code=response.status,
            )

            # Extrair spreads da resposta (pode estar em "data" ou direto)
            spreads = data.get("data") or data.get("spreads") or data if isinstance(data, list) else []
            return spreads if isinstance(spreads, list) else [data]

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log_event(
                    _logger, "endpoint.nao_encontrado",
                    level="info",
                    documento=documento_raiz,
                    correlation_id=correlation_id,
                    status_code=e.code,
                )
                return []
            else:
                log_event(
                    _logger, "endpoint.erro_http",
                    level="error",
                    documento=documento_raiz,
                    correlation_id=correlation_id,
                    status_code=e.code,
                    erro=str(e),
                )
                raise
        except urllib.error.URLError as e:
            # Erro transitório - será retentado pelo @http_retry
            log_event(
                _logger, "endpoint.erro_rede",
                level="warning",
                documento=documento_raiz,
                correlation_id=correlation_id,
                erro=str(e),
                tentando_novamente=True,
            )
            raise
        except Exception as e:
            log_event(
                _logger, "endpoint.erro",
                level="error",
                documento=documento_raiz,
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise

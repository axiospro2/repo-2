"""NJ6 — resolve conglomerado → subgrupos → integrantes por documento (CPF/CNPJ/CGI).

Integração HTTP com o serviço NJ6 do Itaú para resolver grupos econômicos.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
import uuid

from app.adapters.auth import TokenProvider, build_token_provider
from app.core.logging import get_logger, log_event
from app.core.retry import http_retry
from app.core.settings import settings
from app.domain.errors import NaoEncontrado
from app.domain.models import Conglomerado, Pessoa, Subgrupo

_logger = get_logger("faturamento.nj6")

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


def _map_conglomerado(raw: dict) -> Conglomerado:
    """Mapeia resposta do NJ6 (real ou mock) para modelo de domínio.

    A resposta real do NJ6 vem envolvida em {"data": [...]}, enquanto
    as fixtures vêm direto com a estrutura. Esse método normaliza ambas.
    """
    try:
        log_event(_logger, "nj6.map_conglomerado.inicio", level="debug", raw_keys=list(raw.keys()) if isinstance(raw, dict) else "não-dict")

        # Normalizar: se veio envolvida em "data", desembrulhar
        if "data" in raw and isinstance(raw["data"], list) and raw["data"]:
            raw = raw["data"][0]
            log_event(_logger, "nj6.map_conglomerado.desembrulhado", level="debug")

        subgrupos = []
        for i, s in enumerate(raw.get("subgrupos", [])):
            try:
                participantes = [
                    Pessoa(
                        codigo_identificacao_pessoa=p["pessoa"]["codigo_identificacao_pessoa"],
                        documento_raiz=p["pessoa"]["documento_raiz"],
                        codigo_tipo_pessoa=p["pessoa"].get("codigo_tipo_pessoa", "J"),
                        indicador_estrangeiro=p["pessoa"].get("indicador_estrangeiro", 0),
                    )
                    for p in s.get("participantes", [])
                ]
                subgrupos.append(
                    Subgrupo(
                        nome_subgrupo=s["nome_subgrupo"],
                        cabeca_documento_raiz=s["cabeca_subgrupo"]["documento_raiz"],
                        codigo_grupo_cliente_atacado=s.get("codigo_grupo_cliente_atacado"),
                        participantes=participantes,
                    )
                )
                log_event(_logger, "nj6.map_conglomerado.subgrupo_ok", level="debug",
                          idx=i, nome=s.get("nome_subgrupo"), qtd_participantes=len(participantes))
            except Exception as e:
                _logger.exception("nj6.map_conglomerado.erro_subgrupo",
                                   extra={"ctx": {
                                       "event": "nj6.map_conglomerado.erro_subgrupo",
                                       "idx": i,
                                       "tipo_erro": type(e).__name__,
                                       "mensagem": str(e)
                                   }})
                raise

        result = Conglomerado(
            nome_grupo_economico=raw["nome_grupo_economico"],
            cabeca_documento_raiz=raw["cabeca_grupo"]["documento_raiz"],
            segmento=raw.get("segmento"),
            subgrupos=subgrupos,
        )
        log_event(_logger, "nj6.map_conglomerado.sucesso", level="debug",
                  nome_grupo=result.nome_grupo_economico, qtd_subgrupos=len(subgrupos))
        return result
    except Exception as e:
        _logger.exception("nj6.map_conglomerado.erro_fatal",
                           extra={"ctx": {
                               "event": "nj6.map_conglomerado.erro_fatal",
                               "tipo_erro": type(e).__name__,
                               "mensagem": str(e),
                               "raw_type": type(raw).__name__
                           }})
        raise


class HttpNJ6:
    """Integração real com NJ6 do Itaú — auth JWT + headers customizados."""

    def __init__(self, base_url: str, timeout: float = 5.0, token: TokenProvider | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or build_token_provider()

    @http_retry
    def get_por_documento(self, documento: str) -> Conglomerado:
        """
        GET {base_url}/consulta-gruposeconomicos/v1/grupos-economicos?codigo_identificacao_pessoa={documento}

        Headers:
          - Authorization: Bearer <JWT>
          - x-itau-apikey: <API_KEY>
          - x-itau-correlationid: <UUID>

        Com retry automático em caso de timeout/erro transitório.
        """
        # Gerar correlation-id único (UUID)
        correlation_id = str(uuid.uuid4())

        # Montar headers
        headers = self._token.auth_headers()  # Authorization: Bearer <JWT>
        headers["x-itau-apikey"] = os.environ.get("ITAU_API_KEY", "")
        headers["x-itau-correlationid"] = correlation_id
        headers["Content-Type"] = "application/json"

        # Montar URL com parametro
        url = f"{self.base_url}/consulta-gruposeconomicos/v1/grupos-economicos?codigo_identificacao_pessoa={urllib.parse.quote(documento)}"  # (line continues past right edge)

        # Log da requisição
        log_event(
            _logger, "nj6.requisicao",
            level="info",
            url=url,
            documento=documento,
            correlation_id=correlation_id,
            timeout_s=self.timeout,
        )

        try:
            # Fazer requisição com timeout configurado
            log_event(_logger, "nj6.http_request.inicio", level="debug",
                      documento=documento, correlation_id=correlation_id)
            req = urllib.request.Request(url, method="GET", headers=headers)

            # Usar contexto SSL se estiver configurado
            ssl_context = _criar_contexto_ssl()

            if ssl_context:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context) as response:
                    raw_response = response.read().decode("utf-8")
                    log_event(_logger, "nj6.http_request.response_recebida", level="debug",
                              status_code=response.status, tamanho_bytes=len(raw_response))
                    data = json.loads(raw_response)
            else:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    raw_response = response.read().decode("utf-8")
                    log_event(_logger, "nj6.http_request.response_recebida", level="debug",
                              status_code=response.status, tamanho_bytes=len(raw_response))
                    data = json.loads(raw_response)

            log_event(_logger, "nj6.http_request.resposta_parseada", level="debug",
                      status_code=response.status, tipo=type(data).__name__)

            # Log de sucesso
            log_event(
                _logger, "nj6.sucesso",
                level="info",
                documento=documento,
                correlation_id=correlation_id,
                status_code=response.status,
            )

            # Mapear resposta
            conglomerado = _map_conglomerado(data)
            return conglomerado

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log_event(
                    _logger, "nj6.nao_encontrado",
                    level="info",
                    documento=documento,
                    correlation_id=correlation_id,
                    status_code=e.code,
                )
                raise NaoEncontrado(f"Nenhum conglomerado encontrado para o documento {documento}.")
            else:
                log_event(
                    _logger, "nj6.erro_http",
                    level="error",
                    documento=documento,
                    correlation_id=correlation_id,
                    status_code=e.code,
                    erro=str(e),
                )
                raise
        except urllib.error.URLError as e:
            # Erro transitório - será retentado pelo @http_retry
            log_event(
                _logger, "nj6.erro_rede",
                level="warning",
                documento=documento,
                correlation_id=correlation_id,
                erro=str(e),
                tentando_novamente=True,
            )
            raise
        except json.JSONDecodeError as e:
            log_event(
                _logger, "nj6.erro_json",
                level="error",
                documento=documento,
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise
        except Exception as e:
            log_event(
                _logger, "nj6.erro",
                level="error",
                documento=documento,
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise

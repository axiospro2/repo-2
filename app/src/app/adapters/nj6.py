"""NJ6 — resolve conglomerado → subgrupos → integrantes por documento (CPF/CNPJ/CGI).

Integração HTTP com o serviço NJ6 do Itaú para resolver grupos econômicos.
"""

from __future__ import annotations

import json
import urllib.parse
import uuid

import urllib3

from app.adapters.auth import TokenProvider, build_token_provider
from app.core.http_client import get_pool
from app.core.logging import get_logger, log_event
from app.core.mascaramento import mascarar_documento
from app.core.retry import ErroServidorIntegracao, http_retry
from app.core.settings import settings
from app.core.ssl_context import criar_contexto_ssl
from app.domain.errors import NaoEncontrado
from app.domain.models import Conglomerado, Pessoa, Subgrupo

_logger = get_logger("faturamento.nj6")


def _map_conglomerado(raw: dict) -> Conglomerado:
    """Mapeia resposta do NJ6 (real ou mock) para modelo de domínio.

    A resposta real do NJ6 vem envolvida em {"data": [...]}, enquanto
    as fixtures vêm direto com a estrutura. Esse método normaliza ambas.
    """
    try:
        # Normalizar: se veio envolvida em "data", desembrulhar
        if "data" in raw and isinstance(raw["data"], list) and raw["data"]:
            raw = raw["data"][0]

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
            except Exception as e:
                _logger.exception(
                    "nj6.map_conglomerado.erro_subgrupo",
                    extra={
                        "ctx": {
                            "event": "nj6.map_conglomerado.erro_subgrupo",
                            "idx": i,
                            "tipo_erro": type(e).__name__,
                            "mensagem": str(e),
                        }
                    },
                )
                raise

        result = Conglomerado(
            nome_grupo_economico=raw["nome_grupo_economico"],
            cabeca_documento_raiz=raw["cabeca_grupo"]["documento_raiz"],
            segmento=raw.get("segmento"),
            subgrupos=subgrupos,
        )
        log_event(
            _logger,
            "nj6.map_conglomerado.sucesso",
            level="debug",
            nome_grupo=result.nome_grupo_economico,
            qtd_subgrupos=len(subgrupos),
        )
        return result
    except Exception as e:
        _logger.exception(
            "nj6.map_conglomerado.erro_fatal",
            extra={
                "ctx": {
                    "event": "nj6.map_conglomerado.erro_fatal",
                    "tipo_erro": type(e).__name__,
                    "mensagem": str(e),
                    "raw_type": type(raw).__name__,
                }
            },
        )
        raise


def _map_grupos_lista(raw: dict) -> list[Conglomerado]:
    """Mapeia a resposta da busca "like" do NJ6 (`buscar_grupos`) — `data[]` pode trazer
    VÁRIOS grupos econômicos misturados com itens soltos de pessoa física sem grupo
    (`{"pessoa": {...}}`, sem `cabeca_grupo`); esses últimos são ignorados aqui porque a
    busca do front só lista conglomerado/subgrupo (documento raiz), não participante avulso.

    Erro ao mapear 1 item não derruba os demais — só aquele item é descartado do resultado.
    """
    itens = raw.get("data") or []
    grupos: list[Conglomerado] = []
    for i, item in enumerate(itens):
        if "cabeca_grupo" not in item:
            continue
        try:
            grupos.append(_map_conglomerado(item))
        except Exception as e:
            _logger.exception(
                "nj6.map_grupos_lista.erro_item",
                extra={
                    "ctx": {
                        "event": "nj6.map_grupos_lista.erro_item",
                        "idx": i,
                        "tipo_erro": type(e).__name__,
                        "mensagem": str(e),
                    }
                },
            )
    return grupos


class HttpNJ6:
    """Integração real com NJ6 do Itaú — auth JWT + headers customizados."""

    def __init__(self, base_url: str, timeout: float = 5.0, token: TokenProvider | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or build_token_provider()

    def _requisitar_grupos_economicos(self, valor: str):
        """GET cru em consulta-gruposeconomicos — parte comum de `get_por_documento`
        (busca exata) e `buscar_grupos` (busca parcial/"like"); só o tratamento do
        404 e do corpo difere entre as duas (documento não encontrado é erro numa,
        resultado vazio na outra), então fica em cada método chamador.

        Headers:
          - Authorization: Bearer <JWT>
          - x-itau-apikey: <API_KEY>
          - x-itau-correlationid: <UUID>
        """
        # Gerar correlation-id único (UUID)
        correlation_id = str(uuid.uuid4())

        # Montar headers
        headers = self._token.auth_headers()  # Authorization: Bearer <JWT>
        headers["x-itau-apikey"] = settings.itau_api_key
        headers["x-itau-correlationid"] = correlation_id
        headers["Content-Type"] = "application/json"

        # Montar URL com parametro
        url = f"{self.base_url}/consulta-gruposeconomicos/v1/grupos-economicos?codigo_identificacao_pessoa={urllib.parse.quote(valor)}"

        # Log técnico da requisição — sem a URL completa (contém o documento na querystring)
        log_event(
            _logger,
            "nj6.requisicao",
            level="debug",
            documento=mascarar_documento(valor),
            correlation_id=correlation_id,
        )

        pool = get_pool("integrations", criar_contexto_ssl())

        try:
            resp = pool.request(
                "GET",
                url,
                headers=headers,
                timeout=urllib3.Timeout(total=self.timeout),
            )
        except urllib3.exceptions.HTTPError as e:
            # Erro transitório - será retentado pelo @http_retry
            log_event(
                _logger,
                "nj6.erro_rede",
                level="warning",
                documento=mascarar_documento(valor),
                correlation_id=correlation_id,
                erro=str(e),
                tentando_novamente=True,
            )
            raise

        return resp, correlation_id

    @http_retry
    def get_por_documento(self, documento: str) -> Conglomerado:
        """
        GET {base_url}/consulta-gruposeconomicos/v1/grupos-economicos?codigo_identificacao_pessoa={documento}

        Busca exata por documento completo. Com retry automático em caso de
        timeout/erro transitório.
        """
        resp, correlation_id = self._requisitar_grupos_economicos(documento)

        if resp.status == 404:
            log_event(
                _logger,
                "nj6.nao_encontrado",
                level="info",
                documento=mascarar_documento(documento),
                correlation_id=correlation_id,
                status_code=resp.status,
            )
            raise NaoEncontrado(f"Nenhum conglomerado encontrado para o documento {documento}.")

        if resp.status >= 400:
            log_event(
                _logger,
                "nj6.erro_http",
                level="error",
                documento=mascarar_documento(documento),
                correlation_id=correlation_id,
                status_code=resp.status,
                erro=resp.data.decode("utf-8", errors="replace")[:500],
            )
            if resp.status >= 500:
                # 5xx é transitório - será retentado pelo @http_retry
                raise ErroServidorIntegracao(f"NJ6 retornou HTTP {resp.status}")
            raise RuntimeError(f"NJ6 retornou HTTP {resp.status}")

        try:
            data = json.loads(resp.data.decode("utf-8"))

            log_event(
                _logger,
                "nj6.sucesso",
                level="debug",
                documento=mascarar_documento(documento),
                correlation_id=correlation_id,
                status_code=resp.status,
            )

            return _map_conglomerado(data)

        except json.JSONDecodeError as e:
            log_event(
                _logger,
                "nj6.erro_json",
                level="error",
                documento=mascarar_documento(documento),
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise
        except Exception as e:
            log_event(
                _logger,
                "nj6.erro",
                level="error",
                documento=mascarar_documento(documento),
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise

    @http_retry
    def buscar_grupos(self, termo: str) -> list[Conglomerado]:
        """
        GET {base_url}/consulta-gruposeconomicos/v1/grupos-economicos?codigo_identificacao_pessoa={termo}

        Mesmo endpoint do `get_por_documento`, só que pra busca parcial ("like") usada no
        autocomplete do front: `termo` pode ser um CNPJ/CPF incompleto, e o NJ6 devolve
        TODOS os grupos econômicos cujo documento bate — em `data[]`, em vez de 1 só.

        Sem match não é erro aqui (resultado vazio é normal enquanto o usuário digita):
        404 e lista vazia viram `[]`, nunca `NaoEncontrado`.
        """
        resp, correlation_id = self._requisitar_grupos_economicos(termo)

        if resp.status == 404:
            log_event(
                _logger,
                "nj6.busca_grupos.sem_resultado",
                level="debug",
                documento=mascarar_documento(termo),
                correlation_id=correlation_id,
                status_code=resp.status,
            )
            return []

        if resp.status >= 400:
            log_event(
                _logger,
                "nj6.erro_http",
                level="error",
                documento=mascarar_documento(termo),
                correlation_id=correlation_id,
                status_code=resp.status,
                erro=resp.data.decode("utf-8", errors="replace")[:500],
            )
            if resp.status >= 500:
                # 5xx é transitório - será retentado pelo @http_retry
                raise ErroServidorIntegracao(f"NJ6 retornou HTTP {resp.status}")
            raise RuntimeError(f"NJ6 retornou HTTP {resp.status}")

        try:
            data = json.loads(resp.data.decode("utf-8"))

            log_event(
                _logger,
                "nj6.sucesso",
                level="debug",
                documento=mascarar_documento(termo),
                correlation_id=correlation_id,
                status_code=resp.status,
            )

            return _map_grupos_lista(data)

        except json.JSONDecodeError as e:
            log_event(
                _logger,
                "nj6.erro_json",
                level="error",
                documento=mascarar_documento(termo),
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise

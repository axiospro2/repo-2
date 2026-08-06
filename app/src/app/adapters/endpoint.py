"""Endpoint de Faturamento — Integração HTTP real com Gestão Balanço.

O Endpoint real (gestaobalanco) devolve os spreads de faturamento.
A eleição do **melhor balanço** (R1/R2/R3) é regra NOSSA e mora em `domain/eleicao.py` —
aqui o adapter só carrega os dados e chama `eleger`.

Retorna `None` quando não há balanço elegível (→ input MANUAL na tela).
"""

from __future__ import annotations

import json
import urllib.parse
import uuid
from datetime import date
from typing import Optional

import urllib3

from app.adapters.auth import TokenProvider, build_token_provider
from app.core.http_client import get_pool
from app.core.logging import get_bff_correlation_id, get_logger, log_event
from app.core.mascaramento import mascarar_documento
from app.core.retry import ErroServidorIntegracao, http_retry
from app.core.settings import settings
from app.core.ssl_context import criar_contexto_ssl
from app.domain.eleicao import ResultadoFaturamento, eleger  # re-exportado p/ compat de imports

_logger = get_logger("faturamento.endpoint")

__all__ = ["ResultadoFaturamento", "HttpEndpoint"]


def _extrair_spreads(data: object) -> list[dict]:
    """Extrai a lista de spreads de uma resposta que pode vir crua (lista) ou
    envelopada (``{"data": [...]}`` ou ``{"spreads": [...]}``)."""
    spreads = data if isinstance(data, list) else (data.get("data") or data.get("spreads") or [])
    return spreads if isinstance(spreads, list) else [data]


def _sem_zeros_a_esquerda(documento: str) -> str:
    """O Endpoint (Gestão Balanço/CRA) guarda o documento como INTEIRO na própria tabela —
    zeros à esquerda somem lá. Sem remover aqui antes de consultar, um documento como
    "050746577" não bate com o que está gravado e a consulta não encontra nada."""
    return str(int(documento))


_TAMANHO_PAGINA = 100  # itens por página pedidos ao Endpoint


class HttpEndpoint:
    """Integração real com Gestão Balanço (spreads de faturamento) via HTTP.

    Chama: GET {base_url}/gestaobalanco/v1/spreads-faturamento?documento={documento}&valido=true&page={n}&size=100

    `documento` filtra pelo CNPJ (campo `grupo_empresa.cod_docm_grup_baln_coro`, com LIKE
    no servidor) - `subgrupo`/`conglomerado` filtram por um código interno (UUID), não pelo
    documento, então não são usados aqui. `valido=true` é seguro de sempre mandar: as três
    regras (R1/R2/R3) exigem vigente=True, então filtrar isso no servidor só reduz volume,
    sem mudar o resultado da eleição. NÃO filtra por `situacao` (R1 não exige aprovado) nem
    por `dataInicial` (filtra pela data de ATUALIZAÇÃO do spread, não pela data do balanço
    que a nossa janela de 24 meses usa - não é equivalente, ver conversa/pendência).

    A resposta é PAGINADA (`page`/`size`/`totalElements`/`totalPages`) - busca TODAS as
    páginas antes de eleger, senão um candidato de R1 com categoria prioritária mas fora da
    1ª página nunca seria considerado (pode haver mais de um spread simultaneamente
    elegível para R1, com categorias diferentes).

    A eleição R1/R2/R3 continua nossa. É fallback: em falha, devolve None
    (o marcador fica MANUAL, não derruba a leitura).
    """

    def __init__(self, base_url: str, timeout: float = 5.0, token: TokenProvider | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or build_token_provider()

    def buscar(
        self, documento_raiz: str, asof: Optional[str] = None
    ) -> Optional[ResultadoFaturamento]:
        try:
            spreads = self._buscar_todas_paginas(_sem_zeros_a_esquerda(documento_raiz))
            ref = date.fromisoformat(asof) if asof else date.today()
            return eleger(spreads, ref)
        except Exception as e:  # fallback: não derruba a leitura
            log_event(
                _logger,
                "endpoint.indisponivel",
                level="error",
                erro=str(e),
                tipo_erro=type(e).__name__,
            )
            return None

    def _buscar_todas_paginas(self, documento_raiz: str) -> list[dict]:
        """Busca TODAS as páginas de spreads antes de devolver - o Endpoint pagina
        (page/size/totalElements/totalPages), e a eleição precisa ver a carteira inteira."""
        todos: list[dict] = []
        pagina = 1
        while True:
            corpo = self._buscar_spreads(documento_raiz, pagina)
            todos.extend(_extrair_spreads(corpo))
            total_paginas = corpo.get("totalPages", 1) if isinstance(corpo, dict) else 1
            if pagina >= total_paginas:
                break
            pagina += 1
        return todos

    @http_retry
    def _buscar_spreads(self, documento_raiz: str, pagina: int = 1) -> object:
        """Busca UMA página de spreads de faturamento para o documento (CNPJ).

        Devolve o corpo cru (dict paginado, ou lista, conforme o formato da resposta) -
        quem extrai a lista de spreads e decide se busca a próxima página é o chamador
        (`_buscar_todas_paginas`). Com retry automático em caso de timeout/erro transitório.
        """
        # Gerar correlation-id único (UUID)
        correlation_id = get_bff_correlation_id() or str(uuid.uuid4())

        # Montar headers
        headers = self._token.auth_headers()  # Authorization: Bearer <JWT>
        headers["x-itau-apikey"] = settings.itau_api_key
        headers["x-itau-correlationId"] = correlation_id
        headers["Content-Type"] = "application/json"

        # Montar URL — `documento` filtra pelo CNPJ; `valido=true` é seguro (as 3 regras
        # exigem vigente=True); `page`/`size` percorrem a paginação real do Endpoint.
        url = (
            f"{self.base_url}/gestaobalanco/v1/spreads-faturamento"
            f"?documento={urllib.parse.quote(documento_raiz)}&valido=true"
            f"&page={pagina}&size={_TAMANHO_PAGINA}"
        )

        # Log técnico da requisição — sem a URL completa (contém o documento na querystring)
        log_event(
            _logger,
            "endpoint.requisicao",
            level="debug",
            documento=mascarar_documento(documento_raiz),
            pagina=pagina,
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
                "endpoint.erro_rede",
                level="warning",
                documento=mascarar_documento(documento_raiz),
                correlation_id=correlation_id,
                erro=str(e),
                tentando_novamente=True,
            )
            raise

        if resp.status == 404:
            log_event(
                _logger,
                "endpoint.nao_encontrado",
                level="info",
                documento=mascarar_documento(documento_raiz),
                correlation_id=correlation_id,
                status_code=resp.status,
            )
            return []

        if resp.status >= 400:
            log_event(
                _logger,
                "endpoint.erro_http",
                level="error",
                documento=mascarar_documento(documento_raiz),
                correlation_id=correlation_id,
                status_code=resp.status,
                erro=resp.data.decode("utf-8", errors="replace")[:500],
            )
            if resp.status >= 500:
                # 5xx é transitório - será retentado pelo @http_retry
                raise ErroServidorIntegracao(f"Endpoint retornou HTTP {resp.status}")
            raise RuntimeError(f"Endpoint retornou HTTP {resp.status}")

        try:
            data = json.loads(resp.data.decode("utf-8"))

            log_event(
                _logger,
                "endpoint.sucesso",
                level="debug",
                documento=mascarar_documento(documento_raiz),
                pagina=pagina,
                correlation_id=correlation_id,
                status_code=resp.status,
            )

            return data

        except Exception as e:
            log_event(
                _logger,
                "endpoint.erro",
                level="error",
                documento=mascarar_documento(documento_raiz),
                correlation_id=correlation_id,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise

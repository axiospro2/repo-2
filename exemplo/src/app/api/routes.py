"""Rotas do BFF (uma API interna só – a Lambda de Faturamento atende salvar e buscar):
  - POST /faturamento/{documento}                    → repassar salvar (API interna)
  - GET  /faturamento/{documento}                     → repassar buscar (API interna)
  - GET  /conglomerados/{documento}/subgrupos         → repassar buscar (API interna)
  - GET  /grupos-economicos?documento=                → repassar busca "like" (API interna, autocomplete)
  - GET  /catalogo                                    → faixas + moedas (do parametros) para fronte-end
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status

from app.adapters import internal_api
from app.adapters.parametros import ParametrosCatalogo
from app.api.deps import get_parametros
from app.core.logging import bind_context, log_event, get_logger
from app.core.settings import settings

router = APIRouter()
_logger = get_logger("bff.routes")

# Constante para media type JSON (utilizada em múltiplas respostas)
_CONTENT_TYPE_JSON = "application/json"

# Type alias para melhor legibilidade
DocumentoPath = Annotated[
    str,
    Path(
        min_length=11,
        max_length=18,
        description="CPF/CNPJ/CGI do conglomerado",
        example="12345678901",
    )
]


def _montar_headers_downstream(request: Request) -> dict:
    """Monta os headers repassados pra API interna — mesmo conjunto em GET e POST:
      - x-racf: repassado tal qual veio na requisição original (responsabilização) — o
        BFF não sabe quem é o analista, só recebe (de um gateway/auth na frente) e repassa.
      - x-itau-correlationid: gerado NOVO aqui (UUID4) a cada chamada — correlaciona esta
        chamada específica BFF -> API interna nos logs dos dois lados; nunca aceito do
        caller (ele não deveria conseguir escolher o próprio correlation id).
      - x-itau-apikey: vem da config do BFF (`settings.itau_api_key`), nunca do caller —
        é credencial do BFF com a API interna, não algo que o front deveria conhecer.
    """
    headers = {
        "x-itau-correlationid": str(uuid.uuid4()),
        "x-itau-apikey": settings.itau_api_key,
    }
    racf = request.headers.get("x-racf")
    if racf:
        headers["x-racf"] = racf
    return headers


async def _forward(
    *,
    request: Request,
    documento: str,
    internal_path: str,
    operation: str,
    method: str,
) -> Response:
    """Repassa a requisição atual para a API interna e loga o ciclo completo.

    Compartilhado por todas as rotas de forward - a única diferença entre elas é
    o path na API interna, o método HTTP e o nome da operação (pro log).
    """
    bind_context(documento=documento, operation=operation)

    body = await request.body() if method == "POST" else None
    query_string = str(request.url.query) if request.url.query else ""
    forwarded_headers = _montar_headers_downstream(request)

    log_event(
        _logger,
        "forward_request_started",
        level="debug",
        method=method,
        path=internal_path,
        body_size=len(body) if body is not None else None,
        query_params=query_string or None,
    )

    try:
        status_code, response_body, content_type = await internal_api.forward(
            method,
            internal_path,
            body=body,
            query=query_string,
            extra_headers=forwarded_headers,
        )

        log_event(
            _logger,
            "forward_request_completed",
            level="info",
            method=method,
            path=internal_path,
            status_code=status_code,
            response_size=len(response_body),
        )

        return Response(
            content=response_body,
            status_code=status_code,
            media_type=content_type or _CONTENT_TYPE_JSON,
        )

    except Exception as e:
        log_event(
            _logger,
            "forward_request_failed",
            level="error",
            method=method,
            path=internal_path,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


@router.post(
    "/faturamento/{documento}",
    status_code=status.HTTP_200_OK,
    summary="Salvar dados de faturamento",
    description="Repassa requisicao para a API interna de faturamento (operacao de escrita)",
    tags=["Faturamento"],
    response_description="Resultado da operacao de salvamento de faturamento do conglomerado",
)
async def forward_salvar(request: Request, documento: DocumentoPath) -> Response:
    """Forward POST para API interna de faturamento."""
    return await _forward(
        request=request,
        documento=documento,
        internal_path=f"/faturamento/{documento}",
        operation="salvar",
        method="POST",
    )


@router.get(
    "/faturamento/{documento}",
    status_code=status.HTTP_200_OK,
    summary="Buscar dados de faturamento",
    description="Repassa requisicao para a API interna de faturamento (operacao de leitura)",
    tags=["Faturamento"],
    response_description="Dados de faturamento do conglomerado",
)
async def forward_buscar(request: Request, documento: DocumentoPath) -> Response:
    """Forward GET para API interna de faturamento."""
    return await _forward(
        request=request,
        documento=documento,
        internal_path=f"/faturamento/{documento}",
        operation="buscar",
        method="GET",
    )


@router.get(
    "/conglomerados/{documento}/subgrupos",
    status_code=status.HTTP_200_OK,
    summary="Listar subgrupos do conglomerado",
    description="Repassa requisicao para a API interna (busca hierarquia de subgrupos)",
    tags=["Conglomerados"],
    response_description="Lista de subgrupos do conglomerado"
)
async def forward_subgrupos(request: Request, documento: DocumentoPath) -> Response:
    """Forward GET para API interna de subgrupos."""
    return await _forward(
        request=request,
        documento=documento,
        internal_path=f"/conglomerados/{documento}/subgrupos",
        operation="listar_subgrupos",
        method="GET",
    )


@router.get(
    "/grupos-economicos",
    status_code=status.HTTP_200_OK,
    summary="Buscar grupos econômicos (autocomplete)",
    description="Repassa requisicao para a API interna de busca parcial ('like') por documento — usado pelo autocomplete do front, antes de escolher o documento exato pra buscar faturamento.",
    tags=["Conglomerados"],
    response_description="Lista de grupos econômicos (cabeça + subgrupos) que batem com o documento parcial",
)
async def forward_grupos_economicos(request: Request, documento: str = "") -> Response:
    """Forward GET para API interna de busca "like" de grupos econômicos.

    `documento` só entra na assinatura pra virar contexto de log (`bind_context`) — o
    valor real repassado pra API interna é a querystring inteira da requisição original
    (`request.url.query`, resolvido dentro de `_forward`), igual às outras rotas GET.
    """
    return await _forward(
        request=request,
        documento=documento,
        internal_path="/grupos-economicos",
        operation="buscar_grupos_economicos",
        method="GET",
    )


@router.get(
    "/catalogo",
    status_code=status.HTTP_200_OK,
    summary="Obter catalogo de parametros",
    description="Retorna faixas e moedas validas para o frontend (dropdowns). Sem validacao de negocio.",
    tags=["Catalogo"],
    response_description="Faixas e moedas disponiveis",
)
def catalogo(
    parametros: Annotated[ParametrosCatalogo, Depends(get_parametros)]
) -> dict:
    """Retorna catalogo de parametros (faixas e moedas) para o frontend.

    Esta rota NAO faz forward - consome diretamente o servico de parametros.
    Dados sao cacheados no adapter ParametrosCatalogo.
    """
    bind_context(operation="obter_catalogo")

    try:
        log_event(_logger, "catalogo_request_started", level="debug")

        catalogo_data = parametros.catalogo()

        log_event(
            _logger,
            "catalogo_request_completed",
            level="info",
            faixas_count=len(catalogo_data.get("faixas", [])),
            moedas_count=len(catalogo_data.get("moedas", [])),
        )

        return catalogo_data

    except Exception as e:
        log_event(
            _logger,
            "catalogo_request_failed",
            level="error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise

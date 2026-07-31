"""Adapter para a API interna de faturamento.

Repassa requisições do BFF para a API interna, anexando o token OAuth2
(client-credentials) obtido via `OAuth2Manager`. Uma única API interna
atende tanto salvar (POST) quanto buscar (GET).
"""
from __future__ import annotations

import json
import time

import httpx

from app.core.http_client import get_client
from app.core.logging import get_logger, log_event
from app.core.oauth2 import OAuth2Manager
from app.core.settings import settings

_logger = get_logger("bff.internal")

# `settings` já garante (fail-fast na inicialização) que as credenciais de
# auth estão presentes, então o manager pode ser construído direto - sem
# fallback silencioso "sem auth" e sem cache de erro de init.
_oauth2_manager = OAuth2Manager(
    token_url=settings.auth_token_url,
    client_id=settings.auth_client_id,
    client_secret=settings.auth_client_secret,
)


def _erro_json(mensagem: str, **campos: object) -> str:
    """Monta um corpo de erro JSON válido (nunca por f-string manual)."""
    return json.dumps({"erro": mensagem, **campos})


async def forward(
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    query: str = "",
    content_type: str = "application/json",
    extra_headers: dict | None = None,
) -> tuple[int, str, str]:
    """Repassa uma requisição para a API interna, com token OAuth2 anexado.

    `extra_headers` repassa cabeçalhos relevantes (ex.: RACF de
    responsabilização), tanto em POST quanto em GET.

    Devolve (status_code, corpo, content_type), propagando o status/corpo da
    API interna (200/201/404/409/422/...). 502 se a interna não responder ou
    se a obtenção do token de autenticação falhar.
    """
    url = f"{settings.internal_api_base_url}{path}"
    if query:
        url = f"{url}?{query}"

    headers = dict(extra_headers or {})
    if method == "POST":
        headers["Content-Type"] = content_type

    try:
        headers.update(await _oauth2_manager.get_auth_header())
    except RuntimeError as e:
        error_msg = str(e)
        log_event(_logger, "bff.oauth2_error", level="error", error=error_msg, path=path)
        return (
            502,
            _erro_json("BFF falhou ao obter token de autenticacao", detalhes=error_msg),
            "application/json",
        )

    return await _executar_requisicao(url, method, headers, body)


async def _executar_requisicao(
    url: str,
    method: str,
    headers: dict,
    body: bytes | None = None,
) -> tuple[int, str, str]:
    """Executa a requisição HTTP e trata falhas de rede.

    Retorna (status_code, corpo, content_type). O httpx não levanta exceção
    para respostas 4xx/5xx da API interna (só para falhas de rede/timeout),
    então status como 404/409/422 já chegam aqui como resposta normal.
    """
    client = await get_client()
    inicio = time.perf_counter()
    try:
        response = await client.request(
            method, url, content=body, headers=headers, timeout=settings.integ_timeout_s,
        )
        duracao_ms = round((time.perf_counter() - inicio) * 1000, 1)
        log_event(_logger, "bff.forward", status=response.status_code, latency_ms=duracao_ms)
        content_type = response.headers.get("Content-Type", "application/json")
        return response.status_code, response.text, content_type
    except httpx.HTTPError as e:
        duracao_ms = round((time.perf_counter() - inicio) * 1000, 1)
        log_event(_logger, "bff.forward_indisponivel", level="error", erro=str(e), latency_ms=duracao_ms)
        return (
            502,
            _erro_json("BFF nao alcancou a API interna", duracao_ms=duracao_ms),
            "application/json",
        )

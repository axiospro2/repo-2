"""Auth M2M (JWT client_credentials) para as chamadas externas (NJ6, Endpoint, Parâmetros).

Usa OAuth2Manager do módulo core para geração de token com o STS interno do Itaú.
O fluxo é simples:
    Lambda → OAuth2Manager.get_token()
        → POST /api/oauth/token (STS Itaú)
        → { access_token, expires_in }
        → Authorization: Bearer <token>

Ports (NJ6/Endpoint/Parâmetros) recebem um `TokenProvider` e chamam `auth_headers()`.
Trocar aqui não toca no domínio.
"""
from __future__ import annotations

from typing import Protocol

from app.core.logging import get_logger, log_event
from app.core.oauth2 import OAuth2Manager
from app.core.settings import settings

_logger = get_logger("faturamento.auth")


class TokenProvider(Protocol):
    def get_token(self) -> str: ...
    def auth_headers(self) -> dict: ...


class OAuth2TokenProvider:
    """Adaptador que implementa TokenProvider usando OAuth2Manager."""

    def __init__(self, manager: OAuth2Manager):
        self._manager = manager

    def get_token(self) -> str:
        """Obtém token válido (usa cache se disponível, renova se necessário)."""
        return self._manager.get_token()

    def auth_headers(self) -> dict:
        """Retorna o header Authorization pronto para usar em requisições."""
        return self._manager.get_auth_header()


def build_token_provider() -> TokenProvider:
    """Cria OAuth2TokenProvider com TOKEN_URL, AUTH_CLIENT_ID e AUTH_CLIENT_SECRET.

    Raises:
        ValueError: Se TOKEN_URL, AUTH_CLIENT_ID ou AUTH_CLIENT_SECRET não estiverem configurados.
    """
    token_url = settings.token_url
    client_id = settings.auth_client_id
    client_secret = settings.auth_client_secret

    # Diagnóstico
    log_event(
        _logger,
        "auth.provider.diagnostico",
        level="info",
        has_token_url=bool(token_url),
        has_client_id=bool(client_id),
        client_id_length=len(client_id) if client_id else 0,
        has_client_secret=bool(client_secret),
        client_secret_length=len(client_secret) if client_secret else 0,
    )

    if not token_url:
        raise ValueError(
            "TOKEN_URL não configurada. É obrigatória para autenticação M2M. "
            "Configure a variável de ambiente TOKEN_URL."
        )

    if not client_id:
        raise ValueError(
            "AUTH_CLIENT_ID não configurado. É obrigatório para autenticação M2M. "
            "Configure a variável de ambiente AUTH_CLIENT_ID."
        )

    if not client_secret:
        raise ValueError(
            "AUTH_CLIENT_SECRET não configurado. É obrigatório para autenticação M2M. "
            "Configure a variável de ambiente AUTH_CLIENT_SECRET."
        )

    log_event(
        _logger,
        "auth.provider.inicializado",
        level="info",
        tipo="OAuth2TokenProvider",
        token_url=token_url,
        client_id=client_id,
    )

    manager = OAuth2Manager(
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
    )

    return OAuth2TokenProvider(manager)

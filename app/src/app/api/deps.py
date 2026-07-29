"""Dependências (singletons reaproveitados entre invocações da Lambda quente).

Uma Lambda serve SALVAR (POST) e BUSCAR (GET). O salvar usa repo + parâmetros; o buscar usa
repo + NJ6 + Endpoint + catálogo. As integrações de leitura usam MOCK por padrão (fixtures);
com USAR_MOCK_INTEGRACOES=0 trocam para os stubs HTTP — trocar aqui, sem tocar no service.

As chamadas externas autenticam com JWT (client_credentials) via um `TokenProvider` único —
mock por padrão; com `TOKEN_URL` setada vira o provider HTTP real (trocar só a URL).
"""
from __future__ import annotations

from functools import lru_cache

from app.adapters.auth import TokenProvider, build_token_provider
from app.adapters.endpoint import HttpEndpoint
from app.adapters.nj6 import HttpNJ6
from app.adapters.parametros import ParametrosCatalogo, ParametrosClient
from app.adapters.repository import DynamoRepository
from app.core.settings import settings


@lru_cache(maxsize=1)
def get_token_provider() -> TokenProvider:
    return build_token_provider()


@lru_cache(maxsize=1)
def get_repo() -> DynamoRepository:
    return DynamoRepository()


# ─────────── SALVAR ───────────
@lru_cache(maxsize=1)
def get_parametros() -> ParametrosClient:
    return ParametrosClient(token=get_token_provider())


# ─────────── BUSCAR ───────────
@lru_cache(maxsize=1)
def get_nj6():
    return HttpNJ6(settings.nj6_base_url, settings.integ_timeout_s, token=get_token_provider())


@lru_cache(maxsize=1)
def get_endpoint():
    return HttpEndpoint(settings.endpoint_base_url, settings.integ_timeout_s, token=get_token_provider())


@lru_cache(maxsize=1)
def get_catalogo() -> ParametrosCatalogo:
    return ParametrosCatalogo(token=get_token_provider())

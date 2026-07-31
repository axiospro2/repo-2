"""Dependências (singletons reaproveitados entre invocações da Lambda quente).

Uma Lambda serve SALVAR (POST) e BUSCAR (GET). O salvar usa repo + parâmetros; o buscar usa
repo + NJ6 + Endpoint + catálogo. `HttpNJ6`/`HttpEndpoint` são sempre a implementação real —
não há uma classe "mock" alternativa aqui. O ambiente local usa mocks trocando apenas as
URLs de destino (`NJ6_BASE_URL` etc. apontando para o stack `docker-compose` — ver
`SETUP.md`), sem precisar tocar neste módulo nem no `service`.

As chamadas HTTP (NJ6/Endpoint) autenticam com JWT (client_credentials) via um
`TokenProvider` único (`get_token_provider`, com `lru_cache`). `ParametrosClient`/
`ParametrosCatalogo` NÃO usam esse token — conectam direto no cluster QuickConfig via
`QUICKCONFIG_CLUSTER_MEMBERS` (biblioteca interna `manager`, não HTTP).
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
    return ParametrosClient()


# ─────────── BUSCAR ───────────
@lru_cache(maxsize=1)
def get_nj6():
    return HttpNJ6(settings.nj6_base_url, settings.integ_timeout_s, token=get_token_provider())


@lru_cache(maxsize=1)
def get_endpoint():
    return HttpEndpoint(
        settings.endpoint_base_url, settings.integ_timeout_s, token=get_token_provider()
    )


@lru_cache(maxsize=1)
def get_catalogo() -> ParametrosCatalogo:
    return ParametrosCatalogo()

"""Fixtures compartilhadas da suíte.

Roda antes da coleção de qualquer teste no diretório (garantia do pytest) -
por isso o stub do pacote `manager` e as env vars obrigatórias de `Settings`
vivem aqui: sem isso, o simples ato de importar `app.adapters.parametros` ou
`app.core.settings` já quebraria a coleta dos testes.
"""
from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest


def _stub_manager_module() -> None:
    """Registra um stub de `manager` em sys.modules.

    `app.adapters.parametros` faz `from manager import ConfigurationService,
    QuickConfigConfigurationSource` no topo do módulo - mantido de propósito,
    é um pacote interno do Itaú (QuickConfig) não instalável fora da rede
    interna. Sem esse stub, importar `app.adapters.parametros` (direto ou via
    `app.api.routes`) quebra em qualquer máquina/CI fora dessa rede. Os
    testes que exercitam `ParametrosCatalogo` de verdade fazem
    `@patch("app.adapters.parametros.ConfigurationService")` etc., então o
    comportamento real dessas classes stub nunca é exercitado.
    """
    if "manager" in sys.modules:
        return

    stub = types.ModuleType("manager")

    class ConfigurationService:
        def __init__(self, config_source: Any) -> None:
            self.config_source = config_source

        def get_config_for_app(self, app_name: str, key: str, default: str = "[]") -> str:
            return default

    class QuickConfigConfigurationSource:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    stub.ConfigurationService = ConfigurationService
    stub.QuickConfigConfigurationSource = QuickConfigConfigurationSource
    sys.modules["manager"] = stub


def _set_baseline_env() -> None:
    """Env vars mínimas para `Settings()` não estourar ValidationError.

    `settings = Settings()` roda no import de `app.core.settings`, e várias
    coisas importam esse módulo no nível de arquivo de teste - então essas
    env vars precisam existir ANTES de qualquer import de módulo `app.*`.
    Testes que querem validar o comportamento de configuração ausente devem
    instanciar `Settings(...)` diretamente com os campos que querem testar,
    não mexer nessas env vars de processo.
    """
    os.environ.setdefault("AUTH_TOKEN_URL", "https://auth.example.com/token")
    os.environ.setdefault("AUTH_CLIENT_ID", "test-client-id")
    os.environ.setdefault("AUTH_CLIENT_SECRET", "test-client-secret")
    os.environ.setdefault("API_DNS", "example.com")


_stub_manager_module()
_set_baseline_env()


@pytest.fixture
def anyio_backend() -> str:
    """Roda os testes async (`@pytest.mark.anyio`) só no backend asyncio."""
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_oauth2_cache():
    """Garante que o cache de tokens OAuth2 não vaza entre testes."""
    from app.core.oauth2 import clear_token_cache

    clear_token_cache()
    yield
    clear_token_cache()

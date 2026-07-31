"""Config compartilhada do pytest.

`pytest.ini` já adiciona `src` ao sys.path via `pythonpath = src`; este arquivo
é uma rede de segurança para quem rodar `pytest` de um diretório diferente ou
com uma versão de pytest anterior a 7.0 (sem suporte a `pythonpath` no ini).

Também registra o stub do pacote `manager` — ver `_stub_manager_module` — antes
de qualquer import de módulo `app.*`, já que `app.adapters.parametros` importa
`manager` no topo do arquivo.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any


def _stub_manager_module() -> None:
    """Registra um stub de `manager` em `sys.modules`.

    `app.adapters.parametros` faz `from manager import ConfigurationService,
    QuickConfigConfigurationSource` no topo do módulo — mantido de propósito,
    é um pacote interno do Itaú (QuickConfig) não instalável fora da rede
    interna. Sem esse stub, importar `app.adapters.parametros` (direto ou via
    `app.api.deps`/`app.main`) quebra em qualquer máquina/CI fora dessa rede.
    Os testes que exercitam `ParametrosClient`/`ParametrosCatalogo` de verdade
    fazem `@patch("app.adapters.parametros.ConfigurationService")` etc., então
    o comportamento real dessas classes stub nunca é exercitado.
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


_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_stub_manager_module()

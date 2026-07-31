"""Stub LOCAL de dev da lib interna QuickConfig (`manager`) — NÃO é a lib real.

Existe só pra `uvicorn`/`python -m app.main` conseguirem importar
`app.adapters.parametros` fora da rede do Itaú. Nunca conecta em nada de
verdade: `ConfigurationService.get_config_for_app` sempre devolve o `default`
que foi passado — na prática, isso faz `ParametrosClient`/`ParametrosCatalogo`
sempre caírem no fallback hardcoded (6 faixas, BRL/USD, 30%), porque
`QUICKCONFIG_CLUSTER_MEMBERS` também não está setado localmente (ver `.env.example`).

Em produção (Lambda real), este stub NUNCA é usado — o `manager` real vem do
artifactory interno do Itaú, instalado no ambiente de build/deploy.
"""

from __future__ import annotations

from typing import Any


class ConfigurationService:
    def __init__(self, config_source: Any) -> None:
        self.config_source = config_source

    def get_config_for_app(self, app_name: str, key: str, default: str = "[]") -> str:
        return default


class QuickConfigConfigurationSource:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

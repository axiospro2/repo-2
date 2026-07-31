"""Helpers de teste compartilhados (não é um módulo de teste - sem prefixo test_)."""
from __future__ import annotations

from typing import Any


class FakeAsyncClient:
    """Substitui `httpx.AsyncClient` nos testes - sem rede real.

    `responses` é consumida em ordem (uma por chamada); `exception`, se
    informada, é levantada em toda chamada em vez de devolver uma resposta.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        exception: Exception | None = None,
    ) -> None:
        self._responses = list(responses) if responses is not None else None
        self._exception = exception
        self.calls: list[dict[str, Any]] = []

    async def _handle(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._exception is not None:
            raise self._exception
        return self._responses.pop(0)

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return await self._handle(method, url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self._handle("POST", url, **kwargs)


def patch_get_client(monkeypatch: Any, module_path: str, client: FakeAsyncClient) -> None:
    """Substitui o `get_client` importado em `module_path` pelo fake client.

    `oauth2.py`/`internal_api.py` fazem `from app.core.http_client import
    get_client`, então o patch precisa mirar o nome já vinculado no módulo
    que importou - patchar `app.core.http_client.get_client` não teria
    efeito nenhum nesses módulos.
    """

    async def _get_client() -> FakeAsyncClient:
        return client

    monkeypatch.setattr(f"{module_path}.get_client", _get_client)

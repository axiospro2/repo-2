"""Dublês de infraestrutura HTTP (urllib3) para testar os adapters reais
(HttpNJ6, HttpEndpoint, _ClienteParametros, OAuth2Manager) sem rede.

Distintos de `tests/fakes.py` (que dublam os Protocols do domínio, não a
camada HTTP em si)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeResponse:
    status: int
    data: bytes = b"{}"


class FakePool:
    """Substitui `urllib3.PoolManager`: mesma assinatura de `.request(...)` usada
    pelos adapters. `respostas` é consumida em ordem a cada chamada — uma lista de
    `FakeResponse` ou `Exception` permite simular retry (falha, falha, sucesso)."""

    def __init__(self, respostas: list) -> None:
        self._respostas = list(respostas)
        self.chamadas: list[dict] = []

    def request(self, method, url, headers=None, timeout=None, body=None, **kwargs):
        self.chamadas.append({"method": method, "url": url, "headers": headers, "body": body})
        item = self._respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeTokenProvider:
    def get_token(self) -> str:
        return "fake-token"

    def auth_headers(self) -> dict:
        return {"Authorization": "Bearer fake-token"}

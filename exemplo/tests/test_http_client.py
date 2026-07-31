"""Testes para o cliente HTTP assíncrono singleton, seguro entre event loops."""
from __future__ import annotations

import asyncio

import httpx
import pytest

import app.core.http_client as http_client_mod
from app.core.http_client import get_client

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset_client_state():
    """O client é estado global do módulo - não pode vazar entre testes."""
    http_client_mod._client = None
    http_client_mod._client_loop = None
    yield
    http_client_mod._client = None
    http_client_mod._client_loop = None


class TestGetClient:
    async def test_retorna_instancia_httpx_async_client(self):
        client = await get_client()
        assert isinstance(client, httpx.AsyncClient)

    async def test_reaproveita_client_no_mesmo_loop(self):
        """Ganho real de conexão: dentro da mesma invocação/loop, é sempre o mesmo client."""
        client1 = await get_client()
        client2 = await get_client()
        assert client1 is client2

    def test_recria_client_quando_o_loop_muda(self):
        """Simula o cenário do Mangum: cada invocação pode rodar em um event
        loop novo. Um client preso ao loop anterior não pode ser reaproveitado
        com segurança - get_client precisa detectar e recriar."""
        client_loop_1 = asyncio.run(get_client())
        client_loop_2 = asyncio.run(get_client())

        assert client_loop_1 is not client_loop_2

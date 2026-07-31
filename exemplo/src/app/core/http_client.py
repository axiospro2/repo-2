"""Cliente HTTP assíncrono compartilhado, seguro entre invocações da Lambda.

O Mangum pode criar um novo event loop a cada invocação; um `httpx.AsyncClient`
preso a um loop fechado não pode ser reaproveitado com segurança. `get_client`
guarda o client junto com uma referência ao loop em que foi criado e o recria
automaticamente quando o loop muda - funciona tanto se o Mangum reaproveita o
loop entre invocações "quentes" (ganho real: conexões TCP/TLS reaproveitadas)
quanto se cria um novo loop a cada chamada (sempre seguro, só perde o
reaproveitamento naquela invocação).
"""
from __future__ import annotations

import asyncio

import httpx

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


async def get_client() -> httpx.AsyncClient:
    """Retorna o client HTTP assíncrono singleton para o loop atual."""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        _client = httpx.AsyncClient()
        _client_loop = loop
    return _client

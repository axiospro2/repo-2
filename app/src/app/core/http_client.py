"""Cliente HTTP compartilhado (pool de conexões keep-alive) para as chamadas externas.

Por quê: `urllib.request.urlopen` abre uma conexão TCP+TLS nova a cada chamada. Numa
Lambda que faz de 2 a 4 chamadas HTTPS sequenciais por requisição (token + NJ6/Endpoint/
Parâmetros), isso paga um handshake completo toda vez — inclusive em invocações "quentes",
onde o processo (e portanto uma conexão mantida viva) sobrevive entre invocações. Um
`urllib3.PoolManager` guardado em nível de módulo reaproveita as conexões keep-alive entre
invocações, no mesmo espírito do cache de token em `core/oauth2.py`.

Pools nomeados (não um só): o STS (autenticação) e as integrações (NJ6/Endpoint/Parâmetros)
resolvem a CA bundle por mecanismos diferentes (`oauth2._get_ssl_context` vs.
`ssl_context.criar_contexto_ssl`), então cada um mantém seu próprio pool. O contexto SSL só
é aplicado na criação de cada pool — chamadas seguintes reaproveitam o pool já existente, já
que as variáveis de ambiente que definem a CA bundle não mudam durante a vida do processo.
"""

from __future__ import annotations

import ssl

import urllib3

_pools: dict[str, urllib3.PoolManager] = {}


def get_pool(nome: str, ssl_context: ssl.SSLContext | None = None) -> urllib3.PoolManager:
    """Devolve (criando na 1ª chamada) o PoolManager de conexões keep-alive para `nome`."""
    pool = _pools.get(nome)
    if pool is None:
        pool = urllib3.PoolManager(
            ssl_context=ssl_context,
            maxsize=10,
            retries=False,  # retry de aplicação já é feito pelo tenacity (core/retry.py)
        )
        _pools[nome] = pool
    return pool

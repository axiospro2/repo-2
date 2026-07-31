import urllib3

from app.core import http_client


def test_get_pool_cria_na_primeira_chamada():
    http_client._pools.pop("teste-pool", None)
    pool = http_client.get_pool("teste-pool")
    assert isinstance(pool, urllib3.PoolManager)


def test_get_pool_reaproveita_pool_existente():
    http_client._pools.pop("teste-pool-2", None)
    pool1 = http_client.get_pool("teste-pool-2")
    pool2 = http_client.get_pool("teste-pool-2")
    assert pool1 is pool2

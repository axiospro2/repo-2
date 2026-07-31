import json

import pytest
import urllib3

from app.core.oauth2 import OAuth2Manager, _get_ssl_context, _token_cache
from tests.http_fakes import FakePool, FakeResponse


class _FakeSSLContext:
    def __init__(self, falha: bool = False):
        self._falha = falha
        self.carregado_com = None

    def load_verify_locations(self, cafile=None, capath=None):
        if self._falha:
            raise RuntimeError("cert inválido (simulado)")
        self.carregado_com = cafile or capath


def _patch_pool(monkeypatch, pool: FakePool) -> None:
    monkeypatch.setattr("app.core.oauth2.get_pool", lambda *a, **k: pool)


def _manager(token_url: str, **kwargs) -> OAuth2Manager:
    return OAuth2Manager(token_url=token_url, client_id="cid", client_secret="secret", **kwargs)


# ─────────── _get_ssl_context ───────────


def test_get_ssl_context_sem_certificados_usa_sistema(monkeypatch):
    monkeypatch.setattr("app.core.oauth2.os.path.isfile", lambda p: False)
    ctx = _get_ssl_context()
    assert ctx is not None


def test_get_ssl_context_sucesso_no_primeiro_caminho(monkeypatch):
    monkeypatch.setattr("app.core.oauth2.os.path.isfile", lambda p: True)
    monkeypatch.setattr("app.core.oauth2.ssl.create_default_context", lambda: _FakeSSLContext())
    ctx = _get_ssl_context()
    assert isinstance(ctx, _FakeSSLContext)
    assert ctx.carregado_com == "/opt/ca_bundle.crt"


def test_get_ssl_context_falha_no_primeiro_e_sucesso_no_segundo(monkeypatch):
    monkeypatch.setattr("app.core.oauth2.os.path.isfile", lambda p: True)
    contextos = [_FakeSSLContext(falha=True), _FakeSSLContext(falha=False)]
    monkeypatch.setattr("app.core.oauth2.ssl.create_default_context", lambda: contextos.pop(0))
    ctx = _get_ssl_context()
    assert isinstance(ctx, _FakeSSLContext)
    assert ctx.carregado_com == "/opt/certs/ca_bundle.crt"


# ─────────── OAuth2Manager.__post_init__ ───────────


def test_post_init_exige_token_url():
    with pytest.raises(ValueError):
        OAuth2Manager(token_url="", client_id="a", client_secret="b")


def test_post_init_exige_client_id():
    with pytest.raises(ValueError):
        OAuth2Manager(token_url="http://mock/token", client_id="", client_secret="b")


def test_post_init_exige_client_secret():
    with pytest.raises(ValueError):
        OAuth2Manager(token_url="http://mock/token", client_id="a", client_secret="")


# ─────────── get_token / cache ───────────


def test_get_token_busca_e_cacheia(monkeypatch):
    pool = FakePool(
        [FakeResponse(200, json.dumps({"access_token": "tok-1", "expires_in": 3600}).encode())]
    )
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-a")

    assert manager.get_token() == "tok-1"
    assert manager.get_token() == "tok-1"  # cache hit
    assert len(pool.chamadas) == 1


def test_get_token_cache_expirado_renova(monkeypatch):
    pool = FakePool([
        FakeResponse(200, json.dumps({"access_token": "tok-1", "expires_in": 3600}).encode()),
        FakeResponse(200, json.dumps({"access_token": "tok-2", "expires_in": 3600}).encode()),
    ])
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-b")

    assert manager.get_token() == "tok-1"
    _token_cache["http://mock/token-b"]["expira_em"] = 0  # força expiração
    assert manager.get_token() == "tok-2"
    assert len(pool.chamadas) == 2


def test_get_auth_header(monkeypatch):
    pool = FakePool(
        [FakeResponse(200, json.dumps({"access_token": "tok-x", "expires_in": 3600}).encode())]
    )
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-c")

    assert manager.get_auth_header() == {"Authorization": "Bearer tok-x"}


def test_clear_cache_remove_entrada_existente(monkeypatch):
    pool = FakePool(
        [FakeResponse(200, json.dumps({"access_token": "tok-y", "expires_in": 3600}).encode())]
    )
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-d")
    manager.get_token()

    manager.clear_cache()
    assert "http://mock/token-d" not in _token_cache


def test_clear_cache_sem_entrada_nao_falha():
    manager = _manager("http://mock/token-nunca-usado")
    manager.clear_cache()  # não deve lançar


# ─────────── _obter_token ───────────


def test_obter_token_com_headers_itau(monkeypatch):
    pool = FakePool(
        [FakeResponse(200, json.dumps({"access_token": "tok-h", "expires_in": 100}).encode())]
    )
    _patch_pool(monkeypatch, pool)
    manager = _manager(
        "http://mock/token-e",
        itau_apikey="key123",
        itau_correlationid="corr123",
        itau_flowid="flow123",
    )

    token, expires_in = manager._obter_token()
    assert token == "tok-h"
    assert expires_in == 100
    headers = pool.chamadas[0]["headers"]
    assert headers["x-itau-apikey"] == "key123"
    assert headers["x-itau-correlationid"] == "corr123"
    assert headers["x-itau-flowid"] == "flow123"


def test_obter_token_expires_in_ausente_usa_default(monkeypatch):
    pool = FakePool([FakeResponse(200, json.dumps({"access_token": "tok-f"}).encode())])
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-f")

    _, expires_in = manager._obter_token()
    assert expires_in == 3600


def test_obter_token_erro_rede_propaga(monkeypatch):
    pool = FakePool([urllib3.exceptions.HTTPError("timeout simulado")])
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-g")

    with pytest.raises(urllib3.exceptions.HTTPError):
        manager._obter_token()


def test_obter_token_http_erro_levanta_runtime_error(monkeypatch):
    pool = FakePool([FakeResponse(401, b"unauthorized")])
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-i")

    with pytest.raises(RuntimeError):
        manager._obter_token()


def test_obter_token_sem_access_token_levanta_value_error(monkeypatch):
    pool = FakePool([FakeResponse(200, json.dumps({"expires_in": 100}).encode())])
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-j")

    with pytest.raises(ValueError):
        manager._obter_token()


def test_obter_token_json_invalido_propaga(monkeypatch):
    pool = FakePool([FakeResponse(200, b"nao e json{")])
    _patch_pool(monkeypatch, pool)
    manager = _manager("http://mock/token-k")

    with pytest.raises(json.JSONDecodeError):
        manager._obter_token()

"""Testes para o módulo de autenticação OAuth2 (async, httpx)."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.core.oauth2 import OAuth2Manager, OAuth2Token, _token_cache, clear_token_cache
from tests._helpers import FakeAsyncClient, patch_get_client

pytestmark = pytest.mark.anyio

TOKEN_URL = "https://auth.example.com/oauth2/token"
CLIENT_ID = "test_client_id_12345"
CLIENT_SECRET = "test_client_secret"


def _token_response(status_code: int = 200, **payload) -> httpx.Response:
    body = {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600, **payload}
    request = httpx.Request("POST", TOKEN_URL)
    return httpx.Response(status_code, json=body, request=request)


def _manager(**kwargs) -> OAuth2Manager:
    return OAuth2Manager(token_url=TOKEN_URL, client_id=CLIENT_ID, client_secret=CLIENT_SECRET, **kwargs)


class TestOAuth2Token:
    def test_oauth2_token_creation(self):
        token = OAuth2Token(
            access_token="test_token_123",
            token_type="Bearer",
            expires_in=3600,
            expiration_time=time.time() + 3600,
        )
        assert token.access_token == "test_token_123"
        assert token.token_type == "Bearer"
        assert token.expires_in == 3600
        assert isinstance(token.expiration_time, float)


class TestOAuth2ManagerInit:
    def test_init_with_basic_auth(self):
        manager = _manager(use_basic_auth=True)
        assert manager.use_basic_auth is True
        assert manager.timeout == 10.0
        assert manager.correlation_id_prefix == "bff-faturamento"

    def test_init_with_body_credentials(self):
        manager = _manager(use_basic_auth=False)
        assert manager.use_basic_auth is False

    def test_init_custom_parameters(self):
        manager = _manager(timeout=30, correlation_id_prefix="custom-prefix")
        assert manager.timeout == 30
        assert manager.correlation_id_prefix == "custom-prefix"

    def test_cache_key_inclui_client_id(self):
        """Regressão: a chave de cache não pode colidir entre client_ids diferentes."""
        m1 = OAuth2Manager(token_url=TOKEN_URL, client_id="client-a", client_secret="s")
        m2 = OAuth2Manager(token_url=TOKEN_URL, client_id="client-b", client_secret="s")
        assert m1._cache_key != m2._cache_key


class TestSolicitarToken:
    async def test_sucesso_basic_auth_envia_header_authorization(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(access_token="new_access_token_xyz")])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager(use_basic_auth=True)
        token = await manager._solicitar_token()

        assert token.access_token == "new_access_token_xyz"
        headers = client.calls[0]["headers"]
        assert headers["Authorization"].startswith("Basic ")

    async def test_sucesso_body_credentials_sem_header_authorization(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(access_token="body_auth_token", expires_in=7200)])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager(use_basic_auth=False)
        token = await manager._solicitar_token()

        assert token.access_token == "body_auth_token"
        assert token.expires_in == 7200
        call = client.calls[0]
        assert "Authorization" not in call["headers"]
        assert call["data"]["client_id"] == CLIENT_ID
        assert call["data"]["client_secret"] == CLIENT_SECRET

    async def test_http_status_error(self, monkeypatch):
        response = httpx.Response(401, request=httpx.Request("POST", TOKEN_URL))
        client = FakeAsyncClient(responses=[response])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        with pytest.raises(RuntimeError, match="401"):
            await _manager()._solicitar_token()

    async def test_erro_de_rede(self, monkeypatch):
        client = FakeAsyncClient(exception=httpx.ConnectError("Connection refused"))
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        with pytest.raises(RuntimeError, match="nao alcancavel"):
            await _manager()._solicitar_token()

    async def test_json_invalido(self, monkeypatch):
        request = httpx.Request("POST", TOKEN_URL)
        response = httpx.Response(200, content=b"invalid json{", request=request)
        client = FakeAsyncClient(responses=[response])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        with pytest.raises(RuntimeError, match="JSON invalida"):
            await _manager()._solicitar_token()

    async def test_campo_access_token_ausente(self, monkeypatch):
        request = httpx.Request("POST", TOKEN_URL)
        response = httpx.Response(200, json={"token_type": "Bearer", "expires_in": 3600}, request=request)
        client = FakeAsyncClient(responses=[response])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        with pytest.raises(RuntimeError, match="Campo obrigatorio ausente"):
            await _manager()._solicitar_token()

    async def test_buffer_de_expiracao(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(expires_in=1000)])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        antes = time.time()
        token = await _manager()._solicitar_token()

        # Buffer = 10% de 1000 = 100s -> expiration_time ~= antes + 900
        assert token.expiration_time == pytest.approx(antes + 900, abs=2)


class TestGetToken:
    async def test_cacheia_token(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(access_token="cached_token_123")])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager()
        assert await manager.get_token() == "cached_token_123"
        assert await manager.get_token() == "cached_token_123"
        assert len(client.calls) == 1

    async def test_renova_token_expirado(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(access_token="old_token")])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager()
        assert await manager.get_token() == "old_token"

        # Força expiração sem depender de time.sleep real
        _token_cache[manager._cache_key].expiration_time = time.time() - 1
        client._responses.append(_token_response(access_token="new_token"))

        assert await manager.get_token() == "new_token"
        assert len(client.calls) == 2

    async def test_get_auth_header(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(access_token="header_test_token")])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        header = await _manager().get_auth_header()
        assert header == {"Authorization": "Bearer header_test_token"}

    async def test_client_ids_diferentes_nao_compartilham_cache(self, monkeypatch):
        client = FakeAsyncClient(responses=[
            _token_response(access_token="token-a"),
            _token_response(access_token="token-b"),
        ])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        m1 = OAuth2Manager(token_url=TOKEN_URL, client_id="client-a", client_secret="s")
        m2 = OAuth2Manager(token_url=TOKEN_URL, client_id="client-b", client_secret="s")

        assert await m1.get_token() == "token-a"
        assert await m2.get_token() == "token-b"
        assert len(client.calls) == 2

    async def test_chamadas_concorrentes_nao_quebram(self, monkeypatch):
        n = 5
        client = FakeAsyncClient(responses=[_token_response(access_token=f"tok-{i}") for i in range(n)])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager()
        resultados = await asyncio.gather(*(manager.get_token() for _ in range(n)))

        assert all(r.startswith("tok-") for r in resultados)


class TestClearTokenCache:
    async def test_limpa_cache(self, monkeypatch):
        client = FakeAsyncClient(responses=[_token_response(access_token="cache_clear_token")])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager()
        await manager.get_token()
        assert len(_token_cache) > 0

        clear_token_cache()
        assert len(_token_cache) == 0

    async def test_limpar_cache_forca_nova_request(self, monkeypatch):
        client = FakeAsyncClient(responses=[
            _token_response(access_token="a"),
            _token_response(access_token="b"),
        ])
        patch_get_client(monkeypatch, "app.core.oauth2", client)

        manager = _manager()
        await manager.get_token()
        await manager.get_token()
        assert len(client.calls) == 1

        clear_token_cache()
        await manager.get_token()
        assert len(client.calls) == 2

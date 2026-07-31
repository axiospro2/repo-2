"""Testes para o adapter da API interna (forward() unificado, async/httpx)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

import app.adapters.internal_api as internal_api
from tests._helpers import FakeAsyncClient, patch_get_client

pytestmark = pytest.mark.anyio

BASE_URL = "https://internal.example.com"


@pytest.fixture(autouse=True)
def _base_url(monkeypatch):
    monkeypatch.setattr(internal_api.settings, "internal_api_base_url", BASE_URL)
    monkeypatch.setattr(internal_api.settings, "integ_timeout_s", 10.0)


@pytest.fixture(autouse=True)
def _auth_ok(monkeypatch):
    """Por padrão, o OAuth2 sempre resolve com sucesso - testes específicos sobrescrevem."""
    mock = AsyncMock(return_value={"Authorization": "Bearer test-token"})
    monkeypatch.setattr(internal_api._oauth2_manager, "get_auth_header", mock)
    return mock


def _response(status_code: int, **kwargs) -> httpx.Response:
    request = httpx.Request("GET", BASE_URL)
    return httpx.Response(status_code, request=request, **kwargs)


class TestForwardSucesso:
    async def test_post_propaga_status_e_corpo(self, monkeypatch):
        client = FakeAsyncClient(responses=[
            _response(201, json={"id": "123"}, headers={"Content-Type": "application/json"}),
        ])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        status, body, content_type = await internal_api.forward(
            "POST", "/api/resource", body=b'{"data": "test"}',
        )

        assert status == 201
        assert json.loads(body) == {"id": "123"}
        assert content_type == "application/json"

    @pytest.mark.parametrize("status_code", [200, 404, 409, 422])
    async def test_propaga_qualquer_status_da_api_interna(self, monkeypatch, status_code):
        """httpx nao levanta excecao para 4xx/5xx - deve passar direto."""
        client = FakeAsyncClient(responses=[_response(status_code, json={"status": status_code})])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        status, _, _ = await internal_api.forward("GET", "/api/resource")
        assert status == status_code

    async def test_post_define_content_type(self, monkeypatch):
        client = FakeAsyncClient(responses=[_response(200, json={})])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        await internal_api.forward("POST", "/api/resource", body=b"{}", content_type="application/json")

        assert client.calls[0]["headers"]["Content-Type"] == "application/json"

    async def test_query_string_e_anexada_na_url(self, monkeypatch):
        client = FakeAsyncClient(responses=[_response(200, json=[])])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        await internal_api.forward("GET", "/conglomerados/123/subgrupos", query="filter=active&sort=name")

        assert client.calls[0]["url"] == f"{BASE_URL}/conglomerados/123/subgrupos?filter=active&sort=name"

    async def test_extra_headers_repassados_em_get(self, monkeypatch):
        """Regressão: forward_get original não aceitava extra_headers (assimetria com POST)."""
        client = FakeAsyncClient(responses=[_response(200, json={})])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        await internal_api.forward("GET", "/api/resource", extra_headers={"x-racf": "user123"})

        assert client.calls[0]["headers"]["x-racf"] == "user123"

    async def test_authorization_header_e_anexado(self, monkeypatch):
        client = FakeAsyncClient(responses=[_response(200, json={})])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        await internal_api.forward("GET", "/api/resource")

        assert client.calls[0]["headers"]["Authorization"] == "Bearer test-token"


class TestForwardErroDeRede:
    async def test_retorna_502_com_json_valido(self, monkeypatch):
        client = FakeAsyncClient(exception=httpx.ConnectError("Connection refused"))
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        status, body, content_type = await internal_api.forward("POST", "/faturamento/123", body=b"x")

        assert status == 502
        assert content_type == "application/json"
        parsed = json.loads(body)  # nao deve estourar - corpo e sempre JSON valido
        assert parsed["erro"] == "BFF nao alcancou a API interna"
        assert "duracao_ms" in parsed


class TestForwardErroOAuth2:
    async def test_retorna_502_quando_token_falha(self, monkeypatch, _auth_ok):
        _auth_ok.side_effect = RuntimeError("Token generation failed")

        status, body, content_type = await internal_api.forward("POST", "/faturamento/123", body=b"x")

        assert status == 502
        assert content_type == "application/json"
        parsed = json.loads(body)
        assert "autenticacao" in parsed["erro"]

    async def test_json_de_erro_e_valido_mesmo_com_aspas_na_mensagem(self, monkeypatch, _auth_ok):
        """Regressão: o corpo de erro era montado por f-string manual e uma aspas na
        mensagem de exceção quebrava o JSON devolvido ao cliente."""
        _auth_ok.side_effect = RuntimeError('falha ao validar "client_secret" no servidor')

        status, body, _ = await internal_api.forward("GET", "/faturamento/123")

        assert status == 502
        parsed = json.loads(body)  # nao deve estourar json.JSONDecodeError
        assert "client_secret" in parsed["detalhes"]

    async def test_nao_chega_a_fazer_a_requisicao_http(self, monkeypatch, _auth_ok):
        _auth_ok.side_effect = RuntimeError("Token expired")
        client = FakeAsyncClient(responses=[])
        patch_get_client(monkeypatch, "app.adapters.internal_api", client)

        await internal_api.forward("GET", "/faturamento/123")

        assert client.calls == []

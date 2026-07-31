"""Testes para o módulo de rotas (routes.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_parametros
from app.api.routes import _CONTENT_TYPE_JSON, _EXCLUDED_HEADERS, _filter_headers, router


@pytest.fixture
def app():
    app_instance = FastAPI()
    app_instance.include_router(router, prefix="/api")
    yield app_instance
    app_instance.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestFilterHeaders:
    def test_filtra_host(self):
        result = _filter_headers({"host": "example.com", "authorization": "Bearer token"})
        assert "host" not in result
        assert "authorization" in result

    def test_filtra_content_length(self):
        result = _filter_headers({"content-length": "100", "accept": "application/json"})
        assert "content-length" not in result
        assert "accept" in result

    def test_filtra_connection(self):
        result = _filter_headers({"connection": "keep-alive", "user-agent": "test"})
        assert "connection" not in result
        assert "user-agent" in result

    def test_filtra_transfer_encoding(self):
        result = _filter_headers({"transfer-encoding": "chunked", "content-type": "text/plain"})
        assert "transfer-encoding" not in result
        assert "content-type" in result

    def test_preserva_headers_validos(self):
        headers = {
            "authorization": "Bearer token",
            "content-type": "application/json",
            "x-custom-header": "value",
        }
        assert _filter_headers(headers) == headers

    def test_case_insensitive(self):
        result = _filter_headers({"HOST": "example.com", "Content-Length": "100"})
        assert "HOST" not in result
        assert "Content-Length" not in result

    def test_vazio(self):
        assert _filter_headers({}) == {}

    def test_proxy_headers(self):
        headers = {
            "proxy-authenticate": "Basic",
            "proxy-authorization": "Bearer token",
            "authorization": "Bearer user-token",
        }
        result = _filter_headers(headers)
        assert "proxy-authenticate" not in result
        assert "proxy-authorization" not in result
        assert "authorization" in result

    def test_upgrade_headers(self):
        headers = {"upgrade": "websocket", "te": "trailers", "trailer": "x-checksum"}
        result = _filter_headers(headers)
        assert result == {}


class TestForwardSalvar:
    """POST /faturamento/{documento}."""

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_retorna_200_ok(self, mock_forward, client):
        mock_forward.return_value = (200, '{"ok": true}', "application/json")
        response = client.post("/api/faturamento/12345678901", json={"dados": "test"})
        assert response.status_code == 200

    def test_documento_curto_falha_validacao(self, client):
        response = client.post("/api/faturamento/1234567890", json={"dados": "test"})
        assert response.status_code == 422

    def test_documento_longo_falha_validacao(self, client):
        response = client.post("/api/faturamento/123456789012345678901", json={"dados": "test"})
        assert response.status_code == 422

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_status_code_da_api_interna(self, mock_forward, client):
        mock_forward.return_value = (201, '{"id": 123}', "application/json")
        response = client.post("/api/faturamento/12345678901", json={"dados": "test"})
        assert response.status_code == 201

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_body_da_api_interna(self, mock_forward, client):
        mock_forward.return_value = (200, '{"id": 123, "status": "success"}', "application/json")
        response = client.post("/api/faturamento/12345678901", json={"dados": "test"})
        assert response.json() == {"id": 123, "status": "success"}

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_content_type(self, mock_forward, client):
        mock_forward.return_value = (200, "<xml></xml>", "application/xml")
        response = client.post("/api/faturamento/12345678901", json={"dados": "test"})
        assert response.headers.get("content-type") == "application/xml"

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_fallback_content_type_quando_none(self, mock_forward, client):
        mock_forward.return_value = (200, "{}", None)
        response = client.post("/api/faturamento/12345678901", json={"dados": "test"})
        assert response.headers.get("content-type") == _CONTENT_TYPE_JSON

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_repassa_headers_filtrados(self, mock_forward, client):
        mock_forward.return_value = (200, "{}", "application/json")
        client.post(
            "/api/faturamento/12345678901",
            json={"dados": "test"},
            headers={"x-racf": "user123", "connection": "keep-alive"},
        )
        _, kwargs = mock_forward.call_args
        headers = kwargs["extra_headers"]
        assert headers.get("x-racf") == "user123"
        assert "connection" not in headers

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_trata_excecao(self, mock_forward, client):
        mock_forward.side_effect = RuntimeError("Connection failed")
        response = client.post("/api/faturamento/12345678901", json={"dados": "test"})
        assert response.status_code == 500


class TestForwardBuscar:
    """GET /faturamento/{documento}."""

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_retorna_200_ok(self, mock_forward, client):
        mock_forward.return_value = (200, '{"dados": "value"}', "application/json")
        response = client.get("/api/faturamento/12345678901")
        assert response.status_code == 200

    def test_documento_curto_falha_validacao(self, client):
        assert client.get("/api/faturamento/123").status_code == 422

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_status_code_da_api_interna(self, mock_forward, client):
        mock_forward.return_value = (404, '{"error": "not found"}', "application/json")
        response = client.get("/api/faturamento/12345678901")
        assert response.status_code == 404

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_repassa_query_params(self, mock_forward, client):
        mock_forward.return_value = (200, "{}", "application/json")
        client.get("/api/faturamento/12345678901?filtro=ativo")
        _, kwargs = mock_forward.call_args
        assert kwargs["query"] == "filtro=ativo"

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_trata_excecao(self, mock_forward, client):
        mock_forward.side_effect = TimeoutError("Request timeout")
        response = client.get("/api/faturamento/12345678901")
        assert response.status_code == 500


class TestForwardSubgrupos:
    """GET /conglomerados/{documento}/subgrupos."""

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_retorna_200_ok(self, mock_forward, client):
        mock_forward.return_value = (200, "[]", "application/json")
        response = client.get("/api/conglomerados/12345678901/subgrupos")
        assert response.status_code == 200

    def test_documento_curto_falha_validacao(self, client):
        assert client.get("/api/conglomerados/123/subgrupos").status_code == 422

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_body_array(self, mock_forward, client):
        expected = '[{"id": 1, "nome": "Subgrupo A"}]'
        mock_forward.return_value = (200, expected, "application/json")
        response = client.get("/api/conglomerados/12345678901/subgrupos")
        assert response.json() == [{"id": 1, "nome": "Subgrupo A"}]

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_trata_excecao(self, mock_forward, client):
        mock_forward.side_effect = ConnectionError("API unavailable")
        response = client.get("/api/conglomerados/12345678901/subgrupos")
        assert response.status_code == 500


class TestCatalogo:
    """GET /catalogo - não faz forward, consome ParametrosCatalogo direto."""

    @pytest.fixture(autouse=True)
    def _override_parametros(self, app):
        self.fake = MagicMock()
        self.fake.catalogo.return_value = {"faixas": ["0-100k"], "moedas": ["BRL"]}
        app.dependency_overrides[get_parametros] = lambda: self.fake

    def test_retorna_200_ok(self, client):
        assert client.get("/api/catalogo").status_code == 200

    def test_retorna_faixas_e_moedas(self, client):
        assert client.get("/api/catalogo").json() == {"faixas": ["0-100k"], "moedas": ["BRL"]}

    def test_trata_excecao(self, client):
        self.fake.catalogo.side_effect = RuntimeError("QuickConfig down")
        assert client.get("/api/catalogo").status_code == 500


class TestRouter:
    def test_router_nao_vazio(self):
        assert len(router.routes) > 0

    @pytest.mark.parametrize("path", [
        "/faturamento/{documento}",
        "/conglomerados/{documento}/subgrupos",
        "/catalogo",
    ])
    def test_rota_registrada(self, path):
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert path in paths


class TestConstantes:
    def test_excluded_headers_contem_headers_necessarios(self):
        assert {"host", "content-length", "connection", "transfer-encoding"} <= _EXCLUDED_HEADERS

    def test_content_type_json_correto(self):
        assert _CONTENT_TYPE_JSON == "application/json"

    def test_excluded_headers_e_frozenset(self):
        assert isinstance(_EXCLUDED_HEADERS, frozenset)

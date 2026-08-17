"""Testes para o módulo de rotas (routes.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_parametros
from app.api.routes import _CONTENT_TYPE_JSON, _montar_headers_downstream, router


@pytest.fixture
def app():
    app_instance = FastAPI()
    app_instance.include_router(router, prefix="/api")
    yield app_instance
    app_instance.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


class _FakeRequest:
    """Stub mínimo — só o que `_montar_headers_downstream` usa (`request.headers.get`)."""

    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


class TestMontarHeadersDownstream:
    """Headers curados repassados pra API interna — mesmo conjunto em GET e POST."""

    def test_sempre_inclui_correlation_id_gerado_novo_a_cada_chamada(self):
        h1 = _montar_headers_downstream(_FakeRequest())
        h2 = _montar_headers_downstream(_FakeRequest())
        assert "x-itau-correlationid" in h1
        assert h1["x-itau-correlationid"] != h2["x-itau-correlationid"]

    def test_apikey_vem_da_config_do_bff(self, monkeypatch):
        monkeypatch.setattr("app.api.routes.settings.itau_api_key", "chave-teste")
        headers = _montar_headers_downstream(_FakeRequest())
        assert headers["x-itau-apikey"] == "chave-teste"

    def test_repassa_x_racf_se_presente(self):
        headers = _montar_headers_downstream(_FakeRequest({"x-racf": "user123"}))
        assert headers["x-racf"] == "user123"

    def test_omite_x_racf_se_ausente(self):
        headers = _montar_headers_downstream(_FakeRequest({}))
        assert "x-racf" not in headers

    def test_ignora_headers_hop_by_hop_e_nao_confia_em_apikey_do_caller(self, monkeypatch):
        """Só x-racf é repassado do caller — apikey/correlation-id são sempre do BFF,
        nunca aceitos da requisição original (o caller não deveria conseguir spoofar)."""
        monkeypatch.setattr("app.api.routes.settings.itau_api_key", "chave-real")
        headers = _montar_headers_downstream(
            _FakeRequest({
                "x-racf": "user123",
                "connection": "keep-alive",
                "x-itau-apikey": "spoofed",
                "x-itau-correlationid": "spoofed-id",
            })
        )
        assert "connection" not in headers
        assert headers["x-itau-apikey"] == "chave-real"
        assert headers["x-itau-correlationid"] != "spoofed-id"


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
    def test_repassa_x_racf_apikey_e_correlation_id_no_get(self, mock_forward, client):
        """GET também precisa repassar x-racf/x-itau-apikey/x-itau-correlationid pra API
        interna — antes dessa rota nenhum header ia junto em GET, só em POST."""
        mock_forward.return_value = (200, "{}", "application/json")
        client.get("/api/faturamento/12345678901", headers={"x-racf": "user123"})
        _, kwargs = mock_forward.call_args
        headers = kwargs["extra_headers"]
        assert headers.get("x-racf") == "user123"
        assert "x-itau-apikey" in headers
        assert "x-itau-correlationid" in headers

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


class TestForwardGruposEconomicos:
    """GET /grupos-economicos?documento= (autocomplete "like")."""

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_retorna_200_ok(self, mock_forward, client):
        mock_forward.return_value = (200, '{"grupos": []}', "application/json")
        response = client.get("/api/grupos-economicos?documento=9000")
        assert response.status_code == 200

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_repassa_query_documento(self, mock_forward, client):
        mock_forward.return_value = (200, '{"grupos": []}', "application/json")
        client.get("/api/grupos-economicos?documento=9000")
        _, kwargs = mock_forward.call_args
        assert kwargs["query"] == "documento=9000"

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_body_da_api_interna(self, mock_forward, client):
        expected = '{"grupos": [{"nomeGrupoEconomico": "X", "conglomeradoDoc": "900001000", "subgrupos": []}]}'
        mock_forward.return_value = (200, expected, "application/json")
        response = client.get("/api/grupos-economicos?documento=9000")
        assert response.json()["grupos"][0]["conglomeradoDoc"] == "900001000"

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_preserva_status_code_da_api_interna(self, mock_forward, client):
        mock_forward.return_value = (422, '{"erro": "documento invalido"}', "application/json")
        response = client.get("/api/grupos-economicos?documento=abc")
        assert response.status_code == 422

    @patch("app.adapters.internal_api.forward", new_callable=AsyncMock)
    def test_trata_excecao(self, mock_forward, client):
        mock_forward.side_effect = ConnectionError("API unavailable")
        response = client.get("/api/grupos-economicos?documento=9000")
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
        "/grupos-economicos",
        "/catalogo",
    ])
    def test_rota_registrada(self, path):
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert path in paths


class TestConstantes:
    def test_content_type_json_correto(self):
        assert _CONTENT_TYPE_JSON == "application/json"

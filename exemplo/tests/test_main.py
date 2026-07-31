"""Testes para app.main - usa a app real (sem stubs em sys.modules).

O conftest.py já garante que `Settings()` e o import de `manager` funcionam
fora da rede interna, então a app inteira (routes -> internal_api/parametros)
pode ser importada normalmente aqui.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from mangum import Mangum

import app.main as main_mod


@pytest.fixture
def app_real():
    return main_mod.app


@pytest.fixture
def client(app_real):
    return TestClient(app_real, raise_server_exceptions=False)


class TestConstantes:
    def test_prefixo_api(self):
        assert main_mod.PREFIXO_API == "/api-irb-cra-faturamento-bff/v1"

    def test_metodos_cors(self):
        assert main_mod.METODOS_CORS == ["GET", "POST", "OPTIONS"]

    def test_cabecalhos_cors(self):
        assert main_mod.CABECALHOS_CORS == ["Authorization", "Content-Type"]


class TestCriarApp:
    def test_retorna_instancia_fastapi(self, app_real):
        assert isinstance(app_real, FastAPI)

    def test_titulo_correto(self, app_real):
        assert app_real.title == "Faturamento IRB — BFF"

    def test_versao_correta(self, app_real):
        assert app_real.version == "1.0.0"

    def test_descricao_contem_bff(self, app_real):
        assert "BFF para a Lambda de Faturamento do IRB" in app_real.description


class TestHealthEndpoint:
    def test_retorna_200(self, client):
        assert client.get("/health").status_code == 200

    def test_retorna_body_correto(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_rota_registrada(self, app_real):
        paths = [getattr(r, "path", None) for r in app_real.routes]
        assert "/health" in paths

    def test_nao_aparece_no_schema(self, app_real):
        route = next(r for r in app_real.routes if getattr(r, "path", None) == "/health")
        assert route.include_in_schema is False


class TestCorsMiddleware:
    def _cors_entry(self, app_real):
        return next((m for m in app_real.user_middleware if m.cls is CORSMiddleware), None)

    def test_cors_middleware_presente(self, app_real):
        assert self._cors_entry(app_real) is not None

    def test_cors_metodos_configurados(self, app_real):
        cors = self._cors_entry(app_real)
        assert {"GET", "POST", "OPTIONS"}.issubset(set(cors.kwargs.get("allow_methods", [])))

    def test_cors_cabecalhos_configurados(self, app_real):
        cors = self._cors_entry(app_real)
        headers = cors.kwargs.get("allow_headers", [])
        assert "Authorization" in headers
        assert "Content-Type" in headers


class TestMiddlewareContexto:
    def test_adiciona_x_request_id(self, client):
        assert "x-request-id" in client.get("/health").headers

    def test_request_id_e_uuid_valido(self, client):
        rid = client.get("/health").headers["x-request-id"]
        uuid.UUID(rid)

    def test_request_ids_sao_unicos(self, client):
        r1 = client.get("/health").headers["x-request-id"]
        r2 = client.get("/health").headers["x-request-id"]
        assert r1 != r2

    def test_bind_context_recebe_http_method_e_path(self, client, monkeypatch):
        chamadas = []
        monkeypatch.setattr(main_mod, "bind_context", lambda **kw: chamadas.append(kw))

        client.get("/health")

        assert len(chamadas) == 1
        assert chamadas[0]["http_method"] == "GET"
        assert chamadas[0]["http_path"] == "/health"
        assert "request_id" in chamadas[0]

    def test_log_event_start_e_end(self, client, monkeypatch):
        eventos = []
        monkeypatch.setattr(
            main_mod, "log_event",
            lambda logger, event, **kw: eventos.append((event, kw)),
        )

        client.get("/health")

        nomes = [nome for nome, _ in eventos]
        assert "http.request.start" in nomes
        assert "http.request.end" in nomes
        end_kwargs = next(kw for nome, kw in eventos if nome == "http.request.end")
        assert end_kwargs["status_code"] == 200
        assert end_kwargs["duration_ms"] >= 0

    def test_middleware_propaga_excecao_como_500(self, app_real):
        @app_real.get("/test-erro-proposital")
        def boom():
            raise ValueError("boom")

        c = TestClient(app_real, raise_server_exceptions=False)
        assert c.get("/test-erro-proposital").status_code == 500

    def test_clear_context_chamado_mesmo_com_erro(self, app_real, monkeypatch):
        chamadas = []
        monkeypatch.setattr(main_mod, "clear_context", lambda: chamadas.append(1))

        @app_real.get("/test-finally-erro")
        def boom_finally():
            raise RuntimeError("erro finally")

        c = TestClient(app_real, raise_server_exceptions=False)
        c.get("/test-finally-erro")

        # Uma vez no inicio do middleware, outra no finally
        assert len(chamadas) >= 2


class TestHandlerMangum:
    def test_handler_existe_e_e_mangum(self):
        assert isinstance(main_mod.handler, Mangum)

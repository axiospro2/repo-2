"""Fixtures compartilhadas pelos testes da camada de API (routes/routes_buscar/main) —
sobem o app FastAPI real com as dependências (repo/NJ6/Endpoint/parâmetros) trocadas por
fakes via `app.dependency_overrides`, sem precisar de rede/DynamoDB real."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


@pytest.fixture
def api_app():
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def api_client(api_app):
    return TestClient(api_app, raise_server_exceptions=False)

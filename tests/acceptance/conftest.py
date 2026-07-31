"""TAAC — testes de aceite que fazem requisições HTTP REAIS contra a API de um ambiente
(nunca mock, nunca chama o domínio direto). Config via variáveis de ambiente, injetadas
pelo CodeBuild a partir de `tests/testspec-<ambiente>.yml` (`env.variables`/
`env.secrets-manager`):

  AMBIENTE          rótulo do ambiente ("dev"/"hml") — só usado pra travar execução em
                    produção. TAAC nunca roda em prd (ver `pytest_configure` abaixo).
  BASE_URL          URL base da API (ex.: http://localhost:8001 local; a URL real de
                    DEV/HML quando rodando via CodeBuild).
  CLIENT_ID/
  CLIENT_SECRET     credenciais M2M do ambiente (vêm de Secrets Manager via ARN no
                    testspec) — hoje as rotas do Faturamento não exigem client
                    credentials do chamador, então essas fixtures ficam disponíveis pra
                    quando (se) isso for necessário (ex.: API Gateway com client auth).
  DOCUMENTO_TESTE   documento com dado conhecido/seedado no ambiente, usado nos testes
                    de BUSCAR (default: o CNPJ da fixture local do mock).
  RACF_TESTE        RACF usado no header X-RACF dos POSTs de SALVAR.
"""

from __future__ import annotations

import os

import httpx
import pytest

_AMBIENTES_PROIBIDOS = {"prd", "prod", "production", "producao", "produção"}


def pytest_configure(config):
    ambiente = os.environ.get("AMBIENTE", "dev").strip().lower()
    if ambiente in _AMBIENTES_PROIBIDOS:
        pytest.exit(
            f"TAAC não roda em produção (AMBIENTE={ambiente!r}). Abortando a execução.",
            returncode=1,
        )


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8001").rstrip("/")


@pytest.fixture(scope="session")
def prefixo() -> str:
    return "/irb-cra-faturamento/v1"


@pytest.fixture(scope="session")
def client_id() -> str:
    return os.environ.get("CLIENT_ID", "")


@pytest.fixture(scope="session")
def client_secret() -> str:
    return os.environ.get("CLIENT_SECRET", "")


@pytest.fixture(scope="session")
def documento_teste() -> str:
    return os.environ.get("DOCUMENTO_TESTE", "050746577")


@pytest.fixture(scope="session")
def racf_teste() -> str:
    return os.environ.get("RACF_TESTE", "r-taac-teste")


@pytest.fixture
def client(base_url):
    with httpx.Client(base_url=base_url, timeout=15) as c:
        yield c

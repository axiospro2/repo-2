"""Serviço de mock para NJ6, Endpoint de Faturamento e o STS (token OAuth2).

Projeto isolado — não faz parte da aplicação real. Serve fixtures estáticas nos
mesmos paths que os adapters de `app/src/app/adapters/*.py` chamam, para permitir
rodar a BFF localmente sem acesso aos serviços reais do Itaú.

Paths espelhados (confirmar contra os adapters se algo mudar lá):
  - POST /oauth/token                                                      (auth.py / oauth2.py)
  - GET  /consulta-gruposeconomicos/v1/grupos-economicos?codigo_identificacao_pessoa=  (nj6.py)
  - GET  /gestaobalanco/v1/spreads-faturamento?documento=&valido=&page=&size=  (endpoint.py)

Não mocka parâmetros (faixas/moedas/limite de divergência) — isso vem do QuickConfig
(lib interna `manager`), não é HTTP. Local, sem `QUICKCONFIG_CLUSTER_MEMBERS`, o
adapter (`ParametrosClient`/`ParametrosCatalogo`) cai direto no fallback hardcoded —
ver `app/src/app/adapters/parametros.py` e `dev-stubs/manager/` (stub de import).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request

FIXTURES = Path(__file__).parent / "fixtures"

app = FastAPI(title="mocks-faturamento-bff")


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"status": "ok"}


# ─────────── STS / OAuth2 (auth M2M) ───────────

@app.post("/oauth/token")
async def oauth_token(request: Request):
    """Mock do STS: aceita qualquer client_id/client_secret e devolve um token fake."""
    await request.body()  # consome o form-urlencoded (client_id, client_secret, grant_type)
    return {
        "access_token": f"mock-token-{uuid.uuid4().hex}",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


# ─────────── NJ6 (hierarquia conglomerado → subgrupos) ───────────

@app.get("/consulta-gruposeconomicos/v1/grupos-economicos")
def nj6(codigo_identificacao_pessoa: str = ""):
    return _load("nj6.json")


# ─────────── Endpoint de Faturamento (Gestão Balanço / spreads / CRA) ───────────

@app.get("/gestaobalanco/v1/spreads-faturamento")
def endpoint_spreads(documento: str = "", valido: str = "", page: int = 1, size: int = 100):
    """Fixture estática de 1 página só (`totalPages: 1`) - não filtra de verdade
    por `documento`/`valido`, só aceita os parâmetros reais do contrato."""
    return _load("endpoint.json")

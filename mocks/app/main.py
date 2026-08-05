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

from fastapi import FastAPI, HTTPException, Request

FIXTURES = Path(__file__).parent / "fixtures"

app = FastAPI(title="mocks-faturamento-bff")


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _sem_zeros_a_esquerda(documento: str) -> str:
    """Mesma normalização do adapter real (`endpoint.py::_sem_zeros_a_esquerda`) — o
    Endpoint guarda o documento como inteiro, sem zeros à esquerda."""
    try:
        return str(int(documento))
    except ValueError:
        return documento


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

def _achar_por_subgrupo(registros: dict, documento: str) -> dict | None:
    """`nj6.json` só indexa pela cabeça do conglomerado (chave top-level) — um documento de
    SUBGRUPO não é chave nenhuma ali, só aparece dentro de `subgrupos[].cabeca_subgrupo`.
    O NJ6 real resolve por PESSOA (matriz ou subgrupo, tanto faz) e devolve o grupo inteiro
    a que ela pertence; esta função simula isso no mock."""
    for registro in registros.values():
        for sub in registro.get("subgrupos", []):
            if sub.get("cabeca_subgrupo", {}).get("documento_raiz") == documento:
                return registro
    return None


@app.get("/consulta-gruposeconomicos/v1/grupos-economicos")
def nj6(codigo_identificacao_pessoa: str = ""):
    """`nj6.json` é um dict {documento: registro}. Mesmo endpoint serve os dois usos do
    adapter (`get_por_documento` e `buscar_grupos`, ver `adapters/nj6.py`):
      - documento EXATO da cabeça -> 1 resultado só (`data` com 1 item), igual o real.
      - documento EXATO de um SUBGRUPO -> resolve pelo grupo a que ele pertence
        (`_achar_por_subgrupo`) — sem isso, buscar por um subgrupo isolado sempre dava 404.
      - documento PARCIAL ("like") -> todos os registros cujo documento (cabeça) começa com
        o termo, simulando a busca "like" do NJ6 real (usada pelo autocomplete do front).
    404 quando não bate nada — ver docs/CASOS_TESTE_MOCK.md pra lista dos documentos
    disponíveis."""
    registros = _load("nj6.json")

    exato = registros.get(codigo_identificacao_pessoa) or _achar_por_subgrupo(
        registros, codigo_identificacao_pessoa
    )
    if exato is not None:
        return {"data": [exato]}

    like = [
        registro
        for doc, registro in registros.items()
        if codigo_identificacao_pessoa and doc.startswith(codigo_identificacao_pessoa)
    ]
    if not like:
        raise HTTPException(status_code=404, detail="Conglomerado não encontrado (mock).")
    return {"data": like}


# ─────────── Endpoint de Faturamento (Gestão Balanço / spreads / CRA) ───────────

@app.get("/gestaobalanco/v1/spreads-faturamento")
def endpoint_spreads(documento: str = "", valido: str = "", page: int = 1, size: int = 100):
    """`endpoint.json` é um dict {documento_sem_zeros: [análises]} — filtra pelo `documento`
    buscado (normalizado sem zeros à esquerda, igual o adapter real faz antes de chamar).
    Sempre 1 página só (`totalPages: 1`); documento sem análise -> lista vazia (não 404 —
    o adapter real trata "nada encontrado" como lista vazia, não erro)."""
    registros = _load("endpoint.json")
    spreads = registros.get(_sem_zeros_a_esquerda(documento), []) if documento else []
    return {
        "data": spreads,
        "page": 1,
        "size": size,
        "totalElements": len(spreads),
        "totalPages": 1,
    }

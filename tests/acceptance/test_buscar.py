"""TAAC — BUSCAR: GET real contra a API do ambiente configurado (nunca mock)."""

from __future__ import annotations


def test_health_check_da_api_esta_no_ar(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_buscar_faturamento_de_documento_existente_retorna_200(client, prefixo, documento_teste):
    resp = client.get(f"{prefixo}/faturamento/{documento_teste}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for campo in ("conglomeradoDoc", "marcadores", "origemDados"):
        assert campo in body


def test_buscar_subgrupos_de_documento_existente_retorna_200(client, prefixo, documento_teste):
    resp = client.get(f"{prefixo}/conglomerados/{documento_teste}/subgrupos")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for campo in ("nomeGrupoEconomico", "subgrupos"):
        assert campo in body


def test_buscar_faturamento_documento_invalido_falha_com_422(client, prefixo):
    resp = client.get(f"{prefixo}/faturamento/abc")
    assert resp.status_code == 422

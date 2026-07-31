"""TAAC — SALVAR: POST real contra a API do ambiente configurado (nunca mock)."""

from __future__ import annotations

import random


def _novo_documento_teste() -> str:
    """9 dígitos aleatórios (CGI, aceito pelo DOCUMENTO_PATTERN) — evita colidir com dado
    real já existente no ambiente."""
    return "".join(str(random.randint(0, 9)) for _ in range(9))


def _post_faturamento(client, prefixo, racf_teste, documento, corpo):
    return client.post(
        f"{prefixo}/faturamento/{documento}", json=corpo, headers={"X-RACF": racf_teste}
    )


def test_salvar_valor_dentro_de_faixa_conhecida_retorna_sucesso(client, prefixo, racf_teste):
    documento = _novo_documento_teste()
    corpo = {
        "conglomeradoDoc": documento,
        "nomeResponsavel": "TAAC",
        "marcadores": [
            {
                "subgrupoDoc": documento,
                "nome": "TAAC",
                # "500000" bate com o fallback hardcoded do adapter (FAIXA_1: 360 mil a
                # 4,8 MM) — é o que roda local, sem cluster QuickConfig real. Ajuste pro
                # catálogo real do QuickConfig ao rodar contra DEV/HML de verdade.
                "atual": {"valor": "500000", "moeda": "BRL", "unidade": "unitario"},
            }
        ],
    }
    resp = _post_faturamento(client, prefixo, racf_teste, documento, corpo)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["conglomeradoDoc"] == documento
    assert body["marcadores"][0]["atual"]["nomeResponsavel"] == "TAAC"


def test_salvar_sem_nenhum_marcador_falha_com_422(client, prefixo, racf_teste):
    documento = _novo_documento_teste()
    corpo = {"conglomeradoDoc": documento, "marcadores": []}
    resp = _post_faturamento(client, prefixo, racf_teste, documento, corpo)
    assert resp.status_code == 422


def test_salvar_documento_invalido_falha_com_422(client, prefixo, racf_teste):
    corpo = {"conglomeradoDoc": "abc", "marcadores": []}
    resp = _post_faturamento(client, prefixo, racf_teste, "abc", corpo)
    assert resp.status_code == 422


def test_salvar_valor_fora_de_qualquer_faixa_falha_com_422(client, prefixo, racf_teste):
    documento = _novo_documento_teste()
    corpo = {
        "conglomeradoDoc": documento,
        "marcadores": [
            {
                "subgrupoDoc": documento,
                "nome": "TAAC",
                "atual": {"valor": "-1", "moeda": "BRL", "unidade": "unitario"},
            }
        ],
    }
    resp = _post_faturamento(client, prefixo, racf_teste, documento, corpo)
    assert resp.status_code == 422

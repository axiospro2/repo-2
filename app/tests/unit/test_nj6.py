import json

import pytest
import urllib3

from app.adapters.nj6 import HttpNJ6, _map_conglomerado
from app.core.retry import ErroServidorIntegracao
from app.domain.errors import NaoEncontrado
from tests.http_fakes import FakePool, FakeResponse, FakeTokenProvider

RAW_ENVELOPADO = {
    "data": [{
        "nome_grupo_economico": "COSAN S A",
        "cabeca_grupo": {"documento_raiz": "050746577"},
        "subgrupos": [{
            "nome_subgrupo": "OUTROS",
            "codigo_grupo_cliente_atacado": 0,
            "cabeca_subgrupo": {"documento_raiz": "050746577"},
            "participantes": [{
                "pessoa": {
                    "codigo_identificacao_pessoa": "abc-123",
                    "documento_raiz": "050746577",
                    "codigo_tipo_pessoa": "J",
                    "indicador_estrangeiro": 0,
                }
            }],
        }],
    }]
}

RAW_CRU = RAW_ENVELOPADO["data"][0]


def _nj6() -> HttpNJ6:
    return HttpNJ6(base_url="http://mock/", token=FakeTokenProvider())


def _patch_pool(monkeypatch, pool: FakePool) -> None:
    monkeypatch.setattr("app.adapters.nj6.get_pool", lambda *a, **k: pool)


# ─────────── _map_conglomerado ───────────


def test_map_conglomerado_desembrulha_envelope_data():
    cong = _map_conglomerado(RAW_ENVELOPADO)
    assert cong.nome_grupo_economico == "COSAN S A"
    assert cong.cabeca_documento_raiz == "050746577"
    assert len(cong.subgrupos) == 1
    assert cong.subgrupos[0].nome_subgrupo == "OUTROS"
    assert cong.subgrupos[0].participantes[0].codigo_identificacao_pessoa == "abc-123"


def test_map_conglomerado_aceita_estrutura_crua_sem_envelope():
    cong = _map_conglomerado(RAW_CRU)
    assert cong.nome_grupo_economico == "COSAN S A"


def test_map_conglomerado_sem_subgrupos():
    raw = {"nome_grupo_economico": "X", "cabeca_grupo": {"documento_raiz": "123"}}
    cong = _map_conglomerado(raw)
    assert cong.subgrupos == []


def test_map_conglomerado_erro_por_subgrupo_malformado_propaga():
    raw = {
        "nome_grupo_economico": "X",
        "cabeca_grupo": {"documento_raiz": "123"},
        "subgrupos": [{"nome_subgrupo": "SEM_CABECA"}],  # falta cabeca_subgrupo
    }
    with pytest.raises(KeyError):
        _map_conglomerado(raw)


def test_map_conglomerado_erro_fatal_sem_nome_grupo_propaga():
    with pytest.raises(KeyError):
        _map_conglomerado({"cabeca_grupo": {"documento_raiz": "123"}})


# ─────────── HttpNJ6.get_por_documento ───────────


def test_get_por_documento_sucesso(monkeypatch):
    pool = FakePool([FakeResponse(200, json.dumps(RAW_ENVELOPADO).encode("utf-8"))])
    _patch_pool(monkeypatch, pool)

    cong = _nj6().get_por_documento("050746577")
    assert cong.nome_grupo_economico == "COSAN S A"
    assert "codigo_identificacao_pessoa=050746577" in pool.chamadas[0]["url"]


def test_get_por_documento_404_levanta_nao_encontrado(monkeypatch):
    pool = FakePool([FakeResponse(404, b"{}")])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(NaoEncontrado):
        _nj6().get_por_documento("999999999")


def test_get_por_documento_4xx_nao_retentado(monkeypatch):
    pool = FakePool([FakeResponse(400, b"erro cliente")])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError):
        _nj6().get_por_documento("999999999")
    assert len(pool.chamadas) == 1


def test_get_por_documento_5xx_esgota_retry(monkeypatch):
    pool = FakePool([FakeResponse(500, b"erro")] * 3)
    _patch_pool(monkeypatch, pool)

    with pytest.raises(ErroServidorIntegracao):
        _nj6().get_por_documento("999999999")
    assert len(pool.chamadas) == 3


def test_get_por_documento_erro_rede_retentado_depois_sucesso(monkeypatch):
    pool = FakePool([
        urllib3.exceptions.HTTPError("timeout simulado"),
        FakeResponse(200, json.dumps(RAW_ENVELOPADO).encode("utf-8")),
    ])
    _patch_pool(monkeypatch, pool)

    cong = _nj6().get_por_documento("050746577")
    assert cong.nome_grupo_economico == "COSAN S A"
    assert len(pool.chamadas) == 2


def test_get_por_documento_json_invalido_propaga(monkeypatch):
    pool = FakePool([FakeResponse(200, b"nao e json{")])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(json.JSONDecodeError):
        _nj6().get_por_documento("050746577")


def test_get_por_documento_erro_de_mapeamento_propaga(monkeypatch):
    raw_quebrado = {"cabeca_grupo": {"documento_raiz": "123"}}  # falta nome_grupo_economico
    pool = FakePool([FakeResponse(200, json.dumps(raw_quebrado).encode("utf-8"))])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(KeyError):
        _nj6().get_por_documento("123")

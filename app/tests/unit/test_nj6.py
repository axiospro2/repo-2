import json

import pytest
import urllib3

from app.adapters.nj6 import HttpNJ6, _map_conglomerado, _map_conglomerados_lista
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
    assert "documento=050746577" in pool.chamadas[0]["url"]
    assert "codigo_tipo_pessoa=J" in pool.chamadas[0]["url"]
    assert "indicador_estrangeiro=0" in pool.chamadas[0]["url"]


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


def test_get_por_documento_item_malformado_vira_nao_encontrado(monkeypatch):
    """`get_por_documento` reusa `_map_conglomerados_lista` (mesmo parser de `buscar_grupos`),
    que engole erro de mapeamento por item (loga e segue) — se o único item da lista falhar
    ao mapear, sobra lista vazia, que vira NaoEncontrado (não KeyError)."""
    raw_quebrado = {
        "data": [{"cabeca_grupo": {"documento_raiz": "123"}}]  # falta nome_grupo_economico
    }
    pool = FakePool([FakeResponse(200, json.dumps(raw_quebrado).encode("utf-8"))])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(NaoEncontrado):
        _nj6().get_por_documento("123")


# ─────────── _map_conglomerados_lista (busca exata e "like") ───────────

RAW_LISTA_LIKE = {
    "data": [
        {
            "nome_grupo_economico": "PESSOA 1 LTDA",
            "cabeca_grupo": {"documento_raiz": "059274355"},
            "subgrupos": [
                {
                    "nome_subgrupo": "PESSOA 1 LTDA",
                    "cabeca_subgrupo": {"documento_raiz": "059274355"},
                    "participantes": [],
                },
                {
                    "nome_subgrupo": "OUTROS",
                    "cabeca_subgrupo": {"documento_raiz": "050746577"},
                    "participantes": [],
                },
            ],
        },
        # Pessoa física solta, sem grupo econômico (sem cabeca_grupo) — não deve virar Conglomerado.
        {"pessoa": {"codigo_identificacao_pessoa": "abc", "documento_raiz": "044252269"}},
        {
            "nome_grupo_economico": "VICTOR HENRIQUE MOURA ROCHA",
            "cabeca_grupo": {"documento_raiz": "053577744"},
            "subgrupos": [{
                "nome_subgrupo": "OUTROS",
                "cabeca_subgrupo": {"documento_raiz": "053577744"},
                "participantes": [],
            }],
        },
    ]
}


def test_map_conglomerados_lista_mapeia_varios_grupos_ignorando_pessoa_solta():
    grupos = _map_conglomerados_lista(RAW_LISTA_LIKE)
    assert len(grupos) == 2
    assert grupos[0].nome_grupo_economico == "PESSOA 1 LTDA"
    assert grupos[0].cabeca_documento_raiz == "059274355"
    assert [s.nome_subgrupo for s in grupos[0].subgrupos] == ["PESSOA 1 LTDA", "OUTROS"]
    assert grupos[1].nome_grupo_economico == "VICTOR HENRIQUE MOURA ROCHA"


def test_map_conglomerados_lista_sem_data_retorna_vazio():
    assert _map_conglomerados_lista({}) == []


def test_map_conglomerados_lista_item_malformado_no_meio_nao_derruba_os_demais():
    """Item quebrado NO MEIO da lista (não só no fim) — prova que o erro só descarta
    aquele item e CONTINUA pros próximos, em vez de abortar a lista inteira."""
    raw = {
        "data": [
            {"nome_grupo_economico": "OK 1", "cabeca_grupo": {"documento_raiz": "1"}},
            {"cabeca_grupo": {"documento_raiz": "2"}},  # falta nome_grupo_economico -> KeyError
            {"nome_grupo_economico": "OK 2", "cabeca_grupo": {"documento_raiz": "3"}},
        ]
    }
    grupos = _map_conglomerados_lista(raw)
    assert len(grupos) == 2
    assert grupos[0].nome_grupo_economico == "OK 1"
    assert grupos[1].nome_grupo_economico == "OK 2"


# ─────────── HttpNJ6.buscar_grupos ───────────


def test_buscar_grupos_sucesso_varios_resultados(monkeypatch):
    pool = FakePool([FakeResponse(200, json.dumps(RAW_LISTA_LIKE).encode("utf-8"))])
    _patch_pool(monkeypatch, pool)

    grupos = _nj6().buscar_grupos("05")
    assert len(grupos) == 2
    assert "documento=05" in pool.chamadas[0]["url"]


def test_buscar_grupos_404_retorna_lista_vazia(monkeypatch):
    pool = FakePool([FakeResponse(404, b"{}")])
    _patch_pool(monkeypatch, pool)

    assert _nj6().buscar_grupos("999") == []


def test_buscar_grupos_4xx_nao_retentado(monkeypatch):
    pool = FakePool([FakeResponse(400, b"erro cliente")])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(RuntimeError):
        _nj6().buscar_grupos("999")
    assert len(pool.chamadas) == 1


def test_buscar_grupos_5xx_esgota_retry(monkeypatch):
    pool = FakePool([FakeResponse(500, b"erro")] * 3)
    _patch_pool(monkeypatch, pool)

    with pytest.raises(ErroServidorIntegracao):
        _nj6().buscar_grupos("999")
    assert len(pool.chamadas) == 3

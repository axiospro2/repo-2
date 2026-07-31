import json
from datetime import date, timedelta

import pytest
import urllib3

from app.adapters.endpoint import HttpEndpoint, _extrair_spreads, _sem_zeros_a_esquerda
from app.core.retry import ErroServidorIntegracao
from tests.http_fakes import FakePool, FakeResponse, FakeTokenProvider

ASOF = "2024-06-01"


def _analise(*, codigo=1, categoria_codigo=2, valor=5_000_000, data_referencia="2024-01-01"):
    return {
        "codigo": codigo,
        "auditoria": {"possuiAuditoria": True},
        "indicadorFatorPonderado": True,  # original ⇔ indicadorFatorPonderado is True
        "indicadorVigente": {"descricao": "Ativo"},
        "situacao": {"codigo": 3},
        "categoria": {"codigo": categoria_codigo},
        "faturamento": [{"dataReferencia": data_referencia, "valor": valor}],
        "atualizacao": "2024-01-02",
    }


def _endpoint(pool: FakePool) -> HttpEndpoint:
    return HttpEndpoint(base_url="http://mock/", token=FakeTokenProvider())


def _patch_pool(monkeypatch, pool: FakePool) -> None:
    monkeypatch.setattr("app.adapters.endpoint.get_pool", lambda *a, **k: pool)


def test_sem_zeros_a_esquerda_remove_zeros():
    assert _sem_zeros_a_esquerda("050746577") == "50746577"
    assert _sem_zeros_a_esquerda("00012345678") == "12345678"


def test_sem_zeros_a_esquerda_sem_zero_nao_muda():
    assert _sem_zeros_a_esquerda("50746577") == "50746577"


def test_extrair_spreads_lista_crua():
    assert _extrair_spreads([{"a": 1}]) == [{"a": 1}]


def test_extrair_spreads_envelope_data():
    assert _extrair_spreads({"data": [{"a": 1}]}) == [{"a": 1}]


def test_extrair_spreads_envelope_spreads():
    assert _extrair_spreads({"spreads": [{"a": 1}]}) == [{"a": 1}]


def test_extrair_spreads_sem_data_nem_spreads_retorna_vazio():
    assert _extrair_spreads({"outro": "campo"}) == []


def test_buscar_sucesso_remove_zero_a_esquerda_da_url(monkeypatch):
    body = json.dumps([_analise()]).encode("utf-8")
    pool = FakePool([FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    endpoint = _endpoint(pool)
    resultado = endpoint.buscar("050746577", asof=ASOF)

    assert resultado is not None
    assert resultado.valor_faturamento == 5_000_000
    assert "documento=50746577" in pool.chamadas[0]["url"]
    assert "050746577" not in pool.chamadas[0]["url"]
    assert "valido=true" in pool.chamadas[0]["url"]
    assert "subgrupo=" not in pool.chamadas[0]["url"]  # subgrupo filtra por UUID, não CNPJ


def test_buscar_sem_candidato_elegivel_retorna_none(monkeypatch):
    pool = FakePool([FakeResponse(200, b"[]")])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)
    assert resultado is None


def test_buscar_spreads_404_retorna_lista_vazia(monkeypatch):
    pool = FakePool([FakeResponse(404, b"{}")])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)
    assert resultado is None  # eleger([]) = None


def test_buscar_spreads_4xx_nao_e_retentado_e_buscar_absorve(monkeypatch):
    pool = FakePool([FakeResponse(400, b"erro cliente")])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)
    assert resultado is None
    assert len(pool.chamadas) == 1  # 4xx não é retentado


def test_buscar_spreads_5xx_esgota_retry_e_buscar_absorve(monkeypatch):
    pool = FakePool(
        [FakeResponse(500, b"erro"), FakeResponse(500, b"erro"), FakeResponse(500, b"erro")]
    )
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)
    assert resultado is None
    assert len(pool.chamadas) == 3  # PARAMETROS_RETRIES padrão = 3


def test_buscar_spreads_5xx_propaga_erro_servidor_integracao(monkeypatch):
    pool = FakePool([FakeResponse(500, b"erro")] * 3)
    _patch_pool(monkeypatch, pool)

    endpoint = _endpoint(pool)
    with pytest.raises(ErroServidorIntegracao):
        endpoint._buscar_spreads("123456789")


def test_buscar_spreads_erro_rede_retentado_depois_sucesso(monkeypatch):
    body = json.dumps([_analise()]).encode("utf-8")
    pool = FakePool([urllib3.exceptions.HTTPError("timeout simulado"), FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool)._buscar_spreads("123456789")
    assert len(resultado) == 1
    assert len(pool.chamadas) == 2


def test_buscar_spreads_json_invalido_propaga_erro(monkeypatch):
    pool = FakePool([FakeResponse(200, b"nao e json{")])
    _patch_pool(monkeypatch, pool)

    with pytest.raises(json.JSONDecodeError):
        _endpoint(pool)._buscar_spreads("123456789")


def test_buscar_absorve_json_invalido_e_retorna_none(monkeypatch):
    pool = FakePool([FakeResponse(200, b"nao e json{")])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)
    assert resultado is None


def test_buscar_sem_asof_usa_hoje(monkeypatch):
    recente = (date.today() - timedelta(days=30)).isoformat()
    body = json.dumps([_analise(data_referencia=recente)]).encode("utf-8")
    pool = FakePool([FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789")
    assert resultado is not None


def _pagina(spreads: list[dict], pagina: int, total_paginas: int) -> bytes:
    return json.dumps({
        "data": spreads,
        "page": pagina,
        "size": 100,
        "totalElements": total_paginas * len(spreads) if spreads else 0,
        "totalPages": total_paginas,
    }).encode("utf-8")


def test_buscar_percorre_todas_as_paginas_antes_de_eleger(monkeypatch):
    # categoria 4 tem prioridade MENOR que categoria 2 (PRIORIDADE_CATEGORIA_R1 = (2,4,3,5,6));
    # a de categoria 2 está na 2ª página - se só a 1ª página fosse lida, R1 elegeria errado.
    pagina1 = _pagina([_analise(codigo=1, categoria_codigo=4, valor=1_000_000)], 1, 2)
    pagina2 = _pagina([_analise(codigo=2, categoria_codigo=2, valor=2_000_000)], 2, 2)
    pool = FakePool([FakeResponse(200, pagina1), FakeResponse(200, pagina2)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is not None
    assert resultado.valor_faturamento == 2_000_000  # categoria 2 (2ª página) venceu
    assert len(pool.chamadas) == 2
    assert "page=1" in pool.chamadas[0]["url"]
    assert "page=2" in pool.chamadas[1]["url"]


def test_buscar_para_de_paginar_quando_totalpages_e_1(monkeypatch):
    pagina1 = _pagina([_analise()], 1, 1)
    pool = FakePool([FakeResponse(200, pagina1)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is not None
    assert len(pool.chamadas) == 1  # não pediu página 2


def test_paginacao_com_totalpages_ausente_trata_como_pagina_unica(monkeypatch):
    """Envelope {"data": [...]} sem a chave "totalPages" (formato mais antigo/
    de mock) não deve entrar em loop - trata como página única."""
    body = json.dumps({"data": [_analise()]}).encode("utf-8")
    pool = FakePool([FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is not None
    assert len(pool.chamadas) == 1


def test_paginacao_com_totalpages_zero_nao_pagina(monkeypatch):
    pagina1 = _pagina([], 1, 0)
    pool = FakePool([FakeResponse(200, pagina1)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is None  # nenhum spread, nenhuma regra passa
    assert len(pool.chamadas) == 1


def test_paginacao_percorre_tres_paginas(monkeypatch):
    pagina1 = _pagina([_analise(codigo=1, categoria_codigo=4, valor=1)], 1, 3)
    pagina2 = _pagina([_analise(codigo=2, categoria_codigo=5, valor=2)], 2, 3)
    pagina3 = _pagina([_analise(codigo=3, categoria_codigo=2, valor=3)], 3, 3)
    pool = FakePool(
        [FakeResponse(200, pagina1), FakeResponse(200, pagina2), FakeResponse(200, pagina3)]
    )
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is not None
    assert resultado.valor_faturamento == 3  # categoria 2 (3ª página) tem a maior prioridade
    assert len(pool.chamadas) == 3
    assert [c["url"].split("page=")[1][0] for c in pool.chamadas] == ["1", "2", "3"]


def test_paginacao_envelope_spreads_sem_totalpages_e_pagina_unica(monkeypatch):
    body = json.dumps({"spreads": [_analise()]}).encode("utf-8")
    pool = FakePool([FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is not None
    assert len(pool.chamadas) == 1


def test_paginacao_lista_crua_e_pagina_unica(monkeypatch):
    body = json.dumps([_analise()]).encode("utf-8")
    pool = FakePool([FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is not None
    assert len(pool.chamadas) == 1


def test_page_size_e_100_na_url(monkeypatch):
    pagina1 = _pagina([_analise()], 1, 1)
    pool = FakePool([FakeResponse(200, pagina1)])
    _patch_pool(monkeypatch, pool)

    _endpoint(pool).buscar("123456789", asof=ASOF)

    assert "size=100" in pool.chamadas[0]["url"]


def test_correlation_id_e_diferente_a_cada_pagina(monkeypatch):
    pagina1 = _pagina([_analise(codigo=1, categoria_codigo=4, valor=1)], 1, 2)
    pagina2 = _pagina([_analise(codigo=2, categoria_codigo=2, valor=2)], 2, 2)
    pool = FakePool([FakeResponse(200, pagina1), FakeResponse(200, pagina2)])
    _patch_pool(monkeypatch, pool)

    _endpoint(pool).buscar("123456789", asof=ASOF)

    ids = [c["headers"]["x-itau-correlationid"] for c in pool.chamadas]
    assert len(set(ids)) == 2  # cada página com seu próprio correlation-id


def test_buscar_usa_payload_real_do_fixture_e_elege_por_r2(monkeypatch):
    """Payload EXATO de uma fixture de resposta real do Endpoint (não sintetizado
    por `_analise()`) - categoria 1 (Individual) não é elegível em R1, mas
    auditado+vigente+Aprovado(3) elege por R2."""
    fixture_real = {
        "data": [{
            "codigo": 2097,
            "nome": "Análise Anual 2024",
            "etapa": None,
            "situacao": {"codigo": 3, "descricao": "Aprovado"},
            "indicadorVigente": {"codigo": 1, "descricao": "Ativo"},
            "categoria": {"codigo": 1, "descricao": "Individual"},
            "unidade": {"codigo": "1", "descricao": "Mil", "valor": 1000},
            "subgrupo": "50746577000115",
            "conglomerado": "50746577000115",
            "moeda": {"codigo": "180300790", "descricao": "BRL"},
            "grupoEmpresa": {
                "codigo": 763,
                "nome": "OUTROS",
                "prospect": {"codigo": 1, "nome": "Cliente"},
            },
            "auditoria": {
                "codigo": 1,
                "dataCriacao": "2023-04-20T22:33:43",
                "possuiAuditoria": True,
                "entradaManual": False,
            },
            "faturamento": [{"dataReferencia": "2024-12-31", "valor": 15000000.00}],
            "atualizacao": "2024-06-15T14:30:00",
            "indicadorFatorPonderado": True,
        }],
        "page": 1,
        "size": 100,
        "totalElements": 1,
        "totalPages": 1,
    }

    pool = FakePool([FakeResponse(200, json.dumps(fixture_real).encode("utf-8"))])
    _patch_pool(monkeypatch, pool)

    endpoint = _endpoint(pool)
    resultado = endpoint.buscar("50746577000115", asof="2025-06-01")

    assert resultado is not None
    assert resultado.valor_faturamento == 15000000
    assert resultado.data_ref_balanco == "2024-12-31"
    assert resultado.id_spread == "2097"
    assert resultado.unidade == "Mil"
    assert resultado.moeda == "BRL"


def test_sem_zeros_a_esquerda_documento_todo_zeros():
    """Caso extremo: documento só com zeros - int() zera tudo, str(0) = "0"."""
    assert _sem_zeros_a_esquerda("000000000") == "0"


def test_buscar_absorve_excecao_generica_e_retorna_none(monkeypatch):
    """`buscar()` tem um `except Exception` deliberadamente amplo (R-END-002) -
    até uma exceção que não é HTTP/JSON (aqui, um `ValueError` genérico
    levantado dentro do pool) não deve derrubar a leitura."""
    pool = FakePool([ValueError("erro genérico simulado, não é HTTPError")])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof=ASOF)

    assert resultado is None


def test_buscar_usa_asof_fornecido_para_janela_de_idade(monkeypatch):
    """`asof` recebido por `buscar()` é o que vale pra idade do balanço - não
    `date.today()`. Um balanço de 2024-01-01 está dentro da janela vista de
    2024-06-01, mas fora da janela vista de 2027-01-01 (36 meses depois)."""
    body = json.dumps([_analise(data_referencia="2024-01-01")]).encode("utf-8")
    pool = FakePool([FakeResponse(200, body)])
    _patch_pool(monkeypatch, pool)

    resultado = _endpoint(pool).buscar("123456789", asof="2027-01-01")

    assert resultado is None  # fora da janela de 24 meses, vista a partir de 2027

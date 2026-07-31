from decimal import Decimal

import pytest

from app.api.schemas import (
    FaturamentoRequest,
    InfoIn,
    MarcadorIn,
    conglomerado_out,
    faturamento_out,
)
from app.domain.models import (
    Conglomerado,
    Faturamento,
    InfoFaturamento,
    MarcadorFaturamento,
    Pessoa,
    Subgrupo,
)

CDOC = "12345678000100"
SDOC = "12345678000100"


# ─────────── FaturamentoRequest.to_domain / _in_to_info ───────────


def test_to_domain_usa_conglomerado_doc_do_body_quando_presente():
    req = FaturamentoRequest(conglomeradoDoc="999", marcadores=[])
    fat = req.to_domain("111", racf="r1")
    assert fat.conglomerado_doc == "999"


def test_to_domain_usa_documento_do_path_quando_body_nao_informa():
    req = FaturamentoRequest(marcadores=[])
    fat = req.to_domain("111", racf="r1")
    assert fat.conglomerado_doc == "111"


def test_to_domain_mapeia_marcador_completo_com_racf_e_cra():
    req = FaturamentoRequest(
        nomeResponsavel="Alice Ramos Paiva",
        marcadores=[
            MarcadorIn(
                subgrupoDoc=SDOC,
                nome="Grupo",
                confirmadoDivergencia=True,
                atual=InfoIn(valor=Decimal("100"), moeda="BRL", idSpread="123"),
                faturamentoCra=InfoIn(valor=Decimal("50"), moeda="BRL"),
            )
        ],
    )
    fat = req.to_domain(CDOC, racf="r-fulano")
    m = fat.marcadores[0]
    assert m.conglomerado_doc == CDOC
    assert m.atual.racf == "r-fulano"
    assert m.atual.nome_responsavel == "Alice Ramos Paiva"
    assert m.atual.id_spread == "123"  # id_spread do marcador tem prioridade
    assert m.faturamento_cra is not None
    assert m.faturamento_cra.valor == Decimal("50")
    assert m.confirmado_divergencia is True


def test_to_domain_sem_faturamento_cra_fica_none():
    req = FaturamentoRequest(marcadores=[MarcadorIn(subgrupoDoc=SDOC)])
    fat = req.to_domain(CDOC)
    assert fat.marcadores[0].faturamento_cra is None


def test_to_domain_id_spread_cai_no_do_info_quando_marcador_nao_informa():
    req = FaturamentoRequest(
        marcadores=[MarcadorIn(subgrupoDoc=SDOC, atual=InfoIn(idSpread="do-info"))]
    )
    fat = req.to_domain(CDOC)
    assert fat.marcadores[0].atual.id_spread == "do-info"


def test_to_domain_unidade_default_milhoes_quando_ausente():
    req = FaturamentoRequest(marcadores=[MarcadorIn(subgrupoDoc=SDOC, atual=InfoIn())])
    fat = req.to_domain(CDOC)
    assert fat.marcadores[0].atual.unidade == "milhoes"


def test_to_domain_sem_nome_responsavel_fica_none():
    req = FaturamentoRequest(marcadores=[MarcadorIn(subgrupoDoc=SDOC)])
    fat = req.to_domain(CDOC)
    assert fat.marcadores[0].atual.nome_responsavel is None


# ─────────── faturamento_out ───────────


def test_faturamento_out_persistido_true_e_base():
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[
            MarcadorFaturamento(
                conglomerado_doc=CDOC,
                subgrupo_doc=SDOC,
                atual=InfoFaturamento(valor=Decimal("100"), faixa_codigo="FAIXA_1"),
            )
        ],
    )
    out = faturamento_out(fat, persistido=True)
    assert out["origemDados"] == "BASE"
    assert out["marcadores"][0]["atual"]["valor"] == "100"
    assert out["marcadores"][0]["atual"]["faixaCodigo"] == "FAIXA_1"


def test_faturamento_out_persistido_false_e_preview():
    fat = Faturamento(conglomerado_doc=CDOC, marcadores=[])
    out = faturamento_out(fat, persistido=False)
    assert out["origemDados"] == "PREVIEW"


def test_faturamento_out_sem_paginacao_no_envelope():
    fat = Faturamento(conglomerado_doc=CDOC, marcadores=[])
    out = faturamento_out(fat, persistido=True)
    assert "paginacao" not in out


def test_faturamento_out_inclui_nome_responsavel():
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[
            MarcadorFaturamento(
                conglomerado_doc=CDOC,
                subgrupo_doc=SDOC,
                atual=InfoFaturamento(nome_responsavel="Carlos Alberto Silva"),
            )
        ],
    )
    out = faturamento_out(fat, persistido=True)
    assert out["marcadores"][0]["atual"]["nomeResponsavel"] == "Carlos Alberto Silva"


def test_faturamento_out_marcador_sem_atual_nem_cra():
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[MarcadorFaturamento(conglomerado_doc=CDOC, subgrupo_doc=SDOC, atual=None)],
    )
    out = faturamento_out(fat, persistido=True)
    assert out["marcadores"][0]["atual"] is None
    assert out["marcadores"][0]["faturamentoCra"] is None


# ─────────── conglomerado_out ───────────


def test_conglomerado_out_sucesso():
    cong = Conglomerado(
        nome_grupo_economico="Grupo X",
        cabeca_documento_raiz=CDOC,
        segmento="Indústria",
        subgrupos=[
            Subgrupo(
                nome_subgrupo="Sub A",
                cabeca_documento_raiz=SDOC,
                codigo_grupo_cliente_atacado="0",
                participantes=[Pessoa(codigo_identificacao_pessoa="p1", documento_raiz=SDOC)],
            )
        ],
    )
    out = conglomerado_out(cong)
    assert out["nomeGrupoEconomico"] == "Grupo X"
    assert out["segmento"] == "Indústria"
    assert len(out["subgrupos"]) == 1
    assert out["subgrupos"][0]["participantes"][0]["documentoRaiz"] == SDOC


def test_conglomerado_out_sem_subgrupos():
    cong = Conglomerado(nome_grupo_economico="Grupo Y", cabeca_documento_raiz=CDOC)
    out = conglomerado_out(cong)
    assert out["subgrupos"] == []


def test_conglomerado_out_erro_por_subgrupo_propaga():
    cong = Conglomerado(
        nome_grupo_economico="Grupo Z",
        cabeca_documento_raiz=CDOC,
        subgrupos=[
            Subgrupo(
                nome_subgrupo="Sub Quebrado",
                cabeca_documento_raiz=SDOC,
                participantes=["nao-e-uma-pessoa"],  # falta .documento_raiz etc.
            )
        ],
    )
    with pytest.raises(AttributeError):
        conglomerado_out(cong)


def test_conglomerado_out_erro_fatal_propaga():
    class CongQuebrado:
        pass  # sem atributo `subgrupos`

    with pytest.raises(AttributeError):
        conglomerado_out(CongQuebrado())

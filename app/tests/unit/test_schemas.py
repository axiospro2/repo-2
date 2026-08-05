from decimal import Decimal

from app.api.schemas import (
    FaturamentoRequest,
    InfoIn,
    MarcadorIn,
    faturamento_out,
    grupos_out,
)
from app.domain.models import (
    Conglomerado,
    Faturamento,
    InfoFaturamento,
    MarcadorFaturamento,
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
    assert m.atual.id_spread == "123"  # id_spread do marcador tem prioridade
    assert m.faturamento_cra is not None
    assert m.faturamento_cra.valor == Decimal("50")
    assert m.confirmado_divergencia is True


def test_to_domain_mapeia_auditoria_e_valor_ativo():
    req = FaturamentoRequest(
        marcadores=[
            MarcadorIn(
                subgrupoDoc=SDOC,
                atual=InfoIn(
                    valor=Decimal("100"),
                    moeda="BRL",
                    auditoria="Deloitte",
                    valorAtivo=Decimal("50000"),
                ),
            )
        ],
    )
    fat = req.to_domain(CDOC)
    m = fat.marcadores[0]
    assert m.atual.auditoria == "Deloitte"
    assert m.atual.valor_ativo == Decimal("50000")


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


def test_faturamento_out_marcador_sem_atual_nem_cra():
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[MarcadorFaturamento(conglomerado_doc=CDOC, subgrupo_doc=SDOC, atual=None)],
    )
    out = faturamento_out(fat, persistido=True)
    assert out["marcadores"][0]["atual"] is None


def test_faturamento_out_inclui_racf_auditoria_e_valor_ativo():
    """`racf` volta na API — é o que a tela usa como coluna "Atualizado por" (não é nome)."""
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[
            MarcadorFaturamento(
                conglomerado_doc=CDOC,
                subgrupo_doc=SDOC,
                atual=InfoFaturamento(
                    racf="r123456", auditoria="KPMG", valor_ativo=Decimal("900000")
                ),
            )
        ],
    )
    out = faturamento_out(fat, persistido=True)
    atual = out["marcadores"][0]["atual"]
    assert atual["racf"] == "r123456"
    assert atual["auditoria"] == "KPMG"
    assert atual["valorAtivo"] == "900000"


# ─────────── grupos_out ───────────


def test_grupos_out_lista_vazia():
    assert grupos_out([]) == {"grupos": []}


def test_grupos_out_mapeia_cabeca_e_subgrupos_sem_participantes():
    grupo = Conglomerado(
        nome_grupo_economico="Grupo Teste",
        cabeca_documento_raiz=CDOC,
        segmento="Indústria",
        subgrupos=[Subgrupo(nome_subgrupo="OUTROS", cabeca_documento_raiz="999")],
    )
    out = grupos_out([grupo])
    assert out == {
        "grupos": [{
            "nomeGrupoEconomico": "Grupo Teste",
            "conglomeradoDoc": CDOC,
            "segmento": "Indústria",
            "subgrupos": [{"nome": "OUTROS", "documento": "999"}],
        }]
    }

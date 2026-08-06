from datetime import datetime
from decimal import Decimal

from app.domain import resolucao_marcador as resolucao
from app.domain.eleicao import ResultadoFaturamento
from app.domain.models import InfoFaturamento, MarcadorFaturamento, Nivel, Origem

CDOC = "12345678000100"
SDOC = "12345678000100"


def _hoje() -> str:
    return datetime.now().date().isoformat()


def _marcador_banco(**overrides) -> MarcadorFaturamento:
    defaults = dict(
        conglomerado_doc=CDOC,
        subgrupo_doc=SDOC,
        nivel=Nivel.CONGLOMERADO,
        origem=Origem.BASE,
        atual=InfoFaturamento(valor=Decimal("6000000"), data_ref_balanco=_hoje()),
    )
    defaults.update(overrides)
    return MarcadorFaturamento(**defaults)


def test_resolver_marcador_banco_vence_mesmo_com_endpoint_disponivel():
    """Confirmado com o PO: banco sempre vence quando tem valor - sem revalidar
    R1/R2/R3 nem idade (não temos como saber se foi auditado/original/categoria
    de um valor digitado pelo analista)."""
    salvo = _marcador_banco()
    resultado_endpoint = ResultadoFaturamento(
        valor_faturamento=Decimal("999999999"), data_ref_balanco=_hoje()
    )
    m = resolucao.resolver_marcador(
        Nivel.CONGLOMERADO, CDOC, SDOC, "Grupo", salvo, resultado_endpoint, []
    )
    assert m.origem == Origem.BASE
    assert m.atual.valor == Decimal("6000000")  # o do banco, não o do endpoint


def test_resolver_marcador_prioriza_quarentena():
    salvo = _marcador_banco(
        quarentena=True,
        atual=InfoFaturamento(valor=Decimal("999")),
        anterior=InfoFaturamento(valor=Decimal("4000000"), data_ref_balanco="2023-01-01"),
    )
    m = resolucao.resolver_marcador(Nivel.CONGLOMERADO, CDOC, SDOC, "Grupo", salvo, None, [])
    assert m.em_quarentena is True
    assert m.atual.valor == Decimal("4000000")


def test_resolver_marcador_usa_endpoint_quando_banco_ausente():
    resultado_endpoint = ResultadoFaturamento(
        valor_faturamento=Decimal("7000000"), data_ref_balanco=_hoje()
    )
    m = resolucao.resolver_marcador(
        Nivel.CONGLOMERADO, CDOC, SDOC, "Grupo", None, resultado_endpoint, []
    )
    assert m.origem == Origem.ENDPOINT
    assert m.atual.valor == Decimal("7000000")


def test_resolver_marcador_usa_endpoint_quando_banco_vazio():
    salvo = _marcador_banco(atual=InfoFaturamento())  # sem valor e sem faixa -> vazio
    resultado_endpoint = ResultadoFaturamento(
        valor_faturamento=Decimal("7000000"), data_ref_balanco=_hoje()
    )
    m = resolucao.resolver_marcador(
        Nivel.CONGLOMERADO, CDOC, SDOC, "Grupo", salvo, resultado_endpoint, []
    )
    assert m.origem == Origem.ENDPOINT


def test_resolver_marcador_manual_quando_nada_disponivel():
    m = resolucao.resolver_marcador(Nivel.CONGLOMERADO, CDOC, SDOC, "Grupo", None, None, [])
    assert m.origem == Origem.MANUAL


def test_aplicar_quarentena_sem_anterior_mantem_o_marcador():
    m = _marcador_banco(quarentena=True, anterior=None)
    resultado = resolucao.aplicar_quarentena(m)
    assert resultado is m


def test_aplicar_quarentena_com_anterior_vazio_mantem_o_marcador():
    m = _marcador_banco(quarentena=True, anterior=InfoFaturamento())  # vazio: sem valor/faixa
    resultado = resolucao.aplicar_quarentena(m)
    assert resultado is m


def test_marcador_do_endpoint_converte_unidade_mil_antes_da_faixa():
    """Endpoint devolve valor 'Mil' (ex.: 15000 -> R$ 15.000.000) - precisa escalar antes da faixa."""
    faixas = [
        {"codigo": "FAIXA_1", "descricao": "ate 4,8MM", "min": 0, "max": 4800000},
        {"codigo": "FAIXA_2", "descricao": "4,8MM a 20MM", "min": 4800000, "max": 20000000},
    ]
    res = ResultadoFaturamento(
        valor_faturamento=Decimal("15000"), data_ref_balanco=_hoje(), unidade="Mil"
    )
    m = resolucao.marcador_do_endpoint(CDOC, SDOC, Nivel.CONGLOMERADO, "Grupo", res, faixas)
    assert m.atual.valor == Decimal("15000")  # persiste o valor bruto do endpoint
    assert m.atual.faixa_codigo == "FAIXA_2"  # 15000 * 1000 = 15.000.000


def test_marcador_do_endpoint_com_unidade_real_efetivo_nao_multiplica():
    """ "Real/Efetivo" (enum Java UnidadeEnum.REAL) é o ×1 do Endpoint - vocabulário
    diferente de "unitário" (só existe no combo manual do SALVAR), mas precisa ser
    reconhecido igual, senão cai em "unidade desconhecida" e perde a faixa."""
    faixas = [
        {"codigo": "FAIXA_1", "descricao": "ate 4,8MM", "min": 0, "max": 4800000},
        {"codigo": "FAIXA_2", "descricao": "4,8MM a 20MM", "min": 4800000, "max": 20000000},
    ]
    res = ResultadoFaturamento(
        valor_faturamento=Decimal("15000000"), data_ref_balanco=_hoje(), unidade="Real/Efetivo"
    )
    m = resolucao.marcador_do_endpoint(CDOC, SDOC, Nivel.CONGLOMERADO, "Grupo", res, faixas)
    assert m.atual.valor == Decimal("15000000")  # persiste o valor bruto do endpoint
    assert m.atual.faixa_codigo == "FAIXA_2"  # 15.000.000 * 1 = 15.000.000, sem multiplicar


def test_marcador_do_endpoint_com_unidade_desconhecida_nao_quebra_a_leitura():
    res = ResultadoFaturamento(
        valor_faturamento=Decimal("5000000"), data_ref_balanco=_hoje(), unidade="trilhoes"
    )
    m = resolucao.marcador_do_endpoint(
        CDOC,
        SDOC,
        Nivel.CONGLOMERADO,
        "Grupo",
        res,
        [{"codigo": "X", "descricao": "d", "min": 0, "max": None}],
    )
    assert m.atual.faixa_codigo is None  # não sabe classificar, mas não derruba o BUSCAR


def test_enriquecer_faixa_preenche_descricao():
    m = MarcadorFaturamento(
        conglomerado_doc=CDOC,
        subgrupo_doc=SDOC,
        atual=InfoFaturamento(faixa_codigo="X"),
    )
    resolucao.enriquecer_faixa(m, [{"codigo": "X", "descricao": "rotulo"}])
    assert m.atual.faixa_descricao == "rotulo"

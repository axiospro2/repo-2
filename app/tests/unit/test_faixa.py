from decimal import Decimal

from app.domain.faixa import (
    de_para_valor_para_faixa,
    descricao_da_faixa,
    multiplicador_unidade,
    valor_em_reais,
)

FAIXAS = [
    {"codigo": "FAIXA_1", "descricao": "R$ 360 mil a R$ 4,8 MM", "min": 360000, "max": 4800000},
    {"codigo": "FAIXA_2", "descricao": "R$ 4,8 MM a R$ 20 MM", "min": 4800000, "max": 20000000},
    {"codigo": "FAIXA_6", "descricao": "Acima de R$ 2 BI", "min": 2000000000, "max": None},
]


def test_valor_dentro_da_primeira_faixa():
    assert de_para_valor_para_faixa(Decimal("1000000"), FAIXAS) == "FAIXA_1"


def test_valor_no_limite_minimo_da_proxima_faixa_e_inclusivo():
    assert de_para_valor_para_faixa(Decimal("4800000"), FAIXAS) == "FAIXA_2"


def test_valor_no_limite_maximo_da_faixa_atual_e_exclusivo():
    assert de_para_valor_para_faixa(Decimal("4799999"), FAIXAS) == "FAIXA_1"


def test_faixa_sem_teto_aceita_qualquer_valor_acima_do_minimo():
    assert de_para_valor_para_faixa(Decimal("999999999999"), FAIXAS) == "FAIXA_6"


def test_valor_abaixo_de_todas_as_faixas_retorna_none():
    assert de_para_valor_para_faixa(Decimal("1"), FAIXAS) is None


def test_descricao_da_faixa_conhecida():
    assert descricao_da_faixa("FAIXA_1", FAIXAS) == "R$ 360 mil a R$ 4,8 MM"


def test_descricao_da_faixa_desconhecida_retorna_none():
    assert descricao_da_faixa("FAIXA_99", FAIXAS) is None


def test_descricao_sem_codigo_retorna_none():
    assert descricao_da_faixa(None, FAIXAS) is None


def test_multiplicador_unitario_e_identidade():
    """ "unitário" é quem tem multiplicador x1 - o valor já é o número de reais."""
    assert multiplicador_unidade("unitario") == Decimal(1)
    assert multiplicador_unidade("unitário") == Decimal(1)


def test_multiplicador_escala_linear_das_4_unidades_da_tela():
    """Combo real da tela: unitário / mil / milhões / bilhões - escala linear (base 10)."""
    assert multiplicador_unidade("mil") == Decimal(1_000)
    assert multiplicador_unidade("Mil") == Decimal(1_000)  # case-insensitive
    assert multiplicador_unidade("milhoes") == Decimal(1_000_000)
    assert multiplicador_unidade("milhões") == Decimal(1_000_000)
    assert multiplicador_unidade("bilhoes") == Decimal(1_000_000_000)
    assert multiplicador_unidade("bilhões") == Decimal(1_000_000_000)


def test_multiplicador_default_e_milhoes():
    assert multiplicador_unidade(None) == Decimal(1_000_000)


def test_multiplicador_unidade_desconhecida_retorna_none():
    assert multiplicador_unidade("trilhoes") is None


def test_valor_em_reais_aplica_multiplicador():
    """6.500.000 'mil' = R$ 6,5 BI - mesma conta observada na tela real do CRA."""
    assert valor_em_reais(Decimal("100"), "unitario") == Decimal("100")
    assert valor_em_reais(Decimal("6500000"), "mil") == Decimal("6500000000")
    assert valor_em_reais(Decimal("5"), "milhoes") == Decimal("5000000")
    assert valor_em_reais(Decimal("2"), "bilhoes") == Decimal("2000000000")


def test_valor_em_reais_unidade_desconhecida_retorna_none():
    assert valor_em_reais(Decimal("100"), "trilhoes") is None

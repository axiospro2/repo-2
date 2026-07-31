from decimal import Decimal

from app.domain import divergencia
from app.domain.models import InfoFaturamento, MarcadorFaturamento


def _marcador(subgrupo="123", valor=None, moeda="BRL", unidade="milhoes"):
    return MarcadorFaturamento(
        conglomerado_doc="123",
        subgrupo_doc=subgrupo,
        atual=InfoFaturamento(valor=valor, moeda=moeda, unidade=unidade),
    )


def test_sem_existente_nao_gera_divergencia():
    novo = _marcador(valor=Decimal("100"))
    assert divergencia.avaliar(novo, None, 30) == []


def test_variacao_dentro_do_limite_nao_gera_divergencia():
    existente = _marcador(valor=Decimal("1000000"))
    novo = _marcador(valor=Decimal("1200000"))  # 20% de variação, limite 30%
    assert divergencia.avaliar(novo, existente, 30) == []


def test_variacao_acima_do_limite_gera_divergencia_de_valor():
    existente = _marcador(valor=Decimal("1000000"))
    novo = _marcador(valor=Decimal("2000000"))  # 100% de variação
    divs = divergencia.avaliar(novo, existente, 30)
    assert len(divs) == 1
    assert divs[0] == {
        "tipo": "VALOR",
        "subgrupoDoc": "123",
        "de": "1000000",
        "para": "2000000",
        "variacaoPercentual": "100.00",
    }


def test_troca_de_moeda_gera_divergencia():
    existente = _marcador(valor=Decimal("100"), moeda="BRL")
    novo = _marcador(valor=Decimal("100"), moeda="USD")
    divs = divergencia.avaliar(novo, existente, 30)
    assert any(d["tipo"] == "MOEDA" and d["de"] == "BRL" and d["para"] == "USD" for d in divs)


def test_troca_de_unidade_gera_divergencia():
    existente = _marcador(valor=Decimal("100"), unidade="milhoes")
    novo = _marcador(valor=Decimal("100"), unidade="milhares")
    divs = divergencia.avaliar(novo, existente, 30)
    assert any(d["tipo"] == "UNIDADE" for d in divs)


def test_varias_divergencias_simultaneas():
    existente = _marcador(valor=Decimal("1000000"), moeda="BRL", unidade="milhoes")
    novo = _marcador(valor=Decimal("5000000"), moeda="USD", unidade="milhares")
    divs = divergencia.avaliar(novo, existente, 30)
    tipos = {d["tipo"] for d in divs}
    assert tipos == {"VALOR", "MOEDA", "UNIDADE"}

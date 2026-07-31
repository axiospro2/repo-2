"""Testes de integração ligando as duas pontas: banco vazio no BUSCAR até a regra
(R1/R2/R3) que realmente elegeu o valor no Endpoint.

Diferente de `test_service_buscar.py` (que usa `FakeEndpoint`, seedado com um
`ResultadoFaturamento` já pronto, bypassando a cascata) e de `test_eleicao.py`
(que chama `eleger()` isolado, sem passar pelo fluxo BUSCAR inteiro), aqui a
análise crua entra pelo `FakeEndpointComEleicao` (que roda `eleger()` de
verdade) e sai do outro lado como um `MarcadorFaturamento` resolvido por
`service_buscar.obter_faturamento`.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.domain import service_buscar as service
from app.domain.models import InfoFaturamento, MarcadorFaturamento, Nivel, Origem
from tests.fakes import (
    FAIXAS_PADRAO,
    FakeCatalogo,
    FakeEndpointComEleicao,
    FakeNJ6,
    FakeRepositorio,
    conglomerado_simples,
)

CONGLOMERADO_DOC = "12345678000100"

# `service_buscar.obter_faturamento` não repassa `asof` pro Endpoint (usa sempre
# `date.today()`), então as datas de referência do balanço precisam ficar
# relativas a hoje - não podem ser strings fixas no passado, ou saem da janela
# de 24 meses (`IDADE_MAX_MESES`) dependendo de quando o teste rodar.
_BALANCO_RECENTE = (date.today() - timedelta(days=60)).isoformat()


def _analise(
    *,
    codigo=1,
    auditado=True,
    original=True,
    vigente=True,
    situacao_codigo=3,
    categoria_codigo=2,
    data_referencia=None,
    valor=5_000_000,
    atualizado="2024-01-02",
):
    """Análise crua no formato do Endpoint (mesma forma de `test_eleicao.py`)."""
    return {
        "codigo": codigo,
        "auditoria": {"possuiAuditoria": auditado},
        "indicadorFatorPonderado": original,  # original ⇔ indicadorFatorPonderado is True
        "indicadorVigente": {"descricao": "Ativo" if vigente else "Inativo"},
        "situacao": {"codigo": situacao_codigo},
        "categoria": {"codigo": categoria_codigo},
        "faturamento": [{"dataReferencia": data_referencia or _BALANCO_RECENTE, "valor": valor}],
        "atualizacao": atualizado,
    }


def _buscar(endpoint):
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []))
    repo = FakeRepositorio()
    catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)
    return service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)


def test_banco_vazio_endpoint_elege_por_r1_de_verdade():
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_analises(
        CONGLOMERADO_DOC,
        [
            _analise(categoria_codigo=2, valor=5_000_000)
        ],  # auditado+original+vigente+cat. prioritária
    )

    fat = _buscar(endpoint)

    m = fat.marcadores[0]
    assert m.origem == Origem.ENDPOINT
    assert m.atual.valor == Decimal("5000000")


def test_banco_vazio_endpoint_elege_por_r2_de_verdade():
    endpoint = FakeEndpointComEleicao()
    # categoria 1 (Individual) não é elegível na R1; auditado+vigente+Aprovado -> cai pra R2.
    endpoint.seed_analises(
        CONGLOMERADO_DOC,
        [_analise(categoria_codigo=1, situacao_codigo=3, valor=7_000_000)],
    )

    fat = _buscar(endpoint)

    m = fat.marcadores[0]
    assert m.origem == Origem.ENDPOINT
    assert m.atual.valor == Decimal("7000000")


def test_banco_vazio_endpoint_elege_por_r3_de_verdade():
    # não auditado (falha R1 e R2); original+vigente+Aprovado+categoria não excluída -> R3.
    # dois candidatos empatados em tudo, menos o valor - R3 desempata pelo MAIOR.
    menor = _analise(codigo=1, auditado=False, categoria_codigo=2, valor=1_000_000)
    maior = _analise(codigo=2, auditado=False, categoria_codigo=2, valor=9_000_000)
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_analises(CONGLOMERADO_DOC, [menor, maior])

    fat = _buscar(endpoint)

    m = fat.marcadores[0]
    assert m.origem == Origem.ENDPOINT
    assert m.atual.valor == Decimal("9000000")


def test_banco_vazio_nenhuma_analise_elegivel_fica_manual():
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_analises(
        CONGLOMERADO_DOC,
        [_analise(auditado=False, original=False, vigente=False)],
    )

    fat = _buscar(endpoint)

    m = fat.marcadores[0]
    assert m.origem == Origem.MANUAL
    assert m.atual.valor is None


def test_banco_com_valor_vence_mesmo_quando_endpoint_elegeria_por_r1():
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_analises(
        CONGLOMERADO_DOC,
        [_analise(categoria_codigo=2, valor=999_999_999)],  # R1 elegeria isso, se fosse chamado
    )
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []))
    repo = FakeRepositorio()
    repo.seed(
        MarcadorFaturamento(
            conglomerado_doc=CONGLOMERADO_DOC,
            subgrupo_doc=CONGLOMERADO_DOC,
            nivel=Nivel.CONGLOMERADO,
            origem=Origem.BASE,
            atual=InfoFaturamento(valor=Decimal("6000000"), data_ref_balanco="2024-01-01"),
        )
    )
    catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    m = fat.marcadores[0]
    assert m.origem == Origem.BASE
    assert m.atual.valor == Decimal(
        "6000000"
    )  # banco vence, Endpoint nem precisava ter sido chamado


def test_quarentena_ignora_candidato_do_endpoint_mesmo_que_fosse_r1():
    """Quarentena tem prioridade absoluta (R-RES-010): mesmo que o Endpoint
    tivesse uma análise perfeitamente elegível para R1, o marcador em
    quarentena usa o `anterior` e nem chega a ser resolvido pelo Endpoint."""
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_analises(
        CONGLOMERADO_DOC,
        [_analise(categoria_codigo=2, valor=999_999_999)],  # R1 elegeria isso, se fosse chamado
    )
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []))
    repo = FakeRepositorio()
    repo.seed(
        MarcadorFaturamento(
            conglomerado_doc=CONGLOMERADO_DOC,
            subgrupo_doc=CONGLOMERADO_DOC,
            nivel=Nivel.CONGLOMERADO,
            atual=InfoFaturamento(valor=Decimal("999999999")),  # suspeito, não deveria ser usado
            anterior=InfoFaturamento(valor=Decimal("4000000"), data_ref_balanco="2023-01-01"),
            quarentena=True,
        )
    )
    catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    m = fat.marcadores[0]
    assert m.em_quarentena is True
    assert m.atual.valor == Decimal("4000000")


def test_multiplos_subgrupos_cada_um_resolve_pela_sua_propria_regra():
    """Um conglomerado com 3 alvos: a matriz tem valor no banco (vence sem
    consultar o Endpoint), um subgrupo elege por R1 e outro elege por R3 -
    prova que a eleição roda de forma independente por alvo, dentro do mesmo
    GET."""
    docs = ["SUB_R1", "SUB_R3"]
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", docs))
    repo = FakeRepositorio()
    repo.seed(
        MarcadorFaturamento(
            conglomerado_doc=CONGLOMERADO_DOC,
            subgrupo_doc=CONGLOMERADO_DOC,
            nivel=Nivel.CONGLOMERADO,
            origem=Origem.BASE,
            atual=InfoFaturamento(valor=Decimal("1000000"), data_ref_balanco="2024-01-01"),
        )
    )
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_analises(
        "SUB_R1", [_analise(categoria_codigo=2, valor=2_000_000)]  # R1: cat. prioritária
    )
    endpoint.seed_analises(
        "SUB_R3",
        [_analise(auditado=False, categoria_codigo=2, valor=3_000_000)],  # não auditado -> R3
    )
    catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    por_doc = {m.subgrupo_doc: m for m in fat.marcadores}
    assert por_doc[CONGLOMERADO_DOC].origem == Origem.BASE
    assert por_doc[CONGLOMERADO_DOC].atual.valor == Decimal("1000000")
    assert por_doc["SUB_R1"].origem == Origem.ENDPOINT
    assert por_doc["SUB_R1"].atual.valor == Decimal("2000000")
    assert por_doc["SUB_R3"].origem == Origem.ENDPOINT
    assert por_doc["SUB_R3"].atual.valor == Decimal("3000000")


def test_endpoint_falha_isolada_nao_impede_outro_subgrupo_de_eleger_de_verdade():
    """Um subgrupo cujo Endpoint falha não deve impedir outro (no mesmo GET)
    de eleger normalmente pela cascata real."""
    docs = ["SUB_FALHA", "SUB_OK"]
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", docs))
    repo = FakeRepositorio()
    endpoint = FakeEndpointComEleicao()
    endpoint.seed_erro("SUB_FALHA")
    endpoint.seed_analises("SUB_OK", [_analise(categoria_codigo=2, valor=4_000_000)])
    catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    por_doc = {m.subgrupo_doc: m for m in fat.marcadores}
    assert (
        por_doc["SUB_FALHA"].origem == Origem.MANUAL
    )  # falha isolada -> MANUAL, não derruba o GET
    assert por_doc["SUB_OK"].origem == Origem.ENDPOINT
    assert por_doc["SUB_OK"].atual.valor == Decimal("4000000")


def test_conglomerado_misto_quarentena_e_eleicao_simultaneas():
    """Combina, no mesmo GET: matriz com banco normal, um subgrupo em
    quarentena e outro sem banco elegendo pelo Endpoint (R2) - cada alvo
    resolve pela sua própria regra, sem um afetar o outro."""
    docs = ["SUB_QUARENTENA", "SUB_ENDPOINT"]
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", docs))
    repo = FakeRepositorio()
    repo.seed(
        MarcadorFaturamento(
            conglomerado_doc=CONGLOMERADO_DOC,
            subgrupo_doc=CONGLOMERADO_DOC,
            nivel=Nivel.CONGLOMERADO,
            origem=Origem.BASE,
            atual=InfoFaturamento(valor=Decimal("1000000"), data_ref_balanco="2024-01-01"),
        )
    )
    repo.seed(
        MarcadorFaturamento(
            conglomerado_doc=CONGLOMERADO_DOC,
            subgrupo_doc="SUB_QUARENTENA",
            nivel=Nivel.SUBGRUPO,
            atual=InfoFaturamento(valor=Decimal("999999999")),  # suspeito
            anterior=InfoFaturamento(valor=Decimal("2000000"), data_ref_balanco="2023-01-01"),
            quarentena=True,
        )
    )
    endpoint = FakeEndpointComEleicao()
    # categoria 1 (Individual) não é elegível em R1; auditado+vigente+Aprovado -> R2.
    endpoint.seed_analises("SUB_ENDPOINT", [_analise(categoria_codigo=1, valor=3_000_000)])
    catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    por_doc = {m.subgrupo_doc: m for m in fat.marcadores}
    assert por_doc[CONGLOMERADO_DOC].origem == Origem.BASE
    assert por_doc[CONGLOMERADO_DOC].atual.valor == Decimal("1000000")
    assert por_doc["SUB_QUARENTENA"].em_quarentena is True
    assert por_doc["SUB_QUARENTENA"].atual.valor == Decimal("2000000")
    assert por_doc["SUB_ENDPOINT"].origem == Origem.ENDPOINT
    assert por_doc["SUB_ENDPOINT"].atual.valor == Decimal("3000000")

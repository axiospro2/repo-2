from datetime import datetime
from decimal import Decimal

from app.domain import service_buscar as service
from app.domain.eleicao import ResultadoFaturamento
from app.domain.models import InfoFaturamento, MarcadorFaturamento, Nivel, Origem
from tests.fakes import FakeCatalogo, FakeEndpoint, FakeNJ6, FakeRepositorio, conglomerado_simples

CONGLOMERADO_DOC = "12345678000100"


def _hoje() -> str:
    return datetime.now().date().isoformat()


def _marcador_base(doc: str, valor: Decimal, **overrides) -> MarcadorFaturamento:
    defaults = dict(
        conglomerado_doc=CONGLOMERADO_DOC,
        subgrupo_doc=doc,
        nivel=Nivel.CONGLOMERADO if doc == CONGLOMERADO_DOC else Nivel.SUBGRUPO,
        origem=Origem.BASE,
        atual=InfoFaturamento(valor=valor, data_ref_balanco=_hoje()),
    )
    defaults.update(overrides)
    return MarcadorFaturamento(**defaults)


def test_buscar_grupos_economicos_delega_pro_nj6_e_devolve_a_lista():
    grupo1 = conglomerado_simples("900001000", "Grupo Um", [])
    grupo2 = conglomerado_simples("900002000", "Grupo Dois", ["900002001"])
    nj6 = FakeNJ6(grupo1, grupos=[grupo1, grupo2])

    grupos = service.buscar_grupos_economicos("9000", nj6)

    assert grupos == [grupo1, grupo2]


def test_buscar_grupos_economicos_sem_match_devolve_lista_vazia():
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []), grupos=[])

    assert service.buscar_grupos_economicos("999", nj6) == []


class _EndpointContador:
    """Fake local que registra quais documentos foram consultados - para provar
    que o banco sempre vence sem precisar chamar o Endpoint (`R-PEND-011`)."""

    def __init__(self) -> None:
        self.chamados: list[str] = []

    def buscar(self, documento_raiz: str, asof=None):
        self.chamados.append(documento_raiz)
        return None


def test_matriz_e_subgrupo_sem_banco_usam_endpoint():
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", ["SUB2"]))
    repo = FakeRepositorio()
    endpoint = FakeEndpoint()
    endpoint.seed(
        CONGLOMERADO_DOC,
        ResultadoFaturamento(valor_faturamento=Decimal("5000000"), data_ref_balanco=_hoje()),
    )
    endpoint.seed("SUB2", None)
    catalogo = FakeCatalogo()

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    por_doc = {m.subgrupo_doc: m for m in fat.marcadores}
    assert por_doc[CONGLOMERADO_DOC].origem == Origem.ENDPOINT
    assert por_doc[CONGLOMERADO_DOC].atual.valor == Decimal("5000000")
    assert por_doc["SUB2"].origem == Origem.MANUAL


def test_subgrupo_com_banco_vence_mesmo_com_endpoint_disponivel():
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []))
    repo = FakeRepositorio()
    repo.seed(_marcador_base(CONGLOMERADO_DOC, Decimal("6000000")))
    endpoint = FakeEndpoint()
    endpoint.seed(
        CONGLOMERADO_DOC,
        ResultadoFaturamento(valor_faturamento=Decimal("999999999"), data_ref_balanco=_hoje()),
    )
    catalogo = FakeCatalogo()

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    assert fat.marcadores[0].atual.valor == Decimal("6000000")
    assert fat.marcadores[0].origem == Origem.BASE


def test_subgrupo_com_banco_nao_chama_endpoint_pra_ele():
    """Confirmado com o PO: banco sempre vence - nem precisa consultar o Endpoint
    pra quem já tem valor salvo."""
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", ["SUB2"]))
    repo = FakeRepositorio()
    repo.seed(_marcador_base(CONGLOMERADO_DOC, Decimal("6000000")))
    endpoint = _EndpointContador()
    catalogo = FakeCatalogo()

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    assert CONGLOMERADO_DOC not in endpoint.chamados  # banco já resolvia - não precisou
    assert "SUB2" in endpoint.chamados  # SUB2 sem banco - precisou consultar
    assert {m.subgrupo_doc: m.origem for m in fat.marcadores} == {
        CONGLOMERADO_DOC: Origem.BASE,
        "SUB2": Origem.MANUAL,
    }


def test_todos_os_alvos_com_banco_nunca_chama_endpoint():
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", ["SUB2"]))
    repo = FakeRepositorio()
    repo.seed(_marcador_base(CONGLOMERADO_DOC, Decimal("6000000")))
    repo.seed(_marcador_base("SUB2", Decimal("3000000")))
    endpoint = _EndpointContador()
    catalogo = FakeCatalogo()

    service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    assert endpoint.chamados == []


def test_quarentena_usa_valor_anterior_e_ignora_endpoint():
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []))
    repo = FakeRepositorio()
    repo.seed(
        _marcador_base(
            CONGLOMERADO_DOC,
            Decimal("999999999"),  # não deveria ser usado
            anterior=InfoFaturamento(valor=Decimal("4000000"), data_ref_balanco="2023-01-01"),
            quarentena=True,
        )
    )
    endpoint = _EndpointContador()
    catalogo = FakeCatalogo()

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    m = fat.marcadores[0]
    assert m.em_quarentena is True
    assert m.atual.valor == Decimal("4000000")
    assert endpoint.chamados == []  # quarentena também não precisa do Endpoint


def test_obter_faturamento_lista_matriz_e_todos_os_subgrupos_sem_limite():
    docs = [f"SUB{i}" for i in range(5)]
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", docs))
    repo = FakeRepositorio()
    endpoint = FakeEndpoint()
    for d in docs:
        endpoint.seed(d, None)
    catalogo = FakeCatalogo()

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    # matriz + 5 subgrupos, tudo numa lista só, sem paginação
    assert len(fat.marcadores) == 6
    assert fat.marcadores[0].nivel == Nivel.CONGLOMERADO
    assert {m.subgrupo_doc for m in fat.marcadores[1:]} == set(docs)


def test_falha_isolada_no_endpoint_nao_derruba_outros_subgrupos():
    docs = ["SUB2"]
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", docs))
    repo = FakeRepositorio()
    endpoint = FakeEndpoint()
    endpoint.seed_erro(CONGLOMERADO_DOC)
    endpoint.seed(
        "SUB2", ResultadoFaturamento(valor_faturamento=Decimal("1000000"), data_ref_balanco=_hoje())
    )
    catalogo = FakeCatalogo()

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    por_doc = {m.subgrupo_doc: m for m in fat.marcadores}
    assert por_doc[CONGLOMERADO_DOC].origem == Origem.MANUAL
    assert por_doc["SUB2"].origem == Origem.ENDPOINT


def test_usa_o_catalogo_recebido_por_parametro_nao_a_classe_protocol():
    """Regressão do bug #3 (AVALIACAO.md §4.3): o código chamava `Catalogo.obter()`
    na classe em vez de `catalogo.obter()` na instância — o que derrubava todo BUSCAR."""
    nj6 = FakeNJ6(conglomerado_simples(CONGLOMERADO_DOC, "Grupo Teste", []))
    repo = FakeRepositorio()
    endpoint = FakeEndpoint()
    endpoint.seed(
        CONGLOMERADO_DOC,
        ResultadoFaturamento(valor_faturamento=Decimal("5000000"), data_ref_balanco=_hoje()),
    )
    catalogo = FakeCatalogo(
        faixas=[{"codigo": "X", "descricao": "rotulo-do-teste", "min": 0, "max": None}]
    )

    fat = service.obter_faturamento(CONGLOMERADO_DOC, repo, nj6, endpoint, catalogo)

    assert fat.marcadores[0].atual.faixa_descricao == "rotulo-do-teste"

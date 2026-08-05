from decimal import Decimal

from app.adapters.repository import DynamoRepository
from app.domain.models import Faturamento, InfoFaturamento, MarcadorFaturamento, Nivel, Origem
from tests.dynamo_fakes import FakeDynamoResource, FakeTable

CDOC = "12345678000100"
SDOC = "12345678000100"


def _repo() -> DynamoRepository:
    return DynamoRepository(table_name="teste", dynamodb=FakeDynamoResource(FakeTable()))


def _marcador(**overrides) -> MarcadorFaturamento:
    defaults = dict(
        conglomerado_doc=CDOC,
        subgrupo_doc=SDOC,
        nivel=Nivel.CONGLOMERADO,
        nome="Grupo Teste",
        atual=InfoFaturamento(valor=Decimal("500000"), moeda="BRL", faixa_codigo="FAIXA_1"),
        origem=Origem.BASE,
    )
    defaults.update(overrides)
    return MarcadorFaturamento(**defaults)


def test_get_subgrupo_nao_encontrado_retorna_none():
    assert _repo().get_subgrupo(CDOC, SDOC) is None


def test_save_e_get_subgrupo_round_trip():
    repo = _repo()
    fat = Faturamento(conglomerado_doc=CDOC, marcadores=[_marcador()], atualizado_em="2024-01-01")
    repo.save(fat)

    salvo = repo.get_subgrupo(CDOC, SDOC)
    assert salvo is not None
    assert salvo.conglomerado_doc == CDOC
    assert salvo.subgrupo_doc == SDOC
    assert salvo.nivel == Nivel.CONGLOMERADO
    assert salvo.nome == "Grupo Teste"
    assert salvo.origem == Origem.BASE
    assert salvo.atual.valor == Decimal("500000")
    assert salvo.atual.faixa_codigo == "FAIXA_1"
    assert salvo.atual.moeda == "BRL"
    assert salvo.anterior is None
    assert salvo.atualizado_em == "2024-01-01"


def test_save_e_get_subgrupo_round_trip_racf_auditoria_valor_ativo():
    repo = _repo()
    marcador = _marcador(
        atual=InfoFaturamento(
            valor=Decimal("500000"),
            moeda="BRL",
            racf="r123456",
            auditoria="KPMG",
            valor_ativo=Decimal("120000"),
        )
    )
    fat = Faturamento(conglomerado_doc=CDOC, marcadores=[marcador], atualizado_em="2024-01-01")
    repo.save(fat)

    salvo = repo.get_subgrupo(CDOC, SDOC)
    assert salvo.atual.racf == "r123456"
    assert salvo.atual.auditoria == "KPMG"
    assert salvo.atual.valor_ativo == Decimal("120000")


def test_save_faz_roll_hoje_vira_ontem():
    repo = _repo()
    fat1 = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[_marcador(atual=InfoFaturamento(valor=Decimal("100"), moeda="BRL"))],
    )
    repo.save(fat1)

    fat2 = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[_marcador(atual=InfoFaturamento(valor=Decimal("200"), moeda="BRL"))],
    )
    repo.save(fat2)

    salvo = repo.get_subgrupo(CDOC, SDOC)
    assert salvo.atual.valor == Decimal("200")
    assert salvo.anterior is not None
    assert salvo.anterior.valor == Decimal("100")


def test_save_com_anterior_explicito_nao_faz_roll_automatico():
    repo = _repo()
    anterior = InfoFaturamento(valor=Decimal("999"), moeda="BRL")
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[_marcador(anterior=anterior)],
    )
    repo.save(fat)

    salvo = repo.get_subgrupo(CDOC, SDOC)
    assert salvo.anterior.valor == Decimal("999")


def test_save_e_incremental_nao_apaga_outros_subgrupos():
    repo = _repo()
    repo.save(Faturamento(conglomerado_doc=CDOC, marcadores=[_marcador(subgrupo_doc="111")]))
    repo.save(Faturamento(conglomerado_doc=CDOC, marcadores=[_marcador(subgrupo_doc="222")]))

    assert repo.get_subgrupo(CDOC, "111") is not None
    assert repo.get_subgrupo(CDOC, "222") is not None


def test_get_conglomerado_retorna_todos_os_marcadores():
    repo = _repo()
    repo.save(Faturamento(conglomerado_doc=CDOC, marcadores=[_marcador(subgrupo_doc="111")]))
    repo.save(Faturamento(conglomerado_doc=CDOC, marcadores=[_marcador(subgrupo_doc="222")]))

    marcadores = repo.get_conglomerado(CDOC)
    assert {m.subgrupo_doc for m in marcadores} == {"111", "222"}


def test_save_persiste_faturamento_cra_sem_faturamento_justificativa_quarentena():
    repo = _repo()
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[
            _marcador(
                faturamento_cra=InfoFaturamento(valor=Decimal("42"), moeda="BRL"),
                sem_faturamento=True,
                justificativa="não possui",
                aceite=True,
                quarentena=True,
                quarentena_desde="2024-01-01",
            )
        ],
    )
    repo.save(fat)

    salvo = repo.get_subgrupo(CDOC, SDOC)
    assert salvo.faturamento_cra.valor == Decimal("42")
    assert salvo.sem_faturamento is True
    assert salvo.justificativa == "não possui"
    assert salvo.aceite is True
    assert salvo.quarentena is True
    assert salvo.quarentena_desde == "2024-01-01"


def test_item_to_marcador_usa_defaults_quando_campos_ausentes():
    repo = _repo()
    fat = Faturamento(
        conglomerado_doc=CDOC,
        marcadores=[MarcadorFaturamento(conglomerado_doc=CDOC, subgrupo_doc=SDOC)],
    )
    repo.save(fat)

    salvo = repo.get_subgrupo(CDOC, SDOC)
    assert salvo.nivel == Nivel.SUBGRUPO
    assert salvo.origem == Origem.MANUAL
    assert salvo.aceite is False
    assert salvo.sem_faturamento is False
    assert salvo.quarentena is False
    assert salvo.atual.moeda == "BRL"
    assert salvo.atual.unidade == "milhoes"


def test_default_table_name_usa_settings(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.adapters.repository.settings", SimpleNamespace(tabela_faturamento="outra-tabela")
    )
    fake_table = FakeTable()

    class _Resource:
        def Table(self, name):
            assert name == "outra-tabela"
            return fake_table

    repo = DynamoRepository(dynamodb=_Resource())
    assert repo.table is fake_table

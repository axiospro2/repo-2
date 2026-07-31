"""Steps do cenário de BUSCAR (behave), espelhando `domain/service_buscar.py`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from behave import given, then, when
from tests.fakes import (
    FAIXAS_PADRAO,
    FakeCatalogo,
    FakeEndpoint,
    FakeNJ6,
    FakeRepositorio,
    conglomerado_simples,
)

from app.domain import service_buscar as service
from app.domain.eleicao import ResultadoFaturamento
from app.domain.models import InfoFaturamento, MarcadorFaturamento, Nivel, Origem


def _hoje() -> str:
    return datetime.now().date().isoformat()


def _repo(context) -> FakeRepositorio:
    if not hasattr(context, "repo"):
        context.repo = FakeRepositorio()
    return context.repo


def _endpoint(context) -> FakeEndpoint:
    if not hasattr(context, "endpoint"):
        context.endpoint = FakeEndpoint()
    return context.endpoint


@given('um conglomerado "{conglomerado}" com os subgrupos "{subgrupos}" no NJ6')
def step_conglomerado(context, conglomerado, subgrupos):
    docs = [s.strip() for s in subgrupos.split(",")]
    context.conglomerado_doc = conglomerado
    context.nj6 = FakeNJ6(conglomerado_simples(conglomerado, "Grupo de Teste", docs))


@given("o catálogo de parâmetros do buscar tem as faixas padrão")
def step_faixas_padrao(context):
    context.catalogo = FakeCatalogo(faixas=FAIXAS_PADRAO)


@given('que o subgrupo "{subgrupo}" não tem nenhum valor salvo no banco')
def step_subgrupo_sem_banco(context, subgrupo):
    pass  # FakeRepositorio simplesmente não tem nada seedado para esse subgrupo


@given('o Endpoint devolve um resultado de "{valor}" para o subgrupo "{subgrupo}"')
def step_endpoint_com_resultado(context, valor, subgrupo):
    _endpoint(context).seed(
        subgrupo, ResultadoFaturamento(valor_faturamento=Decimal(valor), data_ref_balanco=_hoje())
    )


@given('o Endpoint não devolve nenhum resultado para o subgrupo "{subgrupo}"')
def step_endpoint_sem_resultado(context, subgrupo):
    _endpoint(context).seed(subgrupo, None)


@given('o Endpoint falha ao consultar o subgrupo "{subgrupo}"')
def step_endpoint_falha(context, subgrupo):
    _endpoint(context).seed_erro(subgrupo)


@given('que o subgrupo "{subgrupo}" já tem um valor de "{valor}" salvo no banco')
def step_subgrupo_com_valor_no_banco(context, subgrupo, valor):
    _repo(context).seed(
        MarcadorFaturamento(
            conglomerado_doc=context.conglomerado_doc,
            subgrupo_doc=subgrupo,
            nivel=Nivel.SUBGRUPO,
            origem=Origem.BASE,
            atual=InfoFaturamento(valor=Decimal(valor), data_ref_balanco=_hoje()),
        )
    )


@given('que o subgrupo "{subgrupo}" está em quarentena com um valor anterior de "{valor}" salvo')
def step_subgrupo_em_quarentena(context, subgrupo, valor):
    _repo(context).seed(
        MarcadorFaturamento(
            conglomerado_doc=context.conglomerado_doc,
            subgrupo_doc=subgrupo,
            nivel=Nivel.SUBGRUPO,
            atual=InfoFaturamento(valor=Decimal("999999999")),  # não deveria ser usado
            anterior=InfoFaturamento(valor=Decimal(valor), data_ref_balanco="2023-01-01"),
            quarentena=True,
        )
    )
    _endpoint(context).seed(subgrupo, None)


@when('eu buscar o faturamento do conglomerado "{conglomerado}"')
def step_buscar(context, conglomerado):
    context.resultado = service.obter_faturamento(
        conglomerado,
        _repo(context),
        context.nj6,
        _endpoint(context),
        context.catalogo,
    )
    context.por_doc = {m.subgrupo_doc: m for m in context.resultado.marcadores}


@then('o marcador do subgrupo "{subgrupo}" deve ter origem "{origem}"')
def step_verifica_origem(context, subgrupo, origem):
    marcador = context.por_doc[subgrupo]
    assert marcador.origem == Origem(origem), f"esperava {origem}, veio {marcador.origem}"


@then('o marcador do subgrupo "{subgrupo}" deve estar em quarentena')
def step_verifica_quarentena(context, subgrupo):
    assert context.por_doc[subgrupo].em_quarentena is True


@then('o marcador do subgrupo "{subgrupo}" deve ter o valor "{valor}"')
def step_verifica_valor(context, subgrupo, valor):
    assert context.por_doc[subgrupo].atual.valor == Decimal(valor)

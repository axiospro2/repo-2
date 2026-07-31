"""Steps do cenário de SALVAR (behave), espelhando `domain/service.py::salvar`."""

from __future__ import annotations

from decimal import Decimal

from behave import given, then, when
from tests.fakes import FAIXAS_PADRAO, FakeRepositorio

from app.domain import service
from app.domain.errors import ConfirmacaoNecessaria, DominioError, ErroValidacao
from app.domain.models import Faturamento, InfoFaturamento, MarcadorFaturamento


def _repo(context) -> FakeRepositorio:
    if not hasattr(context, "repo"):
        context.repo = FakeRepositorio()
    return context.repo


def _params(context) -> dict:
    return {
        "faixas": getattr(context, "faixas", FAIXAS_PADRAO),
        "moedas": getattr(context, "moedas", ["BRL", "USD"]),
        "gateDivergenciaAtivo": getattr(context, "gate_ativo", False),
        "limiteVariacaoPercentual": getattr(context, "limite_variacao", 30),
    }


def _adicionar_marcador(context, subgrupo: str, valor: str, moeda: str, confirmado: bool) -> None:
    if not hasattr(context, "conglomerado_doc"):
        context.conglomerado_doc = subgrupo
    marcador = MarcadorFaturamento(
        conglomerado_doc=context.conglomerado_doc,
        subgrupo_doc=subgrupo,
        atual=InfoFaturamento(valor=Decimal(valor), moeda=moeda, unidade="unitario"),
        confirmado_divergencia=confirmado,
    )
    context.marcadores = getattr(context, "marcadores", [])
    context.marcadores.append(marcador)


@given("o catálogo de parâmetros do salvar tem as faixas padrão")
def step_faixas_padrao(context):
    context.faixas = FAIXAS_PADRAO


@given('o catálogo de parâmetros do salvar aceita as moedas "{moedas}"')
def step_moedas_aceitas(context, moedas):
    context.moedas = [m.strip() for m in moedas.split(",")]


@given('um marcador para o subgrupo "{subgrupo}" com valor "{valor}" e moeda "{moeda}"')
def step_marcador_simples(context, subgrupo, valor, moeda):
    _adicionar_marcador(context, subgrupo, valor, moeda, confirmado=False)


@given(
    'um marcador para o subgrupo "{subgrupo}" com valor "{valor}" e moeda "{moeda}" confirmando a'
    " divergência"
)
def step_marcador_confirmando_divergencia(context, subgrupo, valor, moeda):
    _adicionar_marcador(context, subgrupo, valor, moeda, confirmado=True)


@given('um faturamento sem nenhum marcador para o conglomerado "{conglomerado}"')
def step_faturamento_vazio(context, conglomerado):
    context.conglomerado_doc = conglomerado
    context.marcadores = []


@given('que já existe um valor salvo de "{valor}" para o subgrupo "{subgrupo}"')
def step_valor_ja_salvo(context, valor, subgrupo):
    context.conglomerado_doc = subgrupo
    existente = MarcadorFaturamento(
        conglomerado_doc=subgrupo,
        subgrupo_doc=subgrupo,
        atual=InfoFaturamento(valor=Decimal(valor), moeda="BRL", unidade="unitario"),
    )
    _repo(context).seed(existente)


@given('o gate de divergência está ativo com limite de "{limite}" por cento')
def step_gate_ativo(context, limite):
    context.gate_ativo = True
    context.limite_variacao = int(limite)


def _executar_salvar(context) -> None:
    fat = Faturamento(conglomerado_doc=context.conglomerado_doc, marcadores=context.marcadores)
    context.excecao = None
    context.resultado = None
    try:
        context.resultado = service.salvar(fat, _repo(context), _params(context))
    except DominioError as e:
        context.excecao = e


@when('eu salvar o faturamento do conglomerado "{conglomerado}"')
def step_salvar(context, conglomerado):
    _executar_salvar(context)


@when('eu tentar salvar o faturamento do conglomerado "{conglomerado}"')
def step_tentar_salvar(context, conglomerado):
    _executar_salvar(context)


@then("o faturamento deve ser persistido com sucesso")
def step_persistido_com_sucesso(context):
    assert context.excecao is None, f"esperava sucesso, mas houve erro: {context.excecao!r}"
    assert context.resultado is not None


@then('o marcador do subgrupo "{subgrupo}" deve ter a faixa "{faixa}"')
def step_verifica_faixa(context, subgrupo, faixa):
    salvo = _repo(context).get_subgrupo(context.conglomerado_doc, subgrupo)
    assert salvo is not None, f"nenhum marcador salvo para {subgrupo}"
    assert salvo.atual.faixa_codigo == faixa


@then("deve ser rejeitado com erro de validação")
def step_erro_validacao(context):
    assert isinstance(
        context.excecao, ErroValidacao
    ), f"esperava ErroValidacao, veio {context.excecao!r}"


@then("deve ser exigida confirmação de divergência")
def step_confirmacao_necessaria(context):
    assert isinstance(
        context.excecao, ConfirmacaoNecessaria
    ), f"esperava ConfirmacaoNecessaria, veio {context.excecao!r}"
    assert len(context.excecao.divergencias) > 0

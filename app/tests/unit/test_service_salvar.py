from decimal import Decimal

import pytest

from app.domain import service
from app.domain.errors import ConfirmacaoNecessaria, ErroValidacao, FaixaObrigatoria
from app.domain.models import Faturamento, InfoFaturamento, MarcadorFaturamento
from tests.fakes import FAIXAS_PADRAO, MOEDAS_PADRAO, FakeRepositorio

CONGLOMERADO_DOC = "12345678000100"


def _params(gate_ativo=False, limite=30):
    return {
        "faixas": FAIXAS_PADRAO,
        "moedas": MOEDAS_PADRAO,
        "gateDivergenciaAtivo": gate_ativo,
        "limiteVariacaoPercentual": limite,
    }


def _fat(
    subgrupo=CONGLOMERADO_DOC, valor=Decimal("5000000"), moeda="BRL", unidade="unitario", **kwargs
):
    """unidade="unitario" (x1) por padrão - os valores de teste já são o número de reais."""
    marcador = MarcadorFaturamento(
        conglomerado_doc=CONGLOMERADO_DOC,
        subgrupo_doc=subgrupo,
        atual=InfoFaturamento(valor=valor, moeda=moeda, unidade=unidade),
        **kwargs,
    )
    return Faturamento(conglomerado_doc=CONGLOMERADO_DOC, marcadores=[marcador])


def test_salvar_com_sucesso_persiste_no_repositorio():
    repo = FakeRepositorio()
    resultado = service.salvar(_fat(), repo, _params())
    salvo = repo.get_subgrupo(CONGLOMERADO_DOC, CONGLOMERADO_DOC)
    assert salvo is not None
    assert salvo.atual.faixa_codigo == "FAIXA_2"
    assert resultado.atualizado_em is not None


def test_salvar_sem_marcadores_leva_a_erro_de_validacao():
    repo = FakeRepositorio()
    fat = Faturamento(conglomerado_doc=CONGLOMERADO_DOC, marcadores=[])
    with pytest.raises(ErroValidacao):
        service.salvar(fat, repo, _params())


def test_sem_faturamento_ignora_valor_e_faixa():
    repo = FakeRepositorio()
    resultado = service.salvar(_fat(valor=None, sem_faturamento=True), repo, _params())
    assert resultado.marcadores[0].atual.valor is None
    assert resultado.marcadores[0].atual.faixa_codigo is None


def test_valor_fora_das_faixas_conhecidas_leva_a_erro():
    repo = FakeRepositorio()
    with pytest.raises(ErroValidacao):
        service.salvar(_fat(valor=Decimal("1")), repo, _params())


def test_valor_em_unidade_mil_e_convertido_para_reais_antes_da_faixa():
    """5000 'mil' = R$ 5.000.000 -> FAIXA_2 (4,8 MM a 20 MM). Sem conversão, 5000 cairia fora."""
    repo = FakeRepositorio()
    marcador = MarcadorFaturamento(
        conglomerado_doc=CONGLOMERADO_DOC,
        subgrupo_doc=CONGLOMERADO_DOC,
        atual=InfoFaturamento(valor=Decimal("5000"), moeda="BRL", unidade="mil"),
    )
    fat = Faturamento(conglomerado_doc=CONGLOMERADO_DOC, marcadores=[marcador])
    resultado = service.salvar(fat, repo, _params())
    assert resultado.marcadores[0].atual.faixa_codigo == "FAIXA_2"
    assert resultado.marcadores[0].atual.valor == Decimal("5000")  # persiste o valor bruto


def test_valor_com_unidade_desconhecida_leva_a_erro():
    repo = FakeRepositorio()
    marcador = MarcadorFaturamento(
        conglomerado_doc=CONGLOMERADO_DOC,
        subgrupo_doc=CONGLOMERADO_DOC,
        atual=InfoFaturamento(valor=Decimal("5000000"), moeda="BRL", unidade="trilhoes"),
    )
    fat = Faturamento(conglomerado_doc=CONGLOMERADO_DOC, marcadores=[marcador])
    with pytest.raises(ErroValidacao):
        service.salvar(fat, repo, _params())


def test_sem_valor_e_sem_faixa_exige_faixa_obrigatoria():
    repo = FakeRepositorio()
    with pytest.raises(FaixaObrigatoria):
        service.salvar(_fat(valor=None), repo, _params())


def test_moeda_invalida_leva_a_erro():
    repo = FakeRepositorio()
    with pytest.raises(ErroValidacao):
        service.salvar(_fat(moeda="EUR"), repo, _params())


def test_moeda_ausente_leva_a_erro():
    repo = FakeRepositorio()
    with pytest.raises(ErroValidacao):
        service.salvar(_fat(moeda=None), repo, _params())


def test_divergencia_nao_confirmada_e_barrada():
    repo = FakeRepositorio()
    repo.seed(_fat(valor=Decimal("1000000")).marcadores[0])
    with pytest.raises(ConfirmacaoNecessaria) as exc_info:
        service.salvar(_fat(valor=Decimal("5000000")), repo, _params(gate_ativo=True, limite=30))
    assert exc_info.value.divergencias[0]["tipo"] == "VALOR"


def test_divergencia_confirmada_e_aceita():
    repo = FakeRepositorio()
    repo.seed(_fat(valor=Decimal("1000000")).marcadores[0])
    resultado = service.salvar(
        _fat(valor=Decimal("5000000"), confirmado_divergencia=True),
        repo,
        _params(gate_ativo=True, limite=30),
    )
    assert resultado.marcadores[0].atual.valor == Decimal("5000000")


def test_divergencia_dentro_do_limite_nao_bloqueia():
    repo = FakeRepositorio()
    repo.seed(_fat(valor=Decimal("5000000")).marcadores[0])
    resultado = service.salvar(
        _fat(valor=Decimal("5500000")),  # 10% de variação, limite 30%
        repo,
        _params(gate_ativo=True, limite=30),
    )
    assert resultado.marcadores[0].atual.valor == Decimal("5500000")


def test_marcador_sem_subgrupo_doc_leva_a_erro():
    repo = FakeRepositorio()
    with pytest.raises(ErroValidacao):
        service.salvar(_fat(subgrupo=""), repo, _params())


def test_catalogo_de_faixas_vazio_leva_a_erro():
    repo = FakeRepositorio()
    params = _params()
    params["faixas"] = []
    with pytest.raises(ErroValidacao):
        service.salvar(_fat(), repo, params)


def test_catalogo_de_moedas_vazio_leva_a_erro():
    repo = FakeRepositorio()
    params = _params()
    params["moedas"] = []
    with pytest.raises(ErroValidacao):
        service.salvar(_fat(), repo, params)


def test_gate_ativo_sem_registro_existente_nao_bloqueia():
    repo = FakeRepositorio()
    resultado = service.salvar(_fat(), repo, _params(gate_ativo=True, limite=30))
    assert resultado.marcadores[0].atual.valor == Decimal("5000000")


def test_salvar_persiste_nome_responsavel_carimbado_no_atual():
    repo = FakeRepositorio()
    marcador = MarcadorFaturamento(
        conglomerado_doc=CONGLOMERADO_DOC,
        subgrupo_doc=CONGLOMERADO_DOC,
        atual=InfoFaturamento(
            valor=Decimal("5000000"), moeda="BRL", unidade="unitario", nome_responsavel="Alice"
        ),
    )
    fat = Faturamento(conglomerado_doc=CONGLOMERADO_DOC, marcadores=[marcador])
    resultado = service.salvar(fat, repo, _params())
    assert resultado.marcadores[0].atual.nome_responsavel == "Alice"

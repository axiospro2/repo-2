from app.domain import paginacao
from app.domain.models import Nivel


def test_subgrupos_unicos_deduplica_por_documento():
    from tests.fakes import conglomerado_simples

    cong = conglomerado_simples("123", "Grupo", ["A", "B", "A"])
    alvos = paginacao.subgrupos_unicos(cong)
    docs = [doc for (_, doc, _) in alvos]
    assert docs == ["A", "B"]
    assert all(nivel == Nivel.SUBGRUPO for (nivel, _, _) in alvos)


def test_alvos_do_conglomerado_traz_matriz_e_subgrupos():
    from tests.fakes import conglomerado_simples

    cong = conglomerado_simples("123", "Grupo", ["A", "B"])
    alvos = paginacao.alvos_do_conglomerado(cong)

    assert alvos[0] == (Nivel.CONGLOMERADO, "123", "Grupo")
    assert alvos[1:] == [
        (Nivel.SUBGRUPO, "A", "Subgrupo A"),
        (Nivel.SUBGRUPO, "B", "Subgrupo B"),
    ]


def test_alvos_do_conglomerado_sem_subgrupos_traz_so_a_matriz():
    from tests.fakes import conglomerado_simples

    cong = conglomerado_simples("123", "Grupo", [])
    alvos = paginacao.alvos_do_conglomerado(cong)
    assert alvos == [(Nivel.CONGLOMERADO, "123", "Grupo")]


def test_alvos_do_conglomerado_nao_duplica_quando_subgrupo_e_a_propria_matriz():
    """O NJ6 às vezes lista a matriz também como um "subgrupo" cru (mesmo
    documento) - não pode virar dois alvos pro mesmo documento."""
    from tests.fakes import conglomerado_simples

    cong = conglomerado_simples("123", "Grupo", ["123", "B"])
    alvos = paginacao.alvos_do_conglomerado(cong)

    docs = [doc for (_, doc, _) in alvos]
    assert docs == ["123", "B"]
    assert alvos[0][0] == Nivel.CONGLOMERADO

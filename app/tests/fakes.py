"""Dublês (fakes) dos Protocols do domínio — sem I/O real.

Usados pelos testes unitários (`tests/unit/`) e pelos steps de BDD
(`features/steps/`), para manter as duas suítes consistentes entre si.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.domain.eleicao import ResultadoFaturamento, eleger
from app.domain.models import Conglomerado, Faturamento, MarcadorFaturamento, Pessoa, Subgrupo

FAIXAS_PADRAO: list[dict] = [
    {"codigo": "FAIXA_1", "descricao": "R$ 360 mil a R$ 4,8 MM", "min": 360000, "max": 4800000},
    {"codigo": "FAIXA_2", "descricao": "R$ 4,8 MM a R$ 20 MM", "min": 4800000, "max": 20000000},
    {"codigo": "FAIXA_3", "descricao": "R$ 20 MM a R$ 100 MM", "min": 20000000, "max": 100000000},
    {"codigo": "FAIXA_4", "descricao": "R$ 100 MM a R$ 500 MM", "min": 100000000, "max": 500000000},
    {"codigo": "FAIXA_5", "descricao": "R$ 500 MM a R$ 2 BI", "min": 500000000, "max": 2000000000},
    {"codigo": "FAIXA_6", "descricao": "Acima de R$ 2 BI", "min": 2000000000, "max": None},
]

MOEDAS_PADRAO: list[str] = ["BRL", "USD"]


class FakeRepositorio:
    """Serve os dois `Protocol`s `Repositorio` do domínio: o do SALVAR
    (`get_subgrupo`/`save`) e o do BUSCAR (`get_conglomerado`)."""

    def __init__(self) -> None:
        self._itens: dict[tuple[str, str], MarcadorFaturamento] = {}

    def seed(self, marcador: MarcadorFaturamento) -> None:
        self._itens[(marcador.conglomerado_doc, marcador.subgrupo_doc)] = marcador

    def get_subgrupo(
        self, conglomerado_doc: str, subgrupo_doc: str
    ) -> Optional[MarcadorFaturamento]:
        return self._itens.get((conglomerado_doc, subgrupo_doc))

    def get_conglomerado(self, conglomerado_doc: str) -> list[MarcadorFaturamento]:
        return [m for (cdoc, _), m in self._itens.items() if cdoc == conglomerado_doc]

    def save(self, f: Faturamento) -> None:
        for m in f.marcadores:
            self._itens[(f.conglomerado_doc, m.subgrupo_doc)] = m


class FakeNJ6:
    def __init__(
        self, conglomerado: Conglomerado, grupos: Optional[list[Conglomerado]] = None
    ) -> None:
        self._conglomerado = conglomerado
        self._grupos = grupos if grupos is not None else [conglomerado]

    def get_por_documento(self, documento: str) -> Conglomerado:
        return self._conglomerado

    def buscar_grupos(self, termo: str) -> list[Conglomerado]:
        return self._grupos


class FakeEndpoint:
    def __init__(self) -> None:
        self._resultados: dict[str, Optional[ResultadoFaturamento]] = {}
        self._erros: set[str] = set()

    def seed(self, subgrupo_doc: str, resultado: Optional[ResultadoFaturamento]) -> None:
        self._resultados[subgrupo_doc] = resultado

    def seed_erro(self, subgrupo_doc: str) -> None:
        self._erros.add(subgrupo_doc)

    def buscar(self, documento_raiz: str, asof: Optional[str] = None):
        if documento_raiz in self._erros:
            raise RuntimeError("endpoint indisponível (simulado no teste)")
        return self._resultados.get(documento_raiz)


class FakeEndpointComEleicao:
    """Fake que roda a eleição R1/R2/R3 DE VERDADE (chama `eleicao.eleger`) sobre
    análises cruas, sem HTTP - liga a ponta "banco vazio" até a regra que
    realmente elegeu o valor. Diferente de `FakeEndpoint`, que devolve um
    `ResultadoFaturamento` já pronto (bypassa a cascata por completo)."""

    def __init__(self) -> None:
        self._analises: dict[str, list[dict]] = {}
        self._erros: set[str] = set()

    def seed_analises(self, documento_raiz: str, analises: list[dict]) -> None:
        self._analises[documento_raiz] = analises

    def seed_erro(self, documento_raiz: str) -> None:
        self._erros.add(documento_raiz)

    def buscar(self, documento_raiz: str, asof: Optional[str] = None):
        if documento_raiz in self._erros:
            raise RuntimeError("endpoint indisponível (simulado no teste)")
        ref = date.fromisoformat(asof) if asof else date.today()
        return eleger(self._analises.get(documento_raiz, []), ref)


class FakeCatalogo:
    def __init__(
        self, faixas: Optional[list[dict]] = None, moedas: Optional[list[str]] = None
    ) -> None:
        self._snapshot = {
            "faixas": faixas if faixas is not None else FAIXAS_PADRAO,
            "moedas": moedas if moedas is not None else MOEDAS_PADRAO,
        }

    def obter(self) -> dict:
        return self._snapshot


def conglomerado_simples(cdoc: str, nome: str, subgrupos: list[str]) -> Conglomerado:
    """Monta um Conglomerado com um Subgrupo (1 integrante) por documento informado."""
    return Conglomerado(
        nome_grupo_economico=nome,
        cabeca_documento_raiz=cdoc,
        segmento="Indústria",
        subgrupos=[
            Subgrupo(
                nome_subgrupo=f"Subgrupo {doc}",
                cabeca_documento_raiz=doc,
                participantes=[Pessoa(codigo_identificacao_pessoa=doc, documento_raiz=doc)],
            )
            for doc in subgrupos
        ],
    )

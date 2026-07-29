"""Eleição do "melhor balanço" (R1 → R2 → R3) sobre as análises do Endpoint de Faturamento.

Repasse 18/06 + RN06 — regra de NEGÓCIO NOSSA (não do Endpoint). O Endpoint (Deus/Felipe) devolve as
**análises cruas** (paginado `data[]`): cada análise traz situação/auditoria/categoria/vigência +
um **histórico de faturamento** por data de referência. Estas regras escolhem **1 valor**:

  - **R1**: auditado + original + vigente, idade < 2a, SÓ nas 5 categorias de PRIORIDADE_CATEGORIA_R1
    (demais categorias são inelegíveis na R1 e caem pra R2/R3). Desempate em cascata:
    (1) prioridade de categoria, (2) data de atualização mais recente, (3) data de balanço mais recente.
  - **R2**: auditado + vigente + Aprovado(3), idade < 2a. Desempate: data de balanço mais recente.
  - **R3**: original + vigente + Aprovado(3), idade < 2a, exclui combinados e individuais
    (CATEGORIAS_R3_EXCLUIDAS). Desempate: MAIOR valor.

Cascata **R1 → R2 → R3**: a primeira regra com candidato ganha.

Campos do contrato real (usa-se o `codigo` do enum, mais estável que a string):
  - `auditoria.possuiAuditoria` = auditado.
  - `indicadorFatorPonderado` = "balanço original": original ⇔ NÃO ponderado (== False). ⚠ pendência:
    confirmar a polaridade com o time do Endpoint (assume-se true = ponderado/ajustado = não original).
  - `indicadorVigente.descricao == "Ativo"` = vigente/válido.
  - `situacao.codigo == 3` = Aprovado (4 "Histórico Aprovado" NÃO conta).
  - `categoria.codigo` no enum 1..9 (ver PRIORIDADE_CATEGORIA_R1 / CATEGORIAS_R3_EXCLUIDAS).
  - `faturamento[]` = histórico `{dataReferencia, valor}`; `atualizado` = data de atualização.

⚠ Semântica de "idade" e de histórico com datas futuras pende de confirmação (Deus/Felipe). Assume-se:
o "balanço vigente" de uma análise é o `faturamento` mais recente com `dataReferencia <= asof` e idade
<= 24 meses. O multiplicador de `unidade` (ex.: "Mil" = ×1000) NÃO é aplicado aqui — ver pendência.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Optional


IDADE_MAX_MESES = 24

# RN06 R1 — categorias elegíveis, em ordem de prioridade (código do enum). Menor índice ganha.
#   2 Consolidado-Subgrupo Todo · 4 Matriz Consolidado-Subgrupo Todo · 3 Consolidado-Segmento
#   Específico · 5 Matriz Consolidado-Segmento Específico · 6 Matriz Individual.
# As demais (1 Individual, 7/8/9 Combinados) são INELEGÍVEIS na R1.
PRIORIDADE_CATEGORIA_R1: tuple[int, ...] = (2, 4, 3, 5, 6)

# RN06 R3 — exclui combinados (7/8/9) e individuais (1 Individual, 6 Matriz Individual).
CATEGORIAS_R3_EXCLUIDAS: frozenset[int] = frozenset({1, 6, 7, 8, 9})


@dataclass
class ResultadoFaturamento:
    """Retorno do Endpoint JÁ ELEITO pelas R1/R2/R3. `id_spread` é procedência OPCIONAL."""
    valor_faturamento: Decimal
    data_ref_balanco: str
    id_spread: Optional[str] = None
    sistema_origem: Optional[str] = None
    moeda: str = "BRL"
    unidade: str = "milhoes"


@dataclass(frozen=True)
class _Candidato:
    """Uma análise + o balanço vigente escolhido dentro dela."""
    analise: dict
    balanco: dict

    @property
    def data_ref(self) -> str:
        return self.balanco["dataReferencia"]  # ISO ordena lexicograficamente

    @property
    def valor(self) -> Decimal:
        return Decimal(str(self.balanco["valor"]))
    @property
    def categoria_codigo(self) -> Optional[int]:
        return _codigo(self.analise.get("categoria"))

    @property
    def atualizado(self) -> str:
        return self.analise.get("atualizado") or ""


def eleger(analises: list[dict], asof: Optional[date] = None) -> Optional[ResultadoFaturamento]:
    """Aplica a cascata R1 → R2 → R3 às análises e devolve o resultado eleito (ou None)."""
    hoje = asof or date.today()
    candidatos = [
        _Candidato(a, bal)
        for a in analises
        if (bal := _balanco_vigente(a, hoje)) is not None
    ]

    for criterio, desempate in _REGRAS:
        elegiveis = [c for c in candidatos if criterio(c.analise)]
        if elegiveis:
            return _to_resultado(max(elegiveis, key=desempate))
    return None


def _balanco_vigente(analise: dict, asof: date) -> Optional[dict]:
    """Faturamento mais recente da análise com dataReferencia <= asof e idade <= 24 meses."""
    na_janela = [
        f for f in (analise.get("faturamento") or [])
        if _dentro_da_janela(date.fromisoformat(f["dataReferencia"]), asof)
    ]
    if not na_janela:
        return None
    return max(na_janela, key=lambda f: f["dataReferencia"])  # ISO ordena lexicograficamente


def _dentro_da_janela(ref: date, asof: date) -> bool:
    return ref <= asof and _meses_entre(ref, asof) <= IDADE_MAX_MESES


# ────────── predicados sobre a análise (campos do JSON do Endpoint) ──────────

def _auditado(a: dict) -> bool:
    return (a.get("auditoria") or {}).get("possuiAuditoria") is True


def _original(a: dict) -> bool:
    # original ⇔ NÃO ponderado (sem ajuste do analista). ⚠ polaridade a confirmar.
    return a.get("indicadorFatorPonderado") is False


def _vigente(a: dict) -> bool:
    return _descricao(a.get("indicadorVigente")).lower() == "ativo"


def _aprovado(a: dict) -> bool:
    return _codigo(a.get("situacao")) == 3  # 3 = Aprovado (4 "Histórico Aprovado" não conta)


def _categoria(a: dict) -> Optional[int]:
    return _codigo(a.get("categoria"))


def _desempate_r1(c: _Candidato) -> tuple[int, str, str]:
    """R1: prioridade de categoria (menor índice ganha), depois atualização, depois balanço."""
    rank = PRIORIDADE_CATEGORIA_R1.index(c.categoria_codigo)  # criterio garante que está na lista
    return (-rank, c.atualizado, c.data_ref)  # max() → menor rank, mais recente, mais recente


# Cascata: (critério de elegibilidade, chave de desempate do max()).
_REGRAS: tuple[tuple[Callable[[dict], bool], Callable[[_Candidato], object]], ...] = (
    # R1: auditado + original + vigente, só nas 5 categorias → prioridade/atualização/balanco
    (lambda a: _auditado(a) and _original(a) and _vigente(a)
     and _categoria(a) in PRIORIDADE_CATEGORIA_R1,
     _desempate_r1),
    # R2: auditado + vigente + Aprovado(3) → mais recente
    (lambda a: _auditado(a) and _vigente(a) and _aprovado(a),
     lambda c: c.data_ref),
    # R3: original + vigente + Aprovado(3), exclui combinados/individuais → MAIOR VALOR
    (lambda a: _original(a) and _vigente(a) and _aprovado(a)
     and _categoria(a) not in CATEGORIAS_R3_EXCLUIDAS,
     lambda c: c.valor),
)


def _to_resultado(c: _Candidato) -> ResultadoFaturamento:
    analise = c.analise
    return ResultadoFaturamento(
        valor_faturamento=c.valor,
        data_ref_balanco=c.data_ref,
        id_spread=str(analise["codigo"]) if analise.get("codigo") is not None else None,
        sistema_origem="CRA",
        moeda=_descricao(analise.get("moeda")) or "BRL",
        unidade=_descricao(analise.get("unidade")) or "milhoes",
    )


# ────────── helpers ──────────

def _descricao(cod_desc: Optional[dict]) -> str:
    return (cod_desc or {}).get("descricao") or ""


def _codigo(cod_desc: Optional[dict]) -> Optional[int]:
    cod = (cod_desc or {}).get("codigo")
    try:
        return int(cod) if cod is not None else None
    except (TypeError, ValueError):
        return None


def _meses_entre(inicio: date, fim: date) -> int:
    """Meses completos entre duas datas (equivalente a ChronoUnit.MONTHS.between)."""
    meses = (fim.year - inicio.year) * 12 + (fim.month - inicio.month)
    if fim.day < inicio.day:
        meses -= 1
    return meses

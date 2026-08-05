"""Modelos de domínio (dataclasses puras, sem framework/banco) — SALVAR + BUSCAR.

Identidade = (conglomerado_doc, subgrupo_doc). Matriz = subgrupo cujo doc == doc do
conglomerado. `id_spread` é procedência OPCIONAL (habilita o snapshot SPREAD#).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Nivel(str, Enum):
    CONGLOMERADO = "CONGLOMERADO"  # a matriz (cabeça do grupo == cabeça do subgrupo)
    SUBGRUPO = "SUBGRUPO"


class Origem(str, Enum):
    """Como o valor foi resolvido (na gravação = BASE; na leitura read-through)."""

    BASE = "BASE"  # já estava salvo na nossa base
    ENDPOINT = "ENDPOINT"  # veio do Endpoint de Faturamento (fallback, Deus/Felipe)
    MANUAL = "MANUAL"  # ainda não existe → analista preenche


@dataclass
class InfoFaturamento:
    valor: Optional[Decimal] = None
    faixa_codigo: Optional[str] = None
    faixa_descricao: Optional[str] = (
        None  # rótulo humano ("R$ 360 mil a R$ 4,8 MM"); enriquecido na leitura
    )
    data_ref_balanco: Optional[str] = None
    moeda: str = "BRL"
    unidade: str = "milhoes"
    # Procedência do VALOR — versiona JUNTO com ele: o `atual` guarda a procedência de hoje e,
    # no roll "hoje vira ontem", o `anterior` preserva a de ontem (qual spread/sistema/quem gerou).
    id_spread: Optional[str] = None  # spread que gerou este valor (procedência OPCIONAL)
    sistema_origem: Optional[str] = None  # CRA / Serasa / FactSet / agro...
    racf: Optional[str] = None  # quem informou (responsabilização) — vem no header do POST
    auditoria: Optional[str] = None  # empresa auditora do balanço (KPMG, PWC, Deloitte, EY...)
    valor_ativo: Optional[Decimal] = None  # valor do ativo informado junto ao faturamento

    @property
    def vazio(self) -> bool:
        return self.valor is None and not self.faixa_codigo


@dataclass
class MarcadorFaturamento:
    conglomerado_doc: str
    subgrupo_doc: str
    nivel: Nivel = Nivel.SUBGRUPO
    nome: Optional[str] = None
    atual: InfoFaturamento = field(default_factory=InfoFaturamento)
    anterior: Optional[InfoFaturamento] = None
    origem: Origem = Origem.MANUAL
    aceite: bool = False
    # Procedência (id_spread / sistema_origem / racf) vive dentro de `atual`/`anterior`
    # (InfoFaturamento) para versionar junto com o valor no roll "hoje vira ontem".
    # ────────── cadastro de faturamento (telas 2/3 do CRA) ──────────
    # Valor ELEITO do CRA (melhor balanço) — referência imutável mostrada no modal "editar
    # faturamento" mesmo depois do analista sobrescrever o `atual`.
    faturamento_cra: Optional[InfoFaturamento] = None
    sem_faturamento: bool = False  # analista escolheu "Não possuo o faturamento"
    justificativa: Optional[str] = None  # "Justifique/Explique o racional do faturamento"
    # ────────── controle do salvar / quarentena ──────────
    confirmado_divergencia: bool = False  # entrada do salvar: reenvio confirmando divergência
    quarentena: bool = False
    quarentena_desde: Optional[str] = None
    atualizado_em: Optional[str] = None
    em_quarentena: bool = False  # transiente: marcado na leitura quando elegeu o anterior

    @property
    def e_matriz(self) -> bool:
        return self.subgrupo_doc == self.conglomerado_doc


@dataclass
class Faturamento:
    """Agregado: faturamento de um conglomerado (matriz + subgrupos, sem paginação)."""

    conglomerado_doc: str
    nome_grupo_economico: Optional[str] = None
    segmento: Optional[str] = None  # passthrough do NJ6 (cabeçalho "Segmento: Indústria")
    atualizado_em: Optional[str] = None
    marcadores: list[MarcadorFaturamento] = field(default_factory=list)


# ────────── Modelos do NJ6 (conglomerado → subgrupos → integrantes) ──────────


@dataclass
class Pessoa:
    codigo_identificacao_pessoa: str
    documento_raiz: str
    codigo_tipo_pessoa: str = "J"
    indicador_estrangeiro: int = 0


@dataclass
class Subgrupo:
    nome_subgrupo: str
    cabeca_documento_raiz: str
    codigo_grupo_cliente_atacado: Optional[str] = None
    participantes: list[Pessoa] = field(default_factory=list)


@dataclass
class Conglomerado:
    nome_grupo_economico: str
    cabeca_documento_raiz: str
    segmento: Optional[str] = None
    subgrupos: list[Subgrupo] = field(default_factory=list)

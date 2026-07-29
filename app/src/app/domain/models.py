"""Modelos de domínio (dataclasses puras, sem framework/banco) — SALVAR + BUSCAR.

Identidade = (conglomerado_doc, subgrupo_doc). Matriz = subgrupo cujo doc == doc do
conglomerado. `id_spread` é procedência OPCIONAL (habilita o snapshot SPREAD#).

Além do núcleo (fiel à decisão 24/06), o marcador carrega campos de PASSTHROUGH que a
tela do CRA exibe na grade inferior (nome_spread, arquivo, status, categoria) e no cabeçalho
(segmento, no agregado). São OPCIONAIS: só vêm preenchidos quando a origem os gravou — o
serviço de Faturamento não os produz, apenas repassa (ver README, "campos de passthrough").
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
    BASE = "BASE"        # já estava salvo na nossa base
    ENDPOINT = "ENDPOINT"  # veio do Endpoint de Faturamento (fallback, Deus/Felipe)
    MANUAL = "MANUAL"    # ainda não existe → analista preenche


@dataclass
class InfoFaturamento:
    valor: Optional[Decimal] = None
    faixa_codigo: Optional[str] = None
    faixa_descricao: Optional[str] = None  # rótulo humano ("R$ 360 mil a R$ 4,8 MM"); enriquecido na leitura
    data_ref_balanco: Optional[str] = None
    moeda: str = "BRL"
    unidade: str = "milhoes"
    # Procedência do VALOR — versiona JUNTO com ele: o `atual` guarda a procedência de hoje e,
    # no roll "hoje vira ontem", o `anterior` preserva a de ontem (qual spread/sistema/quem gerou).
    id_spread: Optional[str] = None    # spread que gerou este valor (procedência OPCIONAL)
    sistema_origem: Optional[str] = None  # CRA / Serasa / FactSet / agro...
    racf: Optional[str] = None        # quem informou (responsabilização) — vem no header do POST
    # ────────── metadados para validar regras R1/R2/R3 no banco ──────────
    auditado: Optional[bool] = None      # R1/R2 requerem True
    original: Optional[bool] = None      # R1 requer True (não alterado/ponderado pelo analista)
    vigente: Optional[bool] = None      # R1/R2/R3 requerem True
    data_atualizacao: Optional[str] = None  # ISO timestamp — valida idade (< 24 meses)

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
    sem_faturamento: bool = False    # analista escolheu "Não possuo o faturamento"
    justificativa: Optional[str] = None  # "Justifique/Explique o racional do faturamento"
    # ────────── passthrough do CRA (grade inferior das telas 2/3) ──────────
    nome_spread: Optional[str] = None  # "cenario_otimista_set2021"
    arquivo: Optional[str] = None    # referência do balanço enviado
    status: Optional[str] = None    # "rascunho" / workflow do CRA
    categoria: Optional[str] = None  # "consolidado" (categoria do balanço)
    # ────────── controle do salvar / quarentena ──────────
    confirmado_divergencia: bool = False  # entrada do salvar: reenvio confirmando divergência
    quarentena: bool = False
    quarentena_desde: Optional[str] = None
    atualizado_em: Optional[str] = None
    em_quarentena: bool = False        # transiente: marcado na leitura quando elegeu o anterior
    faturamento_modificado: bool = False  # True se o usuário editou o marcador na tela

    @property
    def e_matriz(self) -> bool:
        return self.subgrupo_doc == self.conglomerado_doc


@dataclass
class Paginacao:
    """Recorte da lista de subgrupos (tela 3: itens por página / página X de Y)."""
    limit: int
    total: int
    offset: int = 0
    proximo_cursor: Optional[str] = None

    @property
    def tem_mais(self) -> bool:
        return self.proximo_cursor is not None


@dataclass
class Faturamento:
    """Agregado: faturamento de um conglomerado (matriz + subgrupos)."""
    conglomerado_doc: str
    nome_grupo_economico: Optional[str] = None
    segmento: Optional[str] = None    # passthrough do NJ6 (cabeçalho "Segmento: Indústria")
    atualizado_em: Optional[str] = None
    marcadores: list[MarcadorFaturamento] = field(default_factory=list)
    paginacao: Optional[Paginacao] = None
    # ────────── transiente: metadados compartilhados vindos do POST (não persistido) ──────────
    metadados_compartilhados: Optional[object] = None


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

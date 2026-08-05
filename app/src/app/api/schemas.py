""""Schemas Pydantic (camelCase) + mapeamento <-> domínio (SALVAR + BUSCAR).

Request (só SALVAR): Pydantic aqui SÓ parseia/tipa o JSON (camelCase) - NÃO valida shape
(campos obrigatórios, marcadores não-vazio, valor-ou-faixa). Toda validação (shape + negócio)
é autoritativa no domínio/service, num lugar só. Por isso todos os campos são opcionais aqui.

Response: um envelope único (`faturamento_out`) serve POST e GET. No GET vêm preenchidos
segmento/rótulo da faixa; no POST esses campos podem vir null. Sem paginação: a lista de
marcadores traz sempre a matriz + todos os subgrupos (confirmado com o PO).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.domain.models import (
    Conglomerado,
    Faturamento,
    InfoFaturamento,
    MarcadorFaturamento,
    Origem,
)


class _Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


# ------ request do SALVAR (só parsing - sem regras) ------
class InfoIn(_Base):
    valor: Optional[Decimal] = None
    faixa_codigo: Optional[str] = None
    data_ref_balanco: Optional[str] = None
    moeda: Optional[str] = None
    unidade: Optional[str] = None
    id_spread: Optional[str] = None
    auditoria: Optional[str] = None
    valor_ativo: Optional[Decimal] = None


class MarcadorIn(_Base):
    subgrupo_doc: Optional[str] = None
    nome: Optional[str] = None
    id_spread: Optional[str] = None
    sistema_origem: Optional[str] = None
    confirmado_divergencia: bool = False
    sem_faturamento: bool = False
    justificativa: Optional[str] = None
    atual: Optional[InfoIn] = None
    faturamento_cra: Optional[InfoIn] = None


class FaturamentoRequest(_Base):
    conglomerado_doc: Optional[str] = None
    marcadores: list[MarcadorIn] = []

    def to_domain(self, documento: str, racf: Optional[str] = None) -> "Faturamento":
        """`racf` vem SEMPRE no header (responsabilização) e é carimbado em todos os marcadores."""
        cdoc = self.conglomerado_doc or documento
        marcadores = []
        for m in self.marcadores:
            atual = _in_to_info(
                m.atual,
                id_spread=m.id_spread,
                sistema_origem=m.sistema_origem,
                racf=racf,
            )
            cra = _in_to_info(m.faturamento_cra) if m.faturamento_cra else None
            marcadores.append(
                MarcadorFaturamento(
                    conglomerado_doc=cdoc,
                    subgrupo_doc=m.subgrupo_doc,
                    nome=m.nome,
                    atual=atual,
                    faturamento_cra=cra,
                    sem_faturamento=m.sem_faturamento,
                    justificativa=m.justificativa,
                    origem=Origem.MANUAL,
                    confirmado_divergencia=m.confirmado_divergencia,
                )
            )
        return Faturamento(conglomerado_doc=cdoc, marcadores=marcadores)


def _in_to_info(
    info_in: Optional[InfoIn],
    *,
    id_spread: Optional[str] = None,
    sistema_origem: Optional[str] = None,
    racf: Optional[str] = None,
) -> InfoFaturamento:
    """InfoIn (request) -> InfoFaturamento. `id_spread` do marcador tem prioridade; senão o do próprio info."""
    info = info_in or InfoIn()
    return InfoFaturamento(
        valor=info.valor,
        faixa_codigo=info.faixa_codigo,
        data_ref_balanco=info.data_ref_balanco,
        moeda=info.moeda,  # None -> service rejeita (moeda obrigatória) no atual
        unidade=info.unidade or "milhoes",
        id_spread=id_spread if id_spread is not None else info.id_spread,
        sistema_origem=sistema_origem,
        racf=racf,
        auditoria=info.auditoria,
        valor_ativo=info.valor_ativo,
    )


# ------ response (camelCase) - envelope único do POST e do GET ------
def _dec(v: Optional[Decimal]) -> Optional[str]:
    return None if v is None else format(v, "f")


def _info_out(info: Optional[InfoFaturamento]) -> Optional[dict]:
    if info is None:
        return None
    return {
        "valor": _dec(info.valor),
        "faixaCodigo": info.faixa_codigo,
        "faixaDescricao": info.faixa_descricao,
        "dataRefBalanco": info.data_ref_balanco,
        "moeda": info.moeda,
        "unidade": info.unidade,
        "idSpread": info.id_spread,  # "código spread" da grade de detalhe (tela 2/3)
        "racf": info.racf,  # coluna "Atualizado por" da tela — é o RACF mesmo, não um nome
        "auditoria": info.auditoria,
        "valorAtivo": _dec(info.valor_ativo),
    }


def _marcador_out(m: MarcadorFaturamento) -> dict:
    """Só o que a tela (telas 2/3 do CRA) consome. Controle (sistema_origem, aceite,
    quarentena, anterior, faturamento_cra) NÃO volta na API - segue persistido, mas não
    é exibição."""
    return {
        "nivel": m.nivel.value,
        "subgrupoDoc": m.subgrupo_doc,
        "nome": m.nome,
        "atual": _info_out(m.atual),
        "semFaturamento": m.sem_faturamento,  # "Não possuo o faturamento"
        "origem": m.origem.value,  # front mapeia o badge (CRA / Editado / Manual)
        "justificativa": m.justificativa,
        "atualizadoEm": m.atualizado_em,  # timestamp da última atualização
    }


def faturamento_out(f: Faturamento, persistido: bool = True) -> dict:
    return {
        "conglomeradoDoc": f.conglomerado_doc,
        "nomeGrupoEconomico": f.nome_grupo_economico,
        "segmento": f.segmento,
        "origemDados": "BASE" if persistido else "PREVIEW",
        "atualizadoEm": f.atualizado_em,
        "marcadores": [_marcador_out(m) for m in f.marcadores],
    }


def _grupo_out(g: Conglomerado) -> dict:
    """Item da busca "like" (autocomplete): só conglomerado + subgrupo (documento raiz) —
    sem participantes/pessoas, o front usa isso pra listar opções e depois chama
    `GET /faturamento/{conglomeradoDoc ou documento do subgrupo}` com a escolhida."""
    return {
        "nomeGrupoEconomico": g.nome_grupo_economico,
        "conglomeradoDoc": g.cabeca_documento_raiz,
        "segmento": g.segmento,
        "subgrupos": [
            {"nome": s.nome_subgrupo, "documento": s.cabeca_documento_raiz} for s in g.subgrupos
        ],
    }


def grupos_out(grupos: list[Conglomerado]) -> dict:
    return {"grupos": [_grupo_out(g) for g in grupos]}

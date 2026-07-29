""""Schemas Pydantic (camelCase) + mapeamento <-> domínio (SALVAR + BUSCAR).

Request (só SALVAR): Pydantic aqui SÓ parseia/tipa o JSON (camelCase) - NÃO valida shape
(campos obrigatórios, marcadores não-vazio, valor-ou-faixa). Toda validação (shape + negócio)
é autoritativa no domínio/service, num lugar só. Por isso todos os campos são opcionais aqui.

Response: um envelope único (`faturamento_out`) serve POST e GET. No GET vêm preenchidos
segmento/paginação/rótulo da faixa/passthrough; no POST esses campos podem vir null.
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


class MetadadosPorSubgrupoIn(_Base):
    """Metadados COMPARTILHADOS para todos os marcadores editados (naoFoiEditado=false).

    Fica no TOPO do FaturamentoRequest - não se repete por marcador.
    É ignorado para marcadores com naoFoiEditado=true (esses buscam do endpoint).
    """
    auditado: Optional[bool] = None
    original: Optional[bool] = None
    vigente: Optional[bool] = None


class MarcadorIn(_Base):
    subgrupo_doc: Optional[str] = None
    nome: Optional[str] = None
    id_spread: Optional[str] = None
    sistema_origem: Optional[str] = None
    confirmado_divergencia: bool = False
    sem_faturamento: bool = False
    justificativa: Optional[str] = None
    faturamento_modificado: bool = False  # True = foi editado, False = não foi editado
    atual: Optional[InfoIn] = None
    faturamento_cra: Optional[InfoIn] = None


class FaturamentoRequest(_Base):
    conglomerado_doc: Optional[str] = None
    metadados_por_subgrupo: Optional[MetadadosPorSubgrupoIn] = None # compartilhado (topo)
    marcadores: list[MarcadorIn] = []

    def to_domain(self, documento: str, racf: Optional[str] = None) -> "Faturamento":
        """`racf` vem SEMPRE no header (responsabilização) - carimbado em todos os marcadores."""
        cdoc = self.conglomerado_doc or documento
        marcadores = []
        for m in self.marcadores:
            atual = _in_to_info(m.atual, id_spread=m.id_spread, sistema_origem=m.sistema_origem, racf=racf)
            cra = _in_to_info(m.faturamento_cra) if m.faturamento_cra else None
            marcadores.append(MarcadorFaturamento(
                conglomerado_doc=cdoc,
                subgrupo_doc=m.subgrupo_doc,
                nome=m.nome,
                atual=atual,
                faturamento_cra=cra,
                sem_faturamento=m.sem_faturamento,
                justificativa=m.justificativa,
                origem=Origem.MANUAL,
                confirmado_divergencia=m.confirmado_divergencia,
                faturamento_modificado=m.faturamento_modificado,  # repassa ao domain
            ))
        return Faturamento(
            conglomerado_doc=cdoc,
            marcadores=marcadores,
            metadados_compartilhados=self.metadados_por_subgrupo,  # repassa ao domain
        )


def _in_to_info(info_in: Optional[InfoIn], *, id_spread: Optional[str] = None,
                sistema_origem: Optional[str] = None, racf: Optional[str] = None) -> InfoFaturamento:
    """InfoIn (request) -> InfoFaturamento. `id_spread` do marcador tem prioridade; senão o do próprio info."""
    info = info_in or InfoIn()
    return InfoFaturamento(
        valor=info.valor,
        faixa_codigo=info.faixa_codigo,
        data_ref_balanco=info.data_ref_balanco,
        moeda=info.moeda,               # None -> service rejeita (moeda obrigatória) no atual
        unidade=info.unidade or "milhoes",
        id_spread=id_spread if id_spread is not None else info.id_spread,
        sistema_origem=sistema_origem,
        racf=racf,
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
    }


def _marcador_out(m: MarcadorFaturamento) -> dict:
    """Só o que a tela (telas 2/3 do CRA) consome. Auditoria/controle (racf, sistema_origem,
    aceite, quarentena, anterior) NÃO voltam na API - seguem persistidos, mas não são exibição."""
    return {
        "nivel": m.nivel.value,
        "subgrupoDoc": m.subgrupo_doc,
        "nome": m.nome,
        "atual": _info_out(m.atual),
        "faturamentoCra": _info_out(m.faturamento_cra),  # referência do modal "editar faturamento"
        "semFaturamento": m.sem_faturamento,             # "Não possuo o faturamento"
        "origem": m.origem.value,                        # front mapeia o badge (CRA / Editado / Manual)
        "justificativa": m.justificativa,
        "atualizadoEm": m.atualizado_em,                 # timestamp da última atualização
        # passthrough do CRA (grade de detalhe das telas 2/3):
        "nomeSpread": m.nome_spread,
        "arquivo": m.arquivo,
        "status": m.status,
        "categoria": m.categoria,
    }


def _paginacao_out(f: Faturamento) -> Optional[dict]:
    p = f.paginacao
    if p is None:
        return None
    return {
        "limit": p.limit,
        "offset": p.offset,
        "total": p.total,
        "proximoCursor": p.proximo_cursor,
        "temMais": p.tem_mais,
    }


def faturamento_out(f: Faturamento, persistido: bool = True) -> dict:
    return {
        "conglomeradoDoc": f.conglomerado_doc,
        "nomeGrupoEconomico": f.nome_grupo_economico,
        "segmento": f.segmento,
        "origemDados": "BASE" if persistido else "PREVIEW",
        "atualizadoEm": f.atualizado_em,
        "paginacao": _paginacao_out(f),
        "marcadores": [_marcador_out(m) for m in f.marcadores],
    }


def conglomerado_out(c: Conglomerado) -> dict:
    """GET /conglomerados/{documento}/subgrupos - hierarquia crua (tabela de integrantes da tela 2)."""
    from app.core.logging import get_logger, log_event
    logger = get_logger("faturamento.schemas")

    try:
        log_event(logger, "conglomerado_out.inicio", level="debug",
                  nome_grupo=c.nome_grupo_economico, qtd_subgrupos=len(c.subgrupos))

        subgrupos_out = []
        for i, s in enumerate(c.subgrupos):
            try:
                participantes_out = [
                    {
                        "documentoRaiz": p.documento_raiz,
                        "codigoIdentificacaoPessoa": p.codigo_identificacao_pessoa,
                        "codigoTipoPessoa": p.codigo_tipo_pessoa,
                        "indicadorEstrangeiro": p.indicador_estrangeiro,
                    }
                    for p in s.participantes
                ]
                subgrupo_out = {
                    "nomeSubgrupo": s.nome_subgrupo,
                    "cabecaDocumentoRaiz": s.cabeca_documento_raiz,
                    "codigoGrupoClienteAtacado": s.codigo_grupo_cliente_atacado,
                    "participantes": participantes_out,
                }
                subgrupos_out.append(subgrupo_out)
                log_event(logger, "conglomerado_out.subgrupo_ok", level="debug",
                          idx=i, nome=s.nome_subgrupo, qtd_participantes=len(participantes_out))
            except Exception as e:
                logger.exception("conglomerado_out.erro_subgrupo",
                                 extra={"ctx": {
                                     "event": "conglomerado_out.erro_subgrupo",
                                     "idx": i,
                                     "tipo_erro": type(e).__name__,
                                     "mensagem": str(e),
                                     "nome_subgrupo": s.nome_subgrupo
                                 }})
                raise

        result = {
            "nomeGrupoEconomico": c.nome_grupo_economico,
            "cabecaDocumentoRaiz": c.cabeca_documento_raiz,
            "segmento": c.segmento,
            "subgrupos": subgrupos_out,
        }
        log_event(logger, "conglomerado_out.sucesso", level="debug")
        return result
    except Exception as e:
        logger.exception("conglomerado_out.erro_fatal",
                         extra={"ctx": {
                             "event": "conglomerado_out.erro_fatal",
                             "tipo_erro": type(e).__name__,
                             "mensagem": str(e)
                         }})
        raise
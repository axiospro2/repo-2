"""Adapter DynamoDB — escrita do SALVAR + leitura do BUSCAR.

Layout (nova tabela `tbcv4163_fatm_cogl_subg`):
  cod_cogl = <conglomerado_doc>   (HASH key)
  cod_subg = <subgrupo_doc>       (RANGE key)

  Um item por (conglomerado, subgrupo) — upsert incremental.
  Sem SPREAD# snapshots (a nova tabela não suporta multi-item por subgrupo).
  Sem GSI.

save() é INCREMENTAL (upsert): grava/atualiza só os marcadores presentes no payload,
fazendo o roll "hoje vira ontem" em cada um. NUNCA apaga um subgrupo por ele estar ausente
do payload — o analista preenche a carteira aos poucos.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key

from app.core.logging import get_logger, log_event
from app.core.settings import settings
from app.domain.models import Faturamento, InfoFaturamento, MarcadorFaturamento, Nivel, Origem

_logger = get_logger("faturamento.repository")


def _clean(item: dict) -> dict:
    """Remove chaves None (DynamoDB não aceita atributos nulos em put)."""
    return {k: v for k, v in item.items() if v is not None}


def _info_to_map(info: Optional[InfoFaturamento]) -> Optional[dict]:
    if info is None:
        return None
    return _clean({
        "valor": info.valor,
        "faixa_codigo": info.faixa_codigo,
        "data_ref_balanco": info.data_ref_balanco,
        "moeda": info.moeda,
        "unidade": info.unidade,
        "id_spread": info.id_spread,
        "sistema_origem": info.sistema_origem,
        "racf": info.racf,
        "auditoria": info.auditoria,
        "valor_ativo": info.valor_ativo,
    })


def _info_from_map(m: Optional[dict]) -> InfoFaturamento:
    m = m or {}
    valor = m.get("valor")
    valor_ativo = m.get("valor_ativo")
    return InfoFaturamento(
        valor=Decimal(str(valor)) if valor is not None else None,
        faixa_codigo=m.get("faixa_codigo"),
        data_ref_balanco=m.get("data_ref_balanco"),
        moeda=m.get("moeda", "BRL"),
        unidade=m.get("unidade", "milhoes"),
        id_spread=m.get("id_spread"),
        sistema_origem=m.get("sistema_origem"),
        racf=m.get("racf"),
        auditoria=m.get("auditoria"),
        valor_ativo=Decimal(str(valor_ativo)) if valor_ativo is not None else None,
    )


class DynamoRepository:
    def __init__(self, table_name: Optional[str] = None, dynamodb=None):
        self._ddb = dynamodb or boto3.resource("dynamodb")
        self.table = self._ddb.Table(table_name or settings.tabela_faturamento)

    # ─────────── leitura ───────────

    def get_subgrupo(
        self, conglomerado_doc: str, subgrupo_doc: str
    ) -> Optional[MarcadorFaturamento]:
        resp = self.table.get_item(
            Key={
                "cod_cogl": conglomerado_doc,
                "cod_subg": subgrupo_doc,
            }
        )
        it = resp.get("Item")
        return self._item_to_marcador(it) if it else None

    def get_conglomerado(self, conglomerado_doc: str) -> list[MarcadorFaturamento]:
        """BUSCAR: todos os marcadores do conglomerado (um item por subgrupo)."""
        itens = self._query_conglomerado(conglomerado_doc)
        log_event(
            _logger,
            "dynamo.query",
            level="debug",
            conglomerado_doc=conglomerado_doc,
            itens=len(itens),
        )
        return [self._item_to_marcador(it) for it in itens]

    # ─────────── escrita ───────────

    def save(self, f: Faturamento) -> None:
        """Upsert incremental: grava só os marcadores do payload; nunca apaga o que não veio."""
        # Carrega os "atual" já salvos para fazer o roll hoje→ontem
        atual_por_subg = {
            it["cod_subg"]: it.get("atual") for it in self._query_conglomerado(f.conglomerado_doc)
        }

        with self.table.batch_writer() as bw:
            for m in f.marcadores:
                bw.put_item(Item=self._build_item(f, m, atual_por_subg))

        log_event(
            _logger,
            "dynamo.save",
            level="debug",
            conglomerado_doc=f.conglomerado_doc,
            upserted=len(f.marcadores),
        )

    def _query_conglomerado(self, conglomerado_doc: str) -> list[dict]:
        return self.table.query(KeyConditionExpression=Key("cod_cogl").eq(conglomerado_doc)).get(
            "Items", []
        )

    # ─────────── mapeamento domínio ↔ item ───────────

    def _build_item(self, f: Faturamento, m: MarcadorFaturamento, atual_por_subg: dict) -> dict:
        anterior = _info_to_map(m.anterior)
        if anterior is None:
            anterior = atual_por_subg.get(m.subgrupo_doc)  # roll: atual salvo vira anterior novo
        return _clean({
            "cod_cogl": f.conglomerado_doc,
            "cod_subg": m.subgrupo_doc,
            "nivel": m.nivel.value,
            "conglomerado_doc": f.conglomerado_doc,
            "subgrupo_doc": m.subgrupo_doc,
            "nome": m.nome,
            "atual": _info_to_map(m.atual),
            "anterior": anterior,
            "faturamento_cra": _info_to_map(m.faturamento_cra),
            "sem_faturamento": m.sem_faturamento,
            "justificativa": m.justificativa,
            "origem": m.origem.value,
            "aceite": m.aceite,
            "atualizado_em": f.atualizado_em,
            "quarentena": m.quarentena,
            "quarentena_desde": m.quarentena_desde,
        })

    def _item_to_marcador(self, it: dict) -> MarcadorFaturamento:
        anterior = it.get("anterior")
        cra = it.get("faturamento_cra")
        return MarcadorFaturamento(
            conglomerado_doc=it["conglomerado_doc"],
            subgrupo_doc=it["subgrupo_doc"],
            nivel=Nivel(it.get("nivel", "SUBGRUPO")),
            nome=it.get("nome"),
            atual=_info_from_map(it.get("atual")),
            anterior=_info_from_map(anterior) if anterior else None,
            faturamento_cra=_info_from_map(cra) if cra else None,
            sem_faturamento=bool(it.get("sem_faturamento", False)),
            justificativa=it.get("justificativa"),
            origem=Origem(it.get("origem", "MANUAL")),
            aceite=bool(it.get("aceite", False)),
            quarentena=bool(it.get("quarentena", False)),
            quarentena_desde=it.get("quarentena_desde"),
            atualizado_em=it.get("atualizado_em"),
        )

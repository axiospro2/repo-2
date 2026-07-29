"""Regra de negócio do SALVAR. Depende só do repositório e de um snapshot de parâmetros.

NÃO depende de NJ6/Endpoint (caminho de leitura — ver `service_buscar.py`). Emite eventos de
NEGÓCIO para o Datadog (divergência barrada, faturamento persistido) — sem ruído.

naoFoiEditado=true → busca o endpoint pra extrair auditado/original/vigente automaticamente.
naoFoiEditado=false → usa metadados_compartilhados vindos do topo do JSON (todos os marcadores
editados na mesma tela compartilham os mesmos metadados).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from app.core.logging import get_logger, log_event
from app.domain import divergencia
from app.domain.errors import ConfirmacaoNecessaria, ErroValidacao, FaixaObrigatoria
from app.domain.faixa import de_para_valor_para_faixa
from app.domain.models import Faturamento, InfoFaturamento, MarcadorFaturamento, Nivel, Origem

_logger = get_logger("faturamento.service")


class Repositorio(Protocol):
    def get_subgrupo(self, conglomerado_doc: str, subgrupo_doc: str) -> Optional[MarcadorFaturamento]: ...
    def save(self, f: Faturamento) -> None: ...


def salvar(
    fat: Faturamento,
    repo: Repositorio,
    params: dict,
    endpoint=None,
    metadados_compartilhados=None,
) -> Faturamento:
    """Valida e grava o agregado.

    `params` = snapshot do serviço de parâmetros.
    `endpoint` = client do Endpoint de Faturamento (necessário para naoFoiEditado=true).
    `metadados_compartilhados` = objeto com auditado/original/vigente vindo do topo do JSON.
    """
    if not fat.marcadores:
        raise ErroValidacao("Nenhum marcador informado para classificar.")

    faixas = params.get("faixas") or []
    moedas = {m.upper() for m in (params.get("moedas") or [])}

    # ────── pré-processamento: resolve metadados antes de validar ──────
    for m in fat.marcadores:
        _resolver_metadados(m, endpoint, metadados_compartilhados)

    divergencias: list[dict] = []
    for m in fat.marcadores:
        _normalizar(m, fat)
        _validar_marcador(m, faixas)
        _validar_moeda(m, moedas)
        divergencias.extend(_avaliar_gate(m, fat, repo, params))

    if divergencias:
        log_event(_logger, "faturamento.divergencia_barrada", level="warning",
                  conglomerado_doc=fat.conglomerado_doc, qtd_divergencias=len(divergencias))
        raise ConfirmacaoNecessaria(divergencias)

    fat.atualizado_em = _agora()
    repo.save(fat)
    _log_persistido(fat)
    return fat

# ────── metadados ──────

def _resolver_metadados(
    m: MarcadorFaturamento,
    endpoint,
    metadados_compartilhados,
) -> None:
    """Resolve auditado/original/vigente/data_atualizacao no marcador antes de gravar.

    - naoFoiEditado=True: busca o endpoint e extrai os metadados de lá.
    - naoFoiEditado=False: usa os metadados_compartilhados do topo do JSON.
    """
    agora = _agora()

    if m.nao_foi_editado and endpoint is not None:
        resultado = endpoint.buscar(m.subgrupo_doc)
        if resultado is not None:
            log_event(_logger, "faturamento.salvar.nao_foi_editado_endpoint_encontrado",
                      subgrupo=m.subgrupo_doc, valor_endpoint=resultado.valor_faturamento)
            m.atual.auditado = True      # dado do endpoint = auditado por padrão
            m.atual.original = True      # dado do endpoint = original (não ponderado)
            m.atual.vigente = True       # dado do endpoint = vigente
        else:
            log_event(_logger, "faturamento.salvar.nao_foi_editado_endpoint_nao_encontrado",
                      subgrupo=m.subgrupo_doc)
            # sem metadados -> ficam None (não valida R1/R2/R3 no buscar)
    else:
        # foi editado na tela -> usa metadados compartilhados do topo
        if metadados_compartilhados is not None:
            m.atual.auditado = metadados_compartilhados.auditado
            m.atual.original = metadados_compartilhados.original
            m.atual.vigente = metadados_compartilhados.vigente
            log_event(_logger, "faturamento.salvar.foi_editado",
                      subgrupo=m.subgrupo_doc,
                      auditado=m.atual.auditado,
                      original=m.atual.original,
                      vigente=m.atual.vigente)

    m.atual.data_atualizacao = agora

# ────── etapas ──────

def _normalizar(m: MarcadorFaturamento, fat: Faturamento) -> None:
    """Coerência da chave: todo marcador pertence ao conglomerado do agregado."""
    m.conglomerado_doc = fat.conglomerado_doc
    m.nivel = Nivel.CONGLOMERADO if m.e_matriz else Nivel.SUBGRUPO
    m.origem = Origem.BASE  # gravar na nossa base => o dado passa a ser BASE


def _validar_marcador(m: MarcadorFaturamento, faixas: list[dict]) -> None:
    """De-para automático valor→faixa; faixa obrigatória se não houver valor específico."""
    if not m.subgrupo_doc:
        raise ErroValidacao("subgrupoDoc obrigatório no marcador.")
    if m.sem_faturamento:
        m.atual.valor = None       # "Não possuo o faturamento": sem valor e sem faixa, sem de-para
        m.atual.faixa_codigo = None
        return
    if not faixas:
        raise ErroValidacao("Catálogo de faixas indisponível no serviço de parâmetros.")

    info = m.atual
    if info.valor is not None:
        faixa = de_para_valor_para_faixa(info.valor, faixas)
        if faixa is None:
            raise ErroValidacao(f"Valor {info.valor} fora das faixas conhecidas.")
        info.faixa_codigo = faixa
    elif not info.faixa_codigo:
        raise FaixaObrigatoria(f"Subgrupo {m.subgrupo_doc}: informe valor específico ou faixa.")


def _validar_moeda(m: MarcadorFaturamento, moedas: set[str]) -> None:
    """Moeda obrigatória e presente no catálogo de parâmetros."""
    if m.sem_faturamento:
        return  # sem valor -> moeda não se aplica
    moeda = m.atual.moeda
    if not moeda:
        raise ErroValidacao(f"Moeda obrigatória para o subgrupo {m.subgrupo_doc}.")
    if not moedas:
        raise ErroValidacao("Catálogo de moedas indisponível no serviço de parâmetros.")
    if moeda.upper() not in moedas:
        raise ErroValidacao(f"Moeda inválida ({moeda}) para o subgrupo {m.subgrupo_doc}.")


def _avaliar_gate(m: MarcadorFaturamento, fat: Faturamento, repo: Repositorio, params: dict) -> list[dict]:
    """Gate de divergência (síncrono, ANTES de gravar): compara com o que já está salvo."""
    gate_ativo = bool(params.get("gateDivergenciaAtivo", False))
    if not gate_ativo or m.confirmado_divergencia:
        return []
    existente = repo.get_subgrupo(fat.conglomerado_doc, m.subgrupo_doc)
    if existente is None:
        return []
    limite_pct = int(params.get("limiteVariacaoPercentual", 0))
    return divergencia.avaliar(m, existente, limite_pct)

# ────── internos ──────

def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log_persistido(fat: Faturamento) -> None:
    log_event(_logger, "faturamento.persistido",
              conglomerado_doc=fat.conglomerado_doc,
              qtd_marcadores=len(fat.marcadores),
              snapshots_spread=sum(1 for m in fat.marcadores if m.atual and m.atual.id_spread),
              sistemas_origem=sorted(
                  {m.atual.sistema_origem for m in fat.marcadores if m.atual and m.atual.sistema_origem}))

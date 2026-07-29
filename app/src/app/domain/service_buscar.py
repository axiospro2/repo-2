"""Regra de negócio do BUSCAR (read-through). Depende dos portos NJ6, Endpoint e Repositório.

Módulo irmão de `service.py` (SALVAR) – mesma Lambda, dois caminhos. Fica separado para não
misturar os protocolos de repositório (leitura x escrita) nem as dependências (o salvar NÃO
usa NJ6/Endpoint).

Fluxo (GET /faturamento/{documento}):

1. NJ6 resolve o conglomerado (e subgrupos) a partir do documento (CPF/CNPJ/CGF).
2. Busca o endpoint para TODOS os subgrupos em PARALELO (ThreadPoolExecutor).
3. Para cada alvo:
   a. Valida banco com regras R1/R2/R3 (auditado/original/vigente + idade <= 24m).
   b. Se banco É endpoint valem: desempata pelo mais recente (data_ref_balanço).
   c. Se só um vale: usa esse.
   d. Se nenhum vale: MANUAL.
4. Quarentena: se em quarentena e tem 'anterior', elege o 'anterior'.
5. Enriquece a faixa com o rótulo (descrição) do catálogo de parâmetros.

`aba` (Lógica inversa do repasse):
   - "CONGLOMERADO" (default): lista os N subgrupos (marcadores SUBGRUPO) – paginável.
   - "SUBGRUPO": traz 1 linha – a matriz (marcador CONGLOMERADO).

Emite eventos de NEGÓCIO/TÉCNICO pro Datadog. NÃO grava nada (é só leitura).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime
from typing import Optional, Protocol

from app.core.logging import get_logger, log_event
from app.domain.errors import ErroValidacao
from app.domain.faixa import de_para_valor_para_faixa, descricao_da_faixa
from app.domain.models import (
    Conglomerado,
    Faturamento,
    InfoFaturamento,
    MarcadorFaturamento,
    Nivel,
    Origem,
    Paginacao,
)


_logger = get_logger("faturamento.buscar")


LIMIT_PADRAO = 10
LIMIT_MAXIMO = 100
_CURSOR_PREFIXO = "off"
_MAX_WORKERS = 10    # limite de threads paralelas ao endpoint




class Repositorio(Protocol):
    def get_conglomerado(self, conglomerado_doc: str) -> list[MarcadorFaturamento]: ...




class NJ6(Protocol):
    def get_por_documento(self, documento: str) -> Conglomerado: ...




class Endpoint(Protocol):
    def buscar(self, documento_raiz: str, asof: Optional[str] = None): ...




class Catalogo(Protocol):
    def obter(self) -> dict: ...




def obter_faturamento(
    documento: str,
    aba: Optional[str],
    repo: Repositorio,
    nj6: NJ6,
    endpoint: Endpoint,
    catalogo: Catalogo,
    limit: int = LIMIT_PADRAO,
    cursor: Optional[str] = None,
) -> Faturamento:
    """Read-through por documento com chamadas ao endpoint em PARALELO."""
    cong = nj6.get_por_documento(documento)
    cdoc = cong.cabeca_documento_raiz
    salvos_por_sub = {m.subgrupo_doc: m for m in repo.get_conglomerado(cdoc)}
    faixas = (Catalogo.obter() or {}).get("faixas") or []


    alvos, paginacao = _alvos_da_aba(cong, aba, limit, cursor)


    # busca o endpoint para todos os alvos em paralelo antes do loop
    resultados_endpoint = _buscar_endpoint_paralelo(
        [doc for (_, doc, _) in alvos], endpoint
    )



    marcadores = [
        _resolvedor_marcador(
            nivel, cdoc, doc, nome,
            salvos_por_sub.get(doc),
            resultados_endpoint.get(doc),
            faixas,
        )
        for (nivel, doc, nome) in alvos
    ]

    _log_resolucao(cdoc, aba, marcadores)
    return Faturamento(
        conglomerado_doc=cdoc,
        nome_grupo_economico=cong.nome_grupo_economico,
        segmento=cong.segmento,
        marcadores=marcadores,
        paginacao=paginacao,
    )


    

def listar_subgrupos(documento: str, nj6: NJ6) -> Conglomerado:
    """GET /conglomerados/{documento}/subgrupos — hierarquia crua do NJ6 (tabela de integrantes)."""
    try:
        log_event(_logger, "service.listar_subgrupos.inicio", level="debug", documento=documento)
        cong = nj6.get_por_documento(documento)
        log_event(_logger, "service.listar_subgrupos.sucesso", level="debug",
            documento=documento, gtd_subgrupos=len(cong.subgrupos),
            nome_grupo=cong.nome_grupo_economico)
        return cong
    except Exception as e:
        _logger.exception("service.listar_subgrupos.erro",
            extra={"ctx": {
                "event": "service.listar_subgrupos.erro",
                "documento": documento,
                "tipo_erro": type(e).__name__,
                "mensagem": str(e)
            }})
        raise


# —————— chamadas paralelas ao endpoint ——————


def _buscar_endpoint_paralelo(docs: list[str], endpoint: Endpoint) -> dict[str, object]:
    """Busca o endpoint para vários subgrupos em PARALELO.

    Retorna dict { subgrupo_doc → ResultadoFaturamento | None }.
    Erros em 1 subgrupo NÃO derrubam os outros — tratado individualmente.
    """
    resultados: dict[str, object] = {}
    if not docs:
        return resultados

    workers = min(_MAX_WORKERS, len(docs))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuro_para_doc = {
            executor.submit(endpoint.buscar, doc): doc
            for doc in docs
        }
        for futuro in as_completed(futuro_para_doc):
            doc = futuro_para_doc[futuro]
            try:
                resultados[doc] = futuro.result()
            except Exception as exc:
                log_event(_logger, "faturamento.buscar.endpoint_erro_paralelo",
                    level="warning", subgrupo=doc, erro=str(exc))
                resultados[doc] = None


    return resultados


# —————— validação R1/R2/R3 no banco ——————


def _valida_regras_banco(marcador: MarcadorFaturamento) -> bool:
    """Retorna True se o marcador do banco passa em R1, R2 ou R3 (cascata).

    Sem histórico: valida 1 valor + metadados + idade <= 24 meses.
    """
    if marcador.quarentena:
        return False


    info = marcador.atual
    if not _dentro_da_janela_idade(info.data_atualizacao):
        return False


    # R1: auditado + original + vigente
    if info.auditado is True and info.original is True and info.vigente is True:
        return True
    # R2: auditado + vigente
    if info.auditado is True and info.vigente is True:
        return True
    # R3: original + vigente
    if info.original is True and info.vigente is True:
        return True


    return False




def _qual_regra_passou(marcador: MarcadorFaturamento) -> Optional[str]:
    """Retorna 'R1', 'R2', 'R3' ou None — útil no log do Datadog."""

    info = marcador.atual
    if marcador.quarentena or not _dentro_da_janela_idade(info.data_atualizacao):
        return None


    if info.auditado is True and info.original is True and info.vigente is True:
        return "R1"
    if info.auditado is True and info.vigente is True:
        return "R2"
    if info.original is True and info.vigente is True:
        return "R3"
    return None




def _dentro_da_janela_idade(data_atualizacao: Optional[str]) -> bool:
    """True se data_atualizacao está dentro de 24 meses a partir de hoje."""


    if not data_atualizacao:
        return False
    try:
        data_upd = datetime.fromisoformat(
            data_atualizacao.replace("Z", "+00:00")
        ).date()
        hoje = date.today()
        meses = (hoje.year - data_upd.year) * 12 + (hoje.month - data_upd.month)
        return meses <= 24
    except (ValueError, AttributeError):
        return False




# —————— resolução de 1 marcador (banco → endpoint → manual) ——————


def _resolvedor_marcador(
    nivel: Nivel,
    cdoc: str, sdoc: str,
    nome: Optional[str],
    salvo: Optional[MarcadorFaturamento],
    resultado_endpoint: object,   # já resolvido pelo paralelo
    faixas: list[dict],
) -> MarcadorFaturamento:
    """Resolve 1 marcador com validação R1/R2/R3 + desempate por data.

    Ordem de prioridade:
    1. Quarentena: se banco está em quarentena com anterior válido → usa anterior, sem validar regras
    2. Banco válido (R1/R2/R3 + idade) vs Endpoint → desempata pelo data mais recente
    3. Só banco → usa banco
    4. Só endpoint → usa endpoint
    5. Nenhum → MANUAL
    """


    # 1. Quarentena tem prioridade absoluta — não valida R1/R2/R3
    if salvo is not None and salvo.quarentena:
        log_event(_logger, "faturamento.buscar.quarentena", subgrupo=sdoc)
        m = _aplicar_quarentena(salvo)
        _enriquecer_faixa(m, faixas)
        return m


    banco_valido = salvo is not None and not salvo.atual.vazio and _valida_regras_banco(salvo)
    endpoint_valido = resultado_endpoint is not None


    if banco_valido and endpoint_valido:
        # Ambos vâlem → desempata pelo mais recente
        data_banco    = salvo.atual.data_ref_balanco or "1900-01-01"
        data_endpoint = resultado_endpoint.data_ref_balanco or "1900-01-01"
        if data_banco >= data_endpoint:
            log_event(_logger, "faturamento.buscar.desempate_banco_vence",
                subgrupo=sdoc, data_banco=data_banco, data_endpoint=data_endpoint,
                regra=_qual_regra_passou(salvo))
            m = salvo
        else:
            log_event(_logger, "faturamento.buscar.desempate_endpoint_vence",
                subgrupo=sdoc, data_banco=data_banco, data_endpoint=data_endpoint)
            m = _marcador_do_endpoint(cdoc, sdoc, nivel, nome, resultado_endpoint, faixas)


    elif banco_valido:
        log_event(_logger, "faturamento.buscar.banco_valido_sozinho",
            subgrupo=sdoc, regra=_qual_regra_passou(salvo))
        m = salvo


    elif endpoint_valido:
        log_event(_logger, "faturamento.buscar.endpoint_valido_sozinho", subgrupo=sdoc)
        m = _marcador_do_endpoint(cdoc, sdoc, nivel, nome, resultado_endpoint, faixas)


    else:
        log_event(_logger, "faturamento.buscar.nenhum_valido_manual", subgrupo=sdoc)
        m = MarcadorFaturamento(
            conglomerado_doc=cdoc, subgrupo_doc=sdoc,
            nivel=nivel, nome=nome, origem=Origem.MANUAL,
        )


    _enriquecer_faixa(m, faixas)
    return m




def _marcador_do_endpoint(
    cdoc: str, sdoc: str, nivel: Nivel, nome: Optional[str],
    res, faixas: list[dict],
) -> MarcadorFaturamento:
    """Cria MarcadorFaturamento a partir do resultado do endpoint."""
    m = MarcadorFaturamento(
        conglomerado_doc=cdoc, subgrupo_doc=sdoc, nivel=nivel, nome=nome,
        atual=InfoFaturamento(
            valor=res.valor_faturamento,
            faixa_codigo=de_para_valor_para_faixa(res.valor_faturamento, faixas),
            data_ref_balanco=res.data_ref_balanco,
            moeda=res.moeda or "BRL",
            unidade=res.unidade or "milhoes",
            id_spread=res.id_spread,
            sistema_origem=res.sistema_origem,
        ),
        origem=Origem.ENDPOINT,
        aceite=False,
    )
    m.faturamento_cra = replace(m.atual)
    return m


def _aplicar_quarentena(m: MarcadorFaturamento) -> MarcadorFaturamento:
    """Se em quarentena e há `anterior` não-vazio, elege o `anterior` como valor vigente."""
    if m.quarentena and m.anterior is not None and not m.anterior.vazio:
        return replace(m, atual=m.anterior, em_quarentena=True)
    return m

def _enriquecer_faixa(m: MarcadorFaturamento, faixas: list[dict]) -> None:
    """Preenche o rótulo (descrição) da faixa vigente para a tela exibir."""
    for info in (m.atual, m.anterior, m.faturamento_cra):
        if info is not None:
            info.faixa_descricao = descricao_da_faixa(info.faixa_codigo, faixas)

# ────── alvos por aba ──────

def _alvos_da_aba(
    cong: Conglomerado, aba: Optional[str], limit: int, cursor: Optional[str]
) -> tuple[list[tuple[Nivel, str, Optional[str]]], Optional[Paginacao]]:
    if _aba_subgrupo(aba):
        matriz = (Nivel.CONGLOMERADO, cong.cabeca_documento_raiz, cong.nome_grupo_economico)
        return [matriz], None
    return _paginar(_subgrupos_unicos(cong), limit, cursor)

def _aba_subgrupo(aba: Optional[str]) -> bool:
    return (aba or "CONGLOMERADO").upper() == "SUBGRUPO"

def _subgrupos_unicos(cong: Conglomerado) -> list[tuple[Nivel, str, Optional[str]]]:
    alvos: list[tuple[Nivel, str, Optional[str]]] = []
    vistos: set[str] = set()
    for sub in cong.subgrupos:
        doc = sub.cabeca_documento_raiz
        if doc not in vistos:
            vistos.add(doc)
            alvos.append((Nivel.SUBGRUPO, doc, sub.nome_subgrupo))

    return alvos

# ────── paginação (cursor opaco = offset) ──────

def _paginar(todos: list, limit: int, cursor: Optional[str]) -> tuple[list, Paginacao]:
    limit = max(1, min(int(limit or LIMIT_PADRAO), LIMIT_MAXIMO))
    offset = _decode_cursor(cursor)
    total = len(todos)
    proximo = offset + limit
    return todos[offset:proximo], Paginacao(
        limit=limit,
        total=total,
        offset=offset,
        proximo_cursor=_encode_cursor(proximo) if proximo < total else None,
)

def _encode_cursor(offset: int) -> str:
    return f"{_CURSOR_PREFIXO}:{offset}"

def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        prefixo, _, valor = cursor.partition(":")
        if prefixo != _CURSOR_PREFIXO:
            raise ValueError
        offset = int(valor)
        if offset < 0:
            raise ValueError
        return offset
    except ValueError:
        raise ErroValidacao(f"Cursor de paginação inválido: {cursor!r}.")

# ----------- agregado -----------

def _log_resolucao(cdoc: str, aba: Optional[str], marcadores: list[MarcadorFaturamento]) -> None:
    por_origem = {origem: sum(1 for m in marcadores if m.origem == origem) for origem in Origem}
    log_event(
        _logger, "faturamento.buscar.resolvido",
        conglomerado_doc=cdoc,
        aba="SUBGRUPO" if _aba_subgrupo(aba) else "CONGLOMERADO",
        qtd_marcadores=len(marcadores),
        origem_dados="BASE" if por_origem[Origem.BASE] else "PREVIEW",
        endpoint=por_origem[Origem.ENDPOINT],
        manual=por_origem[Origem.MANUAL],
        origem_dados="BASE" if por_origem[Origem.BASE] else "PREVIEW",
        base=por_origem[Origem.BASE],
        endpoint=por_origem[Origem.ENDPOINT],
        manual=por_origem[Origem.MANUAL],
        origem_dados="BASE" if por_origem[Origem.BASE] else "PREVIEW",
)

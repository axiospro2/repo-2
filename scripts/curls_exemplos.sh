#!/usr/bin/env bash
# Exemplos de curl para os dois fluxos da API (SALVAR e BUSCAR).
# Pré-requisito: stack local no ar (ver SETUP.md) — mocks em :8080, app em :8000.
#
# Uso:
#   ./scripts/curls_exemplos.sh buscar
#   ./scripts/curls_exemplos.sh salvar
#
# BASE_URL/DOCUMENTO podem ser sobrescritos por variável de ambiente.
#
# Não existe mais rota separada de hierarquia (GET /conglomerados/{documento}/subgrupos)
# — foi removida: o GET /faturamento/{documento} já resolve a hierarquia do NJ6 por
# dentro e devolve matriz + subgrupos numa lista só.
#
# Mais CNPJs pra testar variações (cascata R1/R2/R3, subgrupo sem dado no Endpoint,
# 16 subgrupos no limite, moeda/unidade diferentes, dedup de subgrupo etc.):
# ver docs/CASOS_TESTE_MOCK.md (20 casos, documentos 900001000..900020000).

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
DOCUMENTO="${DOCUMENTO:-050746577}"

buscar_faturamento() {
  # GET /faturamento/{documento}
  # Fluxo agregado: NJ6 (hierarquia matriz+subgrupos) + banco (valores já salvos)
  # + Endpoint (fallback pra quem não tem nada salvo) -> lista única deduplicada
  # por documento_raiz. Banco sempre vence quando tem valor salvo (não revalida
  # contra o Endpoint).
  curl -sS -X GET \
    "${BASE_URL}/irb-cra-faturamento/v1/faturamento/${DOCUMENTO}" \
    -H "Accept: application/json" \
    | python3 -m json.tool
}

salvar_faturamento() {
  # POST /faturamento/{documento}
  # RACF de quem informou vai SEMPRE no header (responsabilização) — é o mesmo RACF
  # que volta no GET como "atualizado por" (não tem campo de nome no request nem na
  # resposta, só RACF mesmo). Tela única (sem abas): o POST manda a MATRIZ + TODOS
  # os subgrupos juntos, num array só de "marcadores".
  #
  # Como identificar cada marcador (não tem campo "nivel" no body — é implícito):
  #   - matriz   → subgrupoDoc == o documento do path (é o "e_matriz" do domínio)
  #   - subgrupo → subgrupoDoc é o documento_raiz do subgrupo (mesmo valor que sai
  #     em "subgrupoDoc" no GET /faturamento/{documento})
  #
  # Cada marcador é independente: pode ter valor preenchido, "semFaturamento", ou
  # confirmar uma divergência (confirmadoDivergencia) — não precisa ser tudo no
  # mesmo estado no mesmo POST.
  #
  # `faixaCodigo` (modo "por faixa") tem que ser um código do catálogo real
  # (ate_360_mil, 360_mil_4_8_mm, 4_8_mm_20_mm, 20_mm_125_mm, 125_mm_300_mm,
  # 300_mm_500_mm, 500_mm_1_bi, 1_bi_2_5_bi, 2_5_bi_5_bi, 5_bi_10_bi, acima_10_bi)
  # — ver `adapters/parametros.py::_FAIXAS_FALLBACK`. Quando `valor` vem preenchido,
  # o backend recalcula a faixa a partir dele e ignora o `faixaCodigo` enviado.
  curl -sS -X POST \
    "${BASE_URL}/irb-cra-faturamento/v1/faturamento/${DOCUMENTO}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "X-RACF: A123456" \
    -d '{
      "conglomeradoDoc": "'"${DOCUMENTO}"'",
      "marcadores": [
        {
          "subgrupoDoc": "'"${DOCUMENTO}"'",
          "nome": "COSAN S A",
          "idSpread": "2097",
          "sistemaOrigem": "MANUAL",
          "semFaturamento": false,
          "confirmadoDivergencia": false,
          "justificativa": "Valor confirmado com o cliente em contato telefônico.",
          "atual": {
            "valor": 15000000.00,
            "dataRefBalanco": "2024-12-31",
            "moeda": "BRL",
            "unidade": "mil",
            "auditoria": "KPMG",
            "valorAtivo": 900000.00
          }
        },
        {
          "subgrupoDoc": "11222333000144",
          "nome": "COSAN LOGISTICA S A",
          "sistemaOrigem": "MANUAL",
          "semFaturamento": false,
          "confirmadoDivergencia": true,
          "justificativa": "Divergência frente ao Endpoint confirmada com o analista responsável pelo subgrupo.",
          "atual": {
            "valor": 8500000.00,
            "dataRefBalanco": "2024-12-31",
            "moeda": "BRL",
            "unidade": "mil"
          }
        },
        {
          "subgrupoDoc": "22333444000155",
          "nome": "COSAN BIOENERGIA S A",
          "sistemaOrigem": "MANUAL",
          "semFaturamento": true,
          "confirmadoDivergencia": false,
          "justificativa": "Subgrupo sem operação no período — sem faturamento a reportar."
        }
      ]
    }' \
    | python3 -m json.tool
}

case "${1:-}" in
  buscar)     buscar_faturamento ;;
  salvar)     salvar_faturamento ;;
  *)
    echo "Uso: $0 {buscar|salvar}" >&2
    exit 1
    ;;
esac

#!/usr/bin/env bash
# Cenários de POST /faturamento/{documento} (SALVAR) — criar/atualizar o faturamento
# de um conglomerado. Complementa `scripts/curls_exemplos.sh` (que só tem o happy path
# de buscar + salvar); aqui estão os cenários com os campos obrigatórios isolados, os
# modos de preenchimento (valor / faixa / sem faturamento), o gate de divergência e os
# erros esperados.
#
# Pré-requisito: stack local no ar (ver SETUP.md) — mocks em :8080, DynamoDB local em
# :8010, app (Lambda de Faturamento) em :8000.
#
# Uso:
#   ./scripts/curls_salvar_post.sh                      # lista os cenários
#   ./scripts/curls_salvar_post.sh minimo
#   ./scripts/curls_salvar_post.sh completo
#   ./scripts/curls_salvar_post.sh todos                # roda todos, em ordem
#
# Sobrescrevíveis por env: BASE_URL, API_PATH, DOCUMENTO, RACF.
#
# ─────────────────────────────────────────────────────────────────────────────────
# CONTRATO
# ─────────────────────────────────────────────────────────────────────────────────
#
#   POST {BASE_URL}/irb-cra-faturamento/v1/faturamento/{documento}
#   Content-Type: application/json
#   X-RACF: <racf de quem informou>          (nome do header = env RACF_HEADER na API)
#
#   201 → gravado (devolve o mesmo envelope do GET, com faixa já calculada)
#   409 → ConfirmacaoNecessaria (gate de divergência) — reenviar com confirmadoDivergencia
#   422 → ErroValidacao / FaixaObrigatoria (regra de negócio) ou 422 do FastAPI (path/JSON)
#   400 → DominioError não mapeado · 500 → erro não tratado
#
# ─────────────────────────────────────────────────────────────────────────────────
# CAMPOS — O QUE É REALMENTE OBRIGATÓRIO
# ─────────────────────────────────────────────────────────────────────────────────
# O Pydantic do request NÃO valida nada (todos os campos são Optional de propósito —
# ver `api/schemas.py`): quem valida é o domínio (`domain/service.py`), num lugar só.
# Então "obrigatório" abaixo = o que o service exige, não o que o schema declara.
#
#   path `documento`          OBRIGATÓRIO  só dígitos (`^\d+$`) — CPF/CNPJ/CGI, sem
#                                          validação de tamanho nem de dígito verificador
#   header X-RACF             opcional*    *na prática sempre mande: é o que volta no GET
#                                          como "atualizado por" (é o RACF, não um nome)
#   body.conglomeradoDoc      opcional     default = o `documento` do path
#   body.marcadores           OBRIGATÓRIO  lista NÃO vazia (vazia → 422)
#
#   Por marcador (matriz e subgrupos vão no MESMO array — não existe campo "nivel" no
#   request; matriz é implícita: `subgrupoDoc == conglomeradoDoc`):
#
#   subgrupoDoc               OBRIGATÓRIO  sempre
#   semFaturamento            opcional     default false. Se TRUE, o backend zera
#                                          valor+faixa e PULA as validações de valor,
#                                          faixa, unidade e moeda — nada mais é exigido
#   atual.moeda               OBRIGATÓRIO  se semFaturamento=false. Tem que estar no
#                                          catálogo de parâmetros (fallback local:
#                                          USD EUR BRL AFN ARS AUD CAD CHF CLP CNY)
#   atual.valor OU
#   atual.faixaCodigo         OBRIGATÓRIO  se semFaturamento=false — um dos dois.
#                                          Com `valor`, o backend calcula a faixa e
#                                          IGNORA o `faixaCodigo` enviado.
#   atual.unidade             opcional     ⚠️ default = "milhoes" quando omitido. Aceita
#                                          unitário/unitario, mil, milhão(ões)/milhao(oes),
#                                          bilhão(ões)/bilhao(oes) e "Real/Efetivo" (×1,
#                                          vocabulário do Endpoint). Só entra no cálculo
#                                          quando há `valor`. Desconhecida → 422
#   confirmadoDivergencia     opcional     default false — ver gate abaixo
#   justificativa             opcional     a API não exige (a tela pede)
#   nome, idSpread,
#   sistemaOrigem,
#   atual.dataRefBalanco,
#   atual.auditoria,
#   atual.valorAtivo,
#   atual.idSpread            opcionais    passthrough, sem validação. `dataRefBalanco` é
#                                          string livre (não é validada como data).
#                                          `idSpread` do MARCADOR tem prioridade sobre o
#                                          de `atual`.
#   faturamentoCra            opcional     valor eleito do CRA (referência) — é persistido
#                                          mas NÃO volta na resposta
#
#   Campos carimbados pelo backend (não mande): nivel, origem (vira sempre BASE ao gravar),
#   racf (vem do header), faixaCodigo quando há valor, atualizadoEm.
#
# ─────────────────────────────────────────────────────────────────────────────────
# FAIXAS (código aceito em `atual.faixaCodigo`) — catálogo do QuickConfig; abaixo o
# fallback local de `adapters/parametros.py::_FAIXAS_FALLBACK`, em REAIS absolutos:
#   ate_360_mil      [0 · 360 mil)          300_mm_500_mm    [300 MM · 500 MM)
#   360_mil_4_8_mm   [360 mil · 4,8 MM)     500_mm_1_bi      [500 MM · 1 Bi)
#   4_8_mm_20_mm     [4,8 MM · 20 MM)       1_bi_2_5_bi      [1 Bi · 2,5 Bi)
#   20_mm_125_mm     [20 MM · 125 MM)       2_5_bi_5_bi      [2,5 Bi · 5 Bi)
#   125_mm_300_mm    [125 MM · 300 MM)      5_bi_10_bi       [5 Bi · 10 Bi)
#                                           acima_10_bi      [10 Bi · ∞)
# O de-para usa `valor × multiplicador(unidade)`: 5000000 com unidade "mil" = R$ 5 Bi
# → faixa `5_bi_10_bi` (não "5 milhões").
#
# ─────────────────────────────────────────────────────────────────────────────────
# GATE DE DIVERGÊNCIA (409) — roda ANTES de gravar, comparando com o que JÁ ESTÁ SALVO
# no banco para aquele (conglomerado, subgrupo). Sem registro salvo → nunca dispara.
# Dispara em: variação de valor acima do limite (fallback: 30%), troca de moeda, ou
# troca de unidade (comparada pelo multiplicador — "milhoes"/"milhões" não divergem).
# Para gravar mesmo assim: reenviar o MESMO marcador com `"confirmadoDivergencia": true`.
# ─────────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_PATH="${API_PATH:-/irb-cra-faturamento/v1}"
DOCUMENTO="${DOCUMENTO:-900001000}"
RACF="${RACF:-A123456}"

# Documento dedicado aos cenários de divergência, pra não sujar a linha de base dos outros.
DOC_DIVERGENCIA="${DOC_DIVERGENCIA:-900002000}"

_post() {
  # _post <título> <documento> <body-json>
  local titulo="$1" documento="$2" body="$3"
  local url="${BASE_URL}${API_PATH}/faturamento/${documento}"
  local resposta status corpo

  printf '\n\033[1m=== %s\033[0m\n' "$titulo"
  printf 'POST %s\n' "$url"

  resposta="$(curl -sS -X POST "$url" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "X-RACF: ${RACF}" \
    -w $'\n%{http_code}' \
    --data-binary "$body")"

  status="${resposta##*$'\n'}"
  corpo="${resposta%$'\n'*}"

  printf -- '--> HTTP %s\n' "$status"
  printf '%s\n' "$corpo" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$corpo"
}

# ══════════════════════════════════════════════════════════════════════════════════
# CENÁRIOS FELIZES
# ══════════════════════════════════════════════════════════════════════════════════

# 1) O MENOR body que grava: um marcador (a matriz) com valor + moeda. Espera 201.
#    5.000.000 × 1.000 (unidade "mil") = R$ 5 Bi → faixa `5_bi_10_bi` na resposta.
minimo() {
  _post "mínimo — só os campos obrigatórios (201)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": {
          "valor": 5000000,
          "moeda": "BRL",
          "unidade": "mil"
        }
      }
    ]
  }'
}

# 2) POST realista da tela: matriz + subgrupos num array só, cada um num estado
#    diferente (valor / sem faturamento / por faixa). Espera 201.
completo() {
  _post "completo — matriz + subgrupos, todos os campos (201)" "$DOCUMENTO" '{
    "conglomeradoDoc": "'"${DOCUMENTO}"'",
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "nome": "Alfa Comércio e Distribuição S.A.",
        "idSpread": "2097",
        "sistemaOrigem": "CRA",
        "semFaturamento": false,
        "confirmadoDivergencia": false,
        "justificativa": "Faturamento informado seguindo a visão consolidada do grupo.",
        "atual": {
          "valor": 6500000,
          "dataRefBalanco": "2024-12-31",
          "moeda": "BRL",
          "unidade": "mil",
          "auditoria": "KPMG",
          "valorAtivo": 900000
        }
      },
      {
        "subgrupoDoc": "900001001",
        "nome": "Alfa Norte Ltda",
        "sistemaOrigem": "MANUAL",
        "semFaturamento": false,
        "justificativa": "Valor confirmado com o cliente em contato telefônico.",
        "atual": {
          "valor": 850,
          "dataRefBalanco": "2024-12-31",
          "moeda": "BRL",
          "unidade": "milhões"
        }
      },
      {
        "subgrupoDoc": "900001002",
        "nome": "Alfa Sul Ltda",
        "semFaturamento": true,
        "justificativa": "Empresa recém-constituída, sem balanço publicado ainda."
      }
    ]
  }'
}

# 3) Modo "por faixa": o analista não tem o valor exato, só a faixa. Sem `valor`,
#    `faixaCodigo` vira obrigatório (e a moeda continua obrigatória). Espera 201.
por_faixa() {
  _post "por faixa — sem valor específico (201)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "nome": "Alfa Comércio e Distribuição S.A.",
        "justificativa": "Cliente informou apenas a faixa de faturamento.",
        "atual": {
          "faixaCodigo": "1_bi_2_5_bi",
          "moeda": "BRL"
        }
      }
    ]
  }'
}

# 4) "Não possuo o faturamento": com semFaturamento=true nada mais é exigido — nem
#    valor, nem faixa, nem moeda (o backend zera valor/faixa). Espera 201.
sem_faturamento() {
  _post "sem faturamento — dispensa valor/faixa/moeda (201)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "900001002",
        "nome": "Alfa Sul Ltda",
        "semFaturamento": true,
        "justificativa": "Subgrupo sem operação no período — sem faturamento a reportar."
      }
    ]
  }'
}

# 5) Pegadinha da unidade: OMITIR `unidade` NÃO significa "unitário" — o default é
#    "milhoes". Aqui 5000 vira R$ 5 Bi (faixa `5_bi_10_bi`), não R$ 5 mil. Espera 201.
unidade_omitida() {
  _post "unidade omitida — default é 'milhoes', não unitário (201)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": {
          "valor": 5000,
          "moeda": "BRL"
        }
      }
    ]
  }'
}

# ══════════════════════════════════════════════════════════════════════════════════
# GATE DE DIVERGÊNCIA
# ══════════════════════════════════════════════════════════════════════════════════

# 6) Linha de base + reenvio com variação de 400% (limite padrão: 30%). O 2º POST
#    espera 409 com a lista de `divergencias` (tipo VALOR, de/para/variacaoPercentual).
#    Precisa do DynamoDB local no ar — o gate só compara com o que já está SALVO.
divergencia() {
  _post "divergência · passo 1/2 — grava a linha de base (201)" "$DOC_DIVERGENCIA" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOC_DIVERGENCIA}"'",
        "nome": "Beta Participações Ltda",
        "confirmadoDivergencia": true,
        "atual": {
          "valor": 1000000,
          "moeda": "BRL",
          "unidade": "unitário"
        }
      }
    ]
  }'

  _post "divergência · passo 2/2 — 5x o valor salvo, sem confirmar (409)" "$DOC_DIVERGENCIA" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOC_DIVERGENCIA}"'",
        "nome": "Beta Participações Ltda",
        "confirmadoDivergencia": false,
        "atual": {
          "valor": 5000000,
          "moeda": "BRL",
          "unidade": "unitário"
        }
      }
    ]
  }'
}

# 7) Mesmo POST do passo 2, agora com `confirmadoDivergencia: true` — é assim que a
#    tela reenvia depois que o analista confirma o aviso. Espera 201.
divergencia_confirmada() {
  _post "divergência confirmada — reenvio que grava (201)" "$DOC_DIVERGENCIA" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOC_DIVERGENCIA}"'",
        "nome": "Beta Participações Ltda",
        "confirmadoDivergencia": true,
        "justificativa": "Crescimento confirmado com o cliente — balanço 2024 auditado.",
        "atual": {
          "valor": 5000000,
          "moeda": "BRL",
          "unidade": "unitário"
        }
      }
    ]
  }'
}

# ══════════════════════════════════════════════════════════════════════════════════
# ERROS DE VALIDAÇÃO (todos 422)
# ══════════════════════════════════════════════════════════════════════════════════

erro_sem_marcadores() {
  # "Nenhum marcador informado para classificar."
  _post "erro — marcadores vazio (422)" "$DOCUMENTO" '{
    "marcadores": []
  }'
}

erro_sem_subgrupo_doc() {
  # "subgrupoDoc obrigatório no marcador."
  _post "erro — marcador sem subgrupoDoc (422)" "$DOCUMENTO" '{
    "marcadores": [
      { "atual": { "valor": 5000000, "moeda": "BRL", "unidade": "mil" } }
    ]
  }'
}

erro_sem_valor_nem_faixa() {
  # tipo FaixaObrigatoria: "informe valor específico ou faixa".
  _post "erro — sem valor e sem faixa (422 FaixaObrigatoria)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": { "moeda": "BRL", "unidade": "mil" }
      }
    ]
  }'
}

erro_sem_moeda() {
  # "Moeda obrigatória para o subgrupo ..."
  _post "erro — sem moeda (422)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": { "valor": 5000000, "unidade": "mil" }
      }
    ]
  }'
}

erro_moeda_invalida() {
  # "Moeda inválida (XPT) para o subgrupo ..." — fora do catálogo de parâmetros.
  _post "erro — moeda fora do catálogo (422)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": { "valor": 5000000, "moeda": "XPT", "unidade": "mil" }
      }
    ]
  }'
}

erro_unidade_desconhecida() {
  # "Unidade desconhecida para o subgrupo ...: 'trilhões'."
  _post "erro — unidade fora do de-para (422)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": { "valor": 5000000, "moeda": "BRL", "unidade": "trilhões" }
      }
    ]
  }'
}

erro_valor_fora_das_faixas() {
  # "Valor -1 (unitário) fora das faixas conhecidas." — a menor faixa começa em 0,
  # então só valor negativo cai fora de todas.
  _post "erro — valor fora de todas as faixas (422)" "$DOCUMENTO" '{
    "marcadores": [
      {
        "subgrupoDoc": "'"${DOCUMENTO}"'",
        "atual": { "valor": -1, "moeda": "BRL", "unidade": "unitário" }
      }
    ]
  }'
}

erro_documento_invalido() {
  # 422 do próprio FastAPI (pattern `^\d+$` no path), antes de chegar no domínio.
  _post "erro — documento não numérico no path (422 do FastAPI)" "ABC123" '{
    "marcadores": [
      {
        "subgrupoDoc": "ABC123",
        "atual": { "valor": 5000000, "moeda": "BRL", "unidade": "mil" }
      }
    ]
  }'
}

# ══════════════════════════════════════════════════════════════════════════════════
# MESMO POST, VIA BFF
# ══════════════════════════════════════════════════════════════════════════════════
# O BFF (`exemplo/`) só repassa: mesmo body, mesma resposta. Diferenças pra quem chama:
#   - path: /api-irb-cra-faturamento-bff/v1/faturamento/{documento}
#   - `documento` tem min_length=11 no BFF (os documentos de teste de 9 dígitos, como
#     900001000, são rejeitados com 422 ANTES do forward — use um CNPJ de 14 dígitos)
#   - o BFF NÃO repassa os headers do caller: ele injeta os seus próprios
#     (x-itau-apikey da config, x-itau-correlationid novo a cada chamada, Authorization
#     com o token OAuth2 que ele mesmo obtém). Do caller, só o `X-RACF` segue adiante.
via_bff() {
  local doc="${DOC_BFF:-12345678000199}"
  local url="${BFF_BASE_URL:-http://localhost:8001}/api-irb-cra-faturamento-bff/v1/faturamento/${doc}"

  printf '\n\033[1m=== via BFF — mesmo body, path do BFF\033[0m\n'
  printf 'POST %s\n' "$url"

  curl -sS -X POST "$url" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "X-RACF: ${RACF}" \
    -d '{
      "marcadores": [
        {
          "subgrupoDoc": "'"${doc}"'",
          "atual": { "valor": 5000000, "moeda": "BRL", "unidade": "mil" }
        }
      ]
    }' | python3 -m json.tool
}

todos() {
  minimo
  completo
  por_faixa
  sem_faturamento
  unidade_omitida
  divergencia
  divergencia_confirmada
  erro_sem_marcadores
  erro_sem_subgrupo_doc
  erro_sem_valor_nem_faixa
  erro_sem_moeda
  erro_moeda_invalida
  erro_unidade_desconhecida
  erro_valor_fora_das_faixas
  erro_documento_invalido
}

_uso() {
  cat >&2 <<'EOF'
Uso: ./scripts/curls_salvar_post.sh <cenário>

Felizes (201):
  minimo                      só os campos obrigatórios
  completo                    matriz + subgrupos, todos os campos
  por-faixa                   sem valor específico, só faixaCodigo
  sem-faturamento             "Não possuo o faturamento"
  unidade-omitida             mostra que o default de unidade é "milhoes"

Gate de divergência:
  divergencia                 grava linha de base e reenvia 5x maior (409)
  divergencia-confirmada      reenvio com confirmadoDivergencia (201)

Erros (422):
  erro-sem-marcadores         erro-sem-moeda            erro-unidade-desconhecida
  erro-sem-subgrupo-doc       erro-moeda-invalida       erro-valor-fora-das-faixas
  erro-sem-valor-nem-faixa    erro-documento-invalido

Outros:
  via-bff                     o mesmo POST pelo path do BFF
  todos                       roda todos os cenários acima (menos via-bff)
EOF
  exit 1
}

case "${1:-}" in
  minimo)                     minimo ;;
  completo)                   completo ;;
  por-faixa)                  por_faixa ;;
  sem-faturamento)            sem_faturamento ;;
  unidade-omitida)            unidade_omitida ;;
  divergencia)                divergencia ;;
  divergencia-confirmada)     divergencia_confirmada ;;
  erro-sem-marcadores)        erro_sem_marcadores ;;
  erro-sem-subgrupo-doc)      erro_sem_subgrupo_doc ;;
  erro-sem-valor-nem-faixa)   erro_sem_valor_nem_faixa ;;
  erro-sem-moeda)             erro_sem_moeda ;;
  erro-moeda-invalida)        erro_moeda_invalida ;;
  erro-unidade-desconhecida)  erro_unidade_desconhecida ;;
  erro-valor-fora-das-faixas) erro_valor_fora_das_faixas ;;
  erro-documento-invalido)    erro_documento_invalido ;;
  via-bff)                    via_bff ;;
  todos)                      todos ;;
  *)                          _uso ;;
esac

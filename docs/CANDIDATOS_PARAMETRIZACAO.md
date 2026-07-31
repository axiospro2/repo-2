# Candidatos a parametrização — ainda NÃO implementados

> Diferente de [`docs/PARAMETROS.md`](PARAMETROS.md) (que documenta env vars
> que **já existem e já funcionam**), este documento é uma lista de
> **propostas**: constantes hoje fixas no código que poderiam virar
> `settings.py` + variável de ambiente, mas isso **ainda não foi feito**.
> Nenhuma das variáveis abaixo existe hoje — é backlog, não configuração.

Cada item traz: onde a constante vive hoje, o valor atual, o nome de env var
sugerido (caso se decida implementar) e o cenário que justificaria a mudança.

## Regras de negócio no domínio

| Constante | Onde (hoje) | Valor atual | Env var sugerida | Cenário de uso |
|---|---|---|---|---|
| `IDADE_MAX_MESES` | `domain/eleicao.py` (e duplicada como `24` solto em `domain/resolucao_marcador.py::dentro_da_janela_idade`) | `24` | `IDADE_MAX_BALANCO_MESES` | Negócio decide que um balanço só vale por 18 meses (não 24) — hoje isso é deploy de código em **dois lugares** (e são divergentes entre si, `R-PEND-011` no `REGRAS.md`). ⚠️ Antes de parametrizar, vale corrigir a duplicação: as duas contagens de mês usam lógicas diferentes. |
| `PRIORIDADE_CATEGORIA_R1` | `domain/eleicao.py` | `(2, 4, 3, 5, 6)` | — (estrutura complexa, não é um valor simples) | Se o Endpoint/Gestão Balanço mudar o enum de categorias, hoje é deploy. Parametrização aqui é mais delicada (é uma ordem de prioridade, não um valor único) — talvez faça mais sentido vir do QuickConfig como JSON, no mesmo padrão de `catalogo-faixas`. |
| `CATEGORIAS_R3_EXCLUIDAS` | `domain/eleicao.py` | `{1, 6, 7, 8, 9}` | — (mesma observação acima) | Mesma situação — categoria excluída da R3 muda com regra de negócio, não com deploy. |
| `_MULTIPLICADORES_UNIDADE` | `domain/faixa.py` | `unitário=1, mil=1e3, milhões=1e6, bilhões=1e9` | — (tabela, não escalar) | Se o negócio adicionar uma unidade nova (ex.: "trilhões") um dia, hoje é deploy de código. Baixa prioridade — a lista de unidades é estável há muito tempo. |
| `sistema_origem="CRA"` | `domain/eleicao.py::_to_resultado` | `"CRA"` | `SISTEMA_ORIGEM_ENDPOINT` | Só relevante se este código um dia servir a outro Endpoint que não seja o Gestão Balanço/CRA. Prioridade baixíssima — não há esse plano hoje. |
| `moeda="BRL"` / `unidade="milhoes"` (defaults) | `domain/models.py::InfoFaturamento` | `"BRL"` / `"milhoes"` | — (são defaults de dataclass, não boundary de I/O) | Só justificaria virar setting se a operação abrisse pra outro país/moeda-base — não é o caso hoje. |

## Performance e concorrência

| Constante | Onde (hoje) | Valor atual | Env var sugerida | Cenário de uso |
|---|---|---|---|---|
| `_MAX_WORKERS` | `domain/service.py` **e** `domain/service_buscar.py` (duplicado — o comentário no código já admite isso) | `10` | `ENDPOINT_MAX_WORKERS` | Se o Endpoint de Faturamento começar a rate-limitar ou se um conglomerado gigante tiver 200+ subgrupos, dá pra afinar sem deploy. Ao implementar, também resolve a duplicação (extrair pra um lugar só). |
| `maxsize` do `PoolManager` | `core/http_client.py::get_pool` | `10` | `HTTP_POOL_MAXSIZE` | Está deliberadamente casado com `_MAX_WORKERS` (`R-HTTP-004` no `REGRAS.md`) — se um virar setting, o outro deveria também, pro acoplamento continuar visível e não virar um "mistério" por que os dois têm o mesmo número. |
| `wait_exponential_jitter(initial, max)` | `core/retry.py::http_retry` | `initial=0.1s`, `max=2.0s` | `RETRY_BACKOFF_INICIAL_S` / `RETRY_BACKOFF_MAXIMO_S` | Se o NJ6/Endpoint historicamente demora mais pra "se recuperar" de uma instabilidade, alongar o backoff reduz pressão sem deploy. |

## Paginação

| Constante | Onde (hoje) | Valor atual | Env var sugerida | Cenário de uso |
|---|---|---|---|---|
| `LIMIT_PADRAO` | `domain/paginacao.py` | `10` | `PAGINACAO_LIMIT_PADRAO` | Produto decide que a tela do CRA deveria mostrar 20 subgrupos por página por padrão. |
| `LIMIT_MAXIMO` | `domain/paginacao.py` | `100` | `PAGINACAO_LIMIT_MAXIMO` | Ajustar o teto sem deploy, se algum cliente/uso interno precisar de páginas maiores (cuidado: afeta custo de leitura do DynamoDB por request). |

## Auth / OAuth2 / TLS

| Constante | Onde (hoje) | Valor atual | Env var sugerida | Cenário de uso |
|---|---|---|---|---|
| `margem_renovacao_s` | `core/oauth2.py::OAuth2Manager` (default da dataclass — **não** lê `settings.token_ttl_margem_s`, que já existe mas está desconectado, `R-PEND-001`) | `60`s | já existe: `TOKEN_TTL_MARGEM_S` — só falta **plumbar** | Renovar o token com mais folga se o STS historicamente demorar a responder perto do vencimento. Aqui não é "criar" a env var — é **corrigir** a que já existe e não é usada. |
| `timeout_s` do `OAuth2Manager` | `core/oauth2.py` (default da dataclass — idem, `settings.token_timeout_s` existe e não é usado) | `5.0`s | já existe: `TOKEN_TIMEOUT_S` — idem, só falta plumbar | Mesma observação — é um bug de "fiação", não uma parametrização nova. |
| Caminhos do CA bundle do STS | `core/oauth2.py::_get_ssl_context` | `["/opt/ca_bundle.crt", "/opt/certs/ca_bundle.crt"]` | `STS_CA_BUNDLE_PATHS` (lista separada por vírgula) | Migrar de layer da Lambda sem esperar por um deploy de código — hoje isso já é feito por deploy, então só valeria a pena se a troca de layer virasse frequente. |

## Logging / observabilidade

| Constante | Onde (hoje) | Valor atual | Env var sugerida | Cenário de uso |
|---|---|---|---|---|
| Truncamento do corpo de erro HTTP | `adapters/nj6.py`, `adapters/endpoint.py` | `[:500]` caracteres | `LOG_ERRO_HTTP_MAX_CHARS` | Se o Datadog permitir payloads maiores no seu plano, ou se 500 chars estiver cortando informação útil de diagnóstico num provedor específico. Baixíssima prioridade. |

## Roteamento

| Constante | Onde (hoje) | Valor atual | Env var sugerida | Cenário de uso |
|---|---|---|---|---|
| Prefixo das rotas | `main.py` — duplicado nas duas chamadas de `include_router` | `"/irb-cra-faturamento/v1"` | `API_ROUTE_PREFIX` | Só relevante numa mudança de versionamento de API (`v1` → `v2`) ou se o produto for renomeado. Não impede nada hoje — é mais sobre eliminar a duplicação entre as duas linhas. |

## Limpeza (nome enganoso, não é parametrização nova)

| Constante | Onde (hoje) | Situação | Sugestão |
|---|---|---|---|
| `PARAMETROS_RETRIES` | `core/settings.py`, usado por `core/retry.py` | Já é uma env var, mas seu nome sugere que afeta o serviço de parâmetros — **não afeta** (QuickConfig não usa retry). Só governa NJ6/Endpoint. | Renomear pra `INTEG_RETRIES`, mantendo `PARAMETROS_RETRIES` como fallback (mesmo padrão de `R-CFG-030` no `REGRAS.md`, que já faz isso pra `AUTH_CLIENT_ID`/`PARAMETROS_CLIENT_ID`). |

---

Nada nesta lista foi implementado. Se quiser seguir com algum item, me diga
qual — a implementação de cada um é: (1) adicionar o campo em
`core/settings.py` com `os.environ.get(...)`, (2) trocar a constante fixa
pela leitura de `settings.*` no ponto de uso, (3) atualizar
`docs/REGRAS.md` (o rule ID correspondente deixa de dizer "hardcoded" e
passa a apontar pra `R-CFG-0xx`), (4) atualizar `.env.example`.

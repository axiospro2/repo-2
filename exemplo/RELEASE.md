# Release — Faturamento IRB/CV4 · BFF (`api-irb-cra-faturamento-bff`)

## Tipo de Alteração

- [x] Nova funcionalidade
- [ ] Bug
- [ ] Refatoração

> **Primeira release do BFF** — não está em nenhum ambiente ainda. Não há versão anterior para
> comparar: é a entrega inicial do backend-for-frontend que a tela do CRA consome, na frente da
> Lambda interna de Faturamento.

---

## O que é o projeto

**Resumo:** 32 arquivos — ~1,1 mil linhas de código de produção (`src/app/`) e ~1,5 mil de testes
(`tests/`), com **100% de cobertura de linha**.

**Contexto:** o BFF é a única porta de entrada do front para o Faturamento. Ele não tem regra de
negócio — quem valida faixa, moeda, unidade, divergência e elege o balanço (R1/R2/R3) é a **API
interna** (`irb-cra-faturamento`). O BFF existe para três coisas que o front não pode fazer:

1. **Autenticar** — obtém o token OAuth2 M2M (`client_credentials`, com cache por TTL) e anexa o
   `Authorization` em cada chamada para a API interna. O front nunca vê essa credencial.
2. **Injetar os headers corporativos** — `x-itau-apikey` (da config do BFF) e
   `x-itau-correlationid` (UUID4 novo por chamada, nunca aceito do caller).
3. **Isolar a rede** — o front fala só com o BFF; a API interna não é exposta.

Fora isso ele é um *pass-through* fiel: repassa body, querystring e status code da API interna sem
reinterpretar (200/201/404/409/422 chegam ao front como vieram). A única rota que **não** faz forward
é `GET /catalogo`, que lê faixas e moedas direto do QuickConfig para popular os dropdowns da tela.

### Aplicação / Entry-point

**Arquivos principais:** `src/app/main.py` (factory `criar_app()`), `lambda_function.py` (shim que
põe `src/` no `sys.path` e exporta `lambda_handler`)

- **Tipo de aplicação:** FastAPI (`title="Faturamento IRB — BFF"`, `version="1.0.0"`), montada por
  `criar_app()` — rotas e middlewares em funções separadas, sem estado global no import além de
  `settings`.
- **Handler:** AWS Lambda via `Mangum(app, lifespan="off")`. O entrypoint publicado é
  `lambda_function.lambda_handler`.
- **Endpoints básicos:** `GET /health` → `{"status": "ok"}` (fora do prefixo e do schema OpenAPI).
- **Middlewares relevantes:**
  - `CORSMiddleware` — origem de `CORS_ALLOW_ORIGIN` (default `*`), métodos `GET`/`POST`/`OPTIONS`,
    headers `Authorization` e `Content-Type`.
  - `vincular_contexto_invocacao` — limpa o contexto de log **antes e depois** de cada requisição
    (`finally`), porque a Lambda reaproveita o processo entre invocações; vincula `request_id`
    (do `aws.context`, com fallback para UUID4), método e path; loga `http.request.start` /
    `http.request.end` com `status_code` e `duration_ms`; devolve o `x-request-id` no header da
    resposta.
  - Logging JSON estruturado (`core/logging.py`) para CloudWatch/Datadog, com `dd.trace_id` /
    `dd.span_id` quando o `ddtrace` está presente, campos reservados protegidos contra
    sobrescrita e truncamento de mensagem (`LOG_MAX_MESSAGE_LEN`, default 10.000).

### Rotas / Endpoints

Prefixo: `/api-irb-cra-faturamento-bff/v1`

| Verbo | Rota | Descrição |
| --- | --- | --- |
| `POST` | `/faturamento/{documento}` | Forward do **SALVAR** para a API interna. Repassa o body cru e o `Content-Type`. |
| `GET` | `/faturamento/{documento}` | Forward do **BUSCAR** (read-through com R1/R2/R3 do lado interno). |
| `GET` | `/grupos-economicos?documento=` | Forward do **autocomplete** (busca "like" por documento parcial). Repassa a querystring inteira. |
| `GET` | `/conglomerados/{documento}/subgrupos` | Forward de subgrupos — ⚠ **a rota correspondente não existe na API interna** (ver "Impacto"). |
| `GET` | `/catalogo` | **Não faz forward**: lê faixas e moedas do QuickConfig e devolve para os dropdowns do front. |
| `GET` | `/health` | Health check (sem prefixo, fora do OpenAPI). |

### Regras de Negócio

O BFF **não tem regra de negócio de faturamento** — tudo (faixa, moeda, unidade, gate de divergência,
cascata R1/R2/R3) é decidido na API interna. O que ele decide é de transporte e segurança:

**Validação de entrada**

- `documento` no path: `min_length=11`, `max_length=18` (`DocumentoPath`, `api/routes.py:28`). Fora
  disso → `422` do FastAPI **antes** do forward. ⚠ Mais restritivo que a API interna, que aceita
  qualquer sequência de dígitos (`^\d+$`) — documentos de 9 dígitos (CGI e os documentos de teste
  `900001000`) **não passam pelo BFF**.
- Nenhuma validação de corpo: o body do POST é repassado como bytes, sem parsing — quem valida é o
  domínio da API interna, num lugar só.

**Headers repassados (`_montar_headers_downstream`) — mesmo conjunto em GET e POST**

| Header | Origem | Motivo |
| --- | --- | --- |
| `x-racf` | **repassado do caller** | Responsabilização: o BFF não sabe quem é o analista, recebe de um gateway/auth na frente e repassa. Só segue adiante se vier preenchido. |
| `x-itau-correlationid` | **gerado aqui** (UUID4 por chamada) | Correlaciona BFF → API interna nos logs dos dois lados. Nunca aceito do caller — ele não deve escolher o próprio correlation id. |
| `x-itau-apikey` | **config do BFF** (`ITAU_API_KEY`) | Credencial do BFF com a API interna, não algo que o front deva conhecer. |
| `Authorization` | **token OAuth2 obtido pelo BFF** | Só em nome do próprio BFF. |

Os demais headers do caller **não** são repassados.

**Autenticação M2M (`core/oauth2.py`)**

- `client_credentials` com **cache de token por `(token_url, client_id)`**, protegido por
  `asyncio.Lock` recriado quando o event loop muda (o Mangum pode trocar o loop entre invocações).
- Dois modos de envio da credencial: `Authorization: Basic` (RFC 6749 §2.3.1, default) ou credenciais
  no body (`use_basic_auth=False`) — o padrão exigido pelo STS interno do Itaú.
- `client_id` **mascarado** nos logs (`4 primeiros + **** + 4 últimos`).
- Falha ao obter token → o BFF devolve **`502`** com corpo JSON
  `{"erro": "BFF falhou ao obter token de autenticacao", "detalhes": ...}` — não vaza a exceção.

**Propagação de status e falhas (`adapters/internal_api.py`)**

- Status e corpo da API interna são propagados **como vieram** (200/201/404/409/422/…). O `httpx`
  não levanta exceção para 4xx/5xx, então esses status chegam como resposta normal.
- Falha de rede/timeout com a API interna → **`502`** com
  `{"erro": "BFF nao alcancou a API interna", "duracao_ms": ...}`.
- Corpos de erro são montados com `json.dumps`, nunca por f-string — nunca sai JSON inválido.
- Timeout das chamadas: `INTEG_TIMEOUT_S`, default **27s** (abaixo dos 29s do API Gateway).

**Montagem da URL da API interna (`core/settings.py`, fail-fast no boot)**

- `INTERNAL_API_BASE_URL` tem prioridade; se ausente, monta
  `https://irb-cra-faturamento.{API_DNS}/{INTERNAL_API_PATH}` (path default `irb-cra-faturamento/v1`).
- Sem nenhum dos dois → `ValueError` na inicialização. `AUTH_TOKEN_URL`, `AUTH_CLIENT_ID` e
  `AUTH_CLIENT_SECRET` são `min_length=1`: **o BFF se recusa a subir sem credencial**, porque gerar o
  token é a função central dele — não existe "modo sem auth".

**Catálogo (`adapters/parametros.py`)**

- Lê `catalogo-faixas` e `catalogo-moedas` do QuickConfig, com cache por TTL
  (`QUICKCONFIG_TTL_S`, default 300s).
- Em erro na busca, **cai de volta para o cache expirado** (se houver) em vez de derrubar a tela.
- `QUICKCONFIG_CLUSTER_MEMBERS` vazio → `ValueError` na primeira chamada da rota (não no boot).

### Infraestrutura

- **Arquivos Terraform / IaC: não existem neste componente.** O deploy (Lambda, API Gateway, roles)
  precisa ser provisionado fora deste repo.
- **Runtime:** AWS Lambda Python, handler `lambda_function.lambda_handler`. Dependências de produção:
  `fastapi`, `mangum`, `httpx`, `pydantic-settings` (`requirements.txt` — 4 pacotes, sem `boto3`).
- **IAM necessário:** apenas o básico de execução da Lambda (`logs:*`). O BFF **não** acessa
  DynamoDB nem Secrets Manager em runtime — as credenciais chegam por variável de ambiente,
  injetadas no provisionamento. **A validar** com quem provisiona.
- **Secrets / Parameters:** `AUTH_CLIENT_ID` e `AUTH_CLIENT_SECRET` (Secrets Manager → env pelo
  Terraform), `ITAU_API_KEY`.
- **Rede:** precisa alcançar o endpoint de token OAuth2, a API interna de Faturamento e o cluster do
  QuickConfig.
- **Dependência interna sem pacote público:** `adapters/parametros.py` importa `manager` (QuickConfig)
  no topo do arquivo — a lib **precisa estar disponível no runtime** (Layer ou pacote interno);
  fora da rede do Itaú só existe stub de teste (`tests/conftest.py`).
- **Variáveis de ambiente** (`core/settings.py`):

  | Variável | Obrigatória | Default |
  | --- | --- | --- |
  | `AUTH_TOKEN_URL` | **sim** (fail-fast) | — |
  | `AUTH_CLIENT_ID` | **sim** (fail-fast) | — |
  | `AUTH_CLIENT_SECRET` | **sim** (fail-fast) | — |
  | `INTERNAL_API_BASE_URL` **ou** `API_DNS` | **sim** (um dos dois) | — |
  | `INTERNAL_API_PATH` | não | `irb-cra-faturamento/v1` |
  | `ITAU_API_KEY` | sim nos ambientes reais | `""` |
  | `INTEG_TIMEOUT_S` | não | `27.0` |
  | `CORS_ALLOW_ORIGIN` | não | `*` |
  | `QUICKCONFIG_CLUSTER_MEMBERS` | sim (para `/catalogo`) | `""` |
  | `QUICKCONFIG_APP_NAME` | não | `Faturamento-irb-lambda` |
  | `QUICKCONFIG_TTL_S` | não | `300` |
  | `QUICKCONFIG_KEY_FAIXAS` / `QUICKCONFIG_KEY_MOEDAS` | não | `catalogo-faixas` / `catalogo-moedas` |
  | `DD_SERVICE` / `DD_ENV` / `DD_VERSION` / `LOG_LEVEL` / `LOG_MAX_MESSAGE_LEN` | não | `faturamento-bff` / `dev` / `unknown` / `INFO` / `10000` |

### Testes

- **Unitários (pytest):** `tests/` — 9 arquivos, **142 testes**, cobrindo rotas, forward, OAuth2,
  settings, logging, catálogo, cliente HTTP e o app.
- **Fakes para integrações externas:** `tests/_helpers.py` (`FakeAsyncClient` — substitui o
  `httpx.AsyncClient` sem rede real, com fila de respostas ou exceção) e `patch_get_client`.
- **Stub do QuickConfig:** `tests/conftest.py` registra um stub de `manager` em `sys.modules` e as
  env vars mínimas **antes** da coleta — sem isso o simples import de `app.core.settings` ou
  `app.adapters.parametros` quebraria a suíte fora da rede interna.
- **Sem testes de aceite/BDD e sem TAAC neste componente** — a suíte de aceite HTTP real vive no repo
  da API interna (`tests/acceptance/`).

### Documentação e Qualidade

- **Documentos:** este `RELEASE.md` e o `.env.example` comentado. ⚠ **Não há README neste
  componente** — o contrato do POST e o comportamento do BFF estão documentados do lado da API
  interna (`docs/POST_SALVAR.md` §7).
- **Qualidade:** `pyproject.toml` só configura o pytest (`pythonpath = ["src", "."]`,
  `testpaths = ["tests"]`). ⚠ **Não há `black`/`ruff` configurados aqui** (a API interna tem);
  o `.pre-commit-config.yaml` da raiz cobre `^(app|tests)/`, ou seja, **não pega `exemplo/`**.
- **Sonar:** `sonar-project.properties` com `sonar.sources=src`, `sonar.tests=tests`,
  `sonar.python.coverage.reportPaths=coverage.xml` e `sonar.python.xunit.reportPath=junit.xml`.
  ⚠ `sonar.projectKey=CHANGE_ME` — **precisa apontar para o projeto já cadastrado no Sonar** antes de
  rodar no pipeline.
- **Pipeline:** não há testspec/buildspec próprio neste componente.

---

## Por que este serviço existe

- **Situação atual:** o front não tem como chamar a API interna de Faturamento — ela não é exposta e
  exige token M2M e headers corporativos que o navegador não pode carregar. Este componente é novo e
  **não foi para nenhum ambiente ainda**.
- **Objetivo:** entregar a camada de borda que o front consome, sem duplicar nenhuma regra de negócio
  — todo o comportamento continua com uma única fonte de verdade, a API interna.
- **Necessidade de negócio:** a tela do CRA precisa de um único host para os quatro passos do fluxo
  (autocomplete → buscar → salvar → catálogo de dropdowns), incluindo o `/catalogo`, que hoje não tem
  equivalente na API interna.
- **Segurança / compliance / arquitetura que moldaram o desenho:**
  - **Credencial fora do browser** — o token OAuth2 e a `x-itau-apikey` são obtidos e injetados
    server-side; o front nunca os vê.
  - **Correlation id não confiável no caller** — gerado no BFF a cada chamada, para que o front não
    consiga forjar rastros.
  - **Fail-fast de configuração** — o BFF não sobe sem credencial nem sem destino, em vez de subir e
    responder 502 em produção.
  - **Segurança do processo reaproveitado** — contexto de log limpo no início **e** no `finally` de
    cada invocação, para nada vazar entre requisições de invocações quentes.
  - **Rastreabilidade** — `x-request-id` devolvido ao caller e `x-itau-correlationid` propagado
    adiante, ligando o log do front ao do BFF e ao da API interna.

---

## Há impacto em outros serviços/sistemas?

Primeira subida: nenhum sistema muda de comportamento — o impacto é de **novo consumo e novas
liberações**.

| Sistema | Impacto |
| --- | --- |
| **Front / tela do CRA** | Passa a ter um host único para o fluxo inteiro. ⚠ Precisa saber que o BFF **não repassa headers do caller** além do `x-racf`, e que documentos com menos de 11 dígitos são rejeitados com 422 antes do forward. |
| **API interna (`irb-cra-faturamento`)** | Novo (e único) consumidor. Precisa aceitar o `client_id` M2M do BFF e a `x-itau-apikey` dele. Precisa estar no ar **antes** do BFF — sem ela, tudo responde 502. |
| **STS / provedor de token OAuth2** | Novo consumidor `client_credentials` — client cadastrado por ambiente. Confirmar qual modo o STS exige: `Basic` (default do código) ou credenciais no body (`use_basic_auth=False`). |
| **QuickConfig** | Novo consumidor, só de leitura (`catalogo-faixas`, `catalogo-moedas`), com cache de 300s. A lib `manager` precisa existir no runtime da Lambda. |
| **API Gateway / rede** | Nova rota pública; o BFF precisa de saída para token, API interna e cluster do QuickConfig. |
| **Datadog / CloudWatch** | Nova origem de logs JSON (`http.request.*`, `bff.forward`, `bff.oauth2_*`, `catalogo_*`) com `dd.trace_id` quando o `ddtrace` estiver presente. |

### Pontos a resolver antes de expor ao front

1. ⚠ **`GET /conglomerados/{documento}/subgrupos` não existe na API interna** — o BFF faz forward
   para um path que a API interna não registra (`api/routes_buscar.py` só tem `/faturamento/{documento}`
   e `/grupos-economicos`). Na prática essa rota devolve o 404 da interna. Remover do BFF ou
   implementar na API interna.
2. ⚠ **`documento` é logado sem máscara** — `_forward` faz `bind_context(documento=documento)` e o
   `core/logging.py` do BFF **não tem mascaramento**, enquanto a API interna mascara CPF/CNPJ antes
   de logar (`core/mascaramento.py`). Como está, o documento completo vai para o CloudWatch/Datadog
   — **gap de LGPD a corrigir antes de subir**.
3. ⚠ **`min_length=11` no path** — incompatível com os documentos de 9 dígitos (CGI) que a API
   interna aceita. Confirmar com o negócio se CGI de 9 dígitos precisa passar pelo BFF.

---

## Como testar

### Pré-requisitos

- Python 3.11+ (a suíte roda em 3.14 localmente).
- Variáveis de ambiente — `cp .env.example .env` e preencher:
  - **Obrigatórias:** `AUTH_TOKEN_URL`, `AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`
  - **Destino (um dos dois):** `INTERNAL_API_BASE_URL` ou `API_DNS`
  - **Recomendadas:** `ITAU_API_KEY`, `QUICKCONFIG_CLUSTER_MEMBERS` (necessária para `/catalogo`)
  - **Opcionais:** `CORS_ALLOW_ORIGIN`, `INTEG_TIMEOUT_S`, `LOG_LEVEL`
- A **API interna no ar** (local: stack de mocks + `uvicorn` do outro componente, na porta 8000).
- A lib `manager` (QuickConfig) só é necessária para a rota `/catalogo`; localmente, sem cluster, essa
  rota falha — as rotas de forward funcionam normalmente.

### Requests (passo a passo)

```bash
# 1. instalar e subir o BFF (a API interna deve estar rodando em :8000)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-tests.txt
cp .env.example .env   # ajuste INTERNAL_API_BASE_URL para a API interna local

export INTERNAL_API_BASE_URL=http://localhost:8000/irb-cra-faturamento/v1
export AUTH_TOKEN_URL=http://localhost:8080/oauth/token
export AUTH_CLIENT_ID=local-client AUTH_CLIENT_SECRET=local-secret
export PYTHONPATH=src
uvicorn app.main:app --reload --port 8002

# 2. health (não passa pelo forward, não exige a API interna)
curl http://localhost:8002/health

# 3. BUSCAR via BFF — use um documento de 14 dígitos (min_length=11)
curl -i http://localhost:8002/api-irb-cra-faturamento-bff/v1/faturamento/12345678000100

# 4. autocomplete (a querystring inteira é repassada)
curl "http://localhost:8002/api-irb-cra-faturamento-bff/v1/grupos-economicos?documento=12345678000100"

# 5. SALVAR via BFF — o X-RACF é o único header do caller que segue adiante
curl -i -X POST \
  "http://localhost:8002/api-irb-cra-faturamento-bff/v1/faturamento/12345678000100" \
  -H "Content-Type: application/json" \
  -H "X-RACF: A123456" \
  -d '{"marcadores":[{"subgrupoDoc":"12345678000100",
        "atual":{"valor":"5000000","moeda":"BRL","unidade":"unitario"}}]}'

# 6. catálogo (não faz forward — exige QuickConfig)
curl http://localhost:8002/api-irb-cra-faturamento-bff/v1/catalogo
```

Verificar na resposta: header `x-request-id` presente e status **idêntico** ao que a API interna
devolveria (201 no salvar, 409 em divergência, 422 em erro de validação).

### Cenários de testes

```bash
pip install -r requirements-tests.txt
python -m pytest -q                                   # 142 testes
python -m pytest -q --cov=app --cov-report=term        # cobertura
python -m pytest --cov=app --cov-report=xml:coverage.xml --junitxml=junit.xml  # para o Sonar
```

Cobertos pela suíte (`tests/`):

- **Rotas e forward** (`test_api_routes.py`, 38 testes) — as 4 rotas de forward + `/catalogo`, corpo
  e querystring repassados, `Content-Type` propagado, headers downstream corretos (`x-racf` só
  quando presente, `x-itau-correlationid` sempre novo, `x-itau-apikey` da config), status da API
  interna propagado sem reinterpretação, e `422` do path validator antes do forward.
- **Adapter da API interna** (`test_internal_api.py`, 13 testes) — montagem da URL com e sem querystring,
  `502` quando o token falha, `502` em erro de rede/timeout, 4xx/5xx propagados como resposta
  normal, corpos de erro sempre JSON válido.
- **OAuth2** (`test_oauth.py`, 19 testes) — cache de token por chave, reuso enquanto válido, modo `Basic` vs
  credenciais no body, mascaramento do `client_id`, `RuntimeError` virando 502.
- **Settings** (`test_settings.py`, 11 testes) — fail-fast sem credencial, prioridade de
  `INTERNAL_API_BASE_URL` sobre `API_DNS`, montagem da URL a partir do DNS, normalização de barras.
- **App e middleware** (`test_main.py`, 22 testes) — `/health`, CORS, `x-request-id` na resposta,
  contexto limpo entre invocações, log de início/fim com `duration_ms`, exceção re-levantada após
  logar.
- **Logging** (`test_logging.py`, 18 testes) — formato JSON, campos reservados não sobrescritos,
  truncamento, `dd.trace_id` quando há span.
- **Catálogo** (`test_parametros.py`, 16 testes) — cache por TTL, fallback para cache expirado em
  erro, erro quando o cluster não está configurado.

---

## Checklist

- [x] Testes unitários passando — `tests/`: **142 passed**, **100% de cobertura de linha**
      (417 statements, 0 sem cobertura)
- [ ] Testes de aceite / TAAC — **não se aplica a este componente**; a suíte HTTP real vive no repo
      da API interna
- [ ] Lint e formatação — **pendente**: não há `ruff`/`black` configurados aqui e o
      `.pre-commit-config.yaml` da raiz não cobre `exemplo/`
- [ ] README do componente — **pendente**: só existe o `.env.example`
- [ ] `sonar.projectKey` apontando para o projeto real (hoje `CHANGE_ME`)
- [ ] Variáveis de ambiente e secrets provisionados em dev/hom/prod — `AUTH_TOKEN_URL`,
      `AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`, `INTERNAL_API_BASE_URL`/`API_DNS`, `ITAU_API_KEY`,
      `QUICKCONFIG_CLUSTER_MEMBERS`
- [ ] Infraestrutura (Lambda, API Gateway, Layer com a lib `manager`) criada — não há IaC neste repo
- [ ] Modo de auth do STS confirmado (`Basic` vs credenciais no body)
- [ ] Mascaramento do `documento` nos logs — **gap de LGPD aberto** (ver "Pontos a resolver")
- [ ] Rota `GET /conglomerados/{documento}/subgrupos` resolvida (remover ou implementar na interna)
- [x] Não há breaking changes — é a primeira release, não existe consumidor em produção

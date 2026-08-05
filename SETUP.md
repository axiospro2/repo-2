# Setup Local

## Estrutura

```
docker-compose.yml       # orquestra os 3 serviços de mock (nada aqui toca em app/)
mocks/
  app/
    main.py              # FastAPI: mock de NJ6, Endpoint e OAuth2/STS (NÃO mocka parâmetros)
    fixtures/
      nj6.json
      endpoint.json
  db/
    init_table.py        # cria a tabela no DynamoDB local (roda 1x, container sobe e sai)
app/                      # aplicação real — NENHUM arquivo aqui foi alterado para os mocks
dev-stubs/
  manager/               # stub de import da lib interna QuickConfig (`manager`) — só
                         # existe pra rodar localmente fora da rede do Itaú; ver §3
```

## 1. Subir os mocks (DynamoDB local + tabela + API de mocks)

```bash
docker compose up -d --build
```

Isso sobe:
- `dynamodb-local` (porta **8010** no host → 8000 dentro do container, modo `-inMemory`)
- `dynamodb-init` (roda uma vez, cria a tabela `tbcv4163_fatm_cogl_subg`, sai com status 0)
- `mock-api` (porta **8080**), expondo:
  - `POST /oauth/token` — token OAuth2 fake (aceita qualquer client_id/secret)
  - `GET /consulta-gruposeconomicos/v1/grupos-economicos` — NJ6 (fixture `nj6.json`).
    Serve os dois usos do adapter (`app/src/app/adapters/nj6.py`): documento EXATO da
    cabeça do conglomerado (1 resultado), documento EXATO de um SUBGRUPO (resolve pelo
    grupo a que ele pertence) e documento PARCIAL/"like" (todos os grupos cujo documento
    da cabeça começa com o termo — usado pelo `GET /grupos-economicos` do autocomplete).
  - `GET /gestaobalanco/v1/spreads-faturamento` — Endpoint/CRA (fixture `endpoint.json`)

> **Parâmetros (faixas/moedas/limite de divergência) não são mockados aqui** — o serviço
> real é o QuickConfig (lib interna `manager`, não HTTP). Local, sem
> `QUICKCONFIG_CLUSTER_MEMBERS` configurado, `ParametrosClient`/`ParametrosCatalogo` caem
> direto no fallback hardcoded do próprio adapter (6 faixas, BRL/USD, 30% de limite) — ver
> `app/src/app/adapters/parametros.py`.

Verificar:
```bash
curl http://localhost:8080/health
docker logs projeto_reconstruido-dynamodb-init-1   # deve mostrar "tabela ... criada"
```

> **Nota:** a porta 8000 padrão do DynamoDB Local foi trocada pra **8010** no host porque
> já havia outro projeto seu (`job_matcher_api`) usando a 8000. Dentro da rede docker
> interna o serviço continua respondendo em `dynamodb-local:8000` normalmente.

> **Nota 2:** o DynamoDB Local está em modo `-inMemory` (sem volume persistente) — os dados
> somem a cada `docker compose down`/restart. Isso evitou um bug conhecido do container
> `amazon/dynamodb-local` com volumes nomeados (erro `unable to open database file`,
> causa a API travar em qualquer request). Pra mock é o suficiente; se precisar persistir,
> me avisa que ajusto pra `-dbPath` com bind mount (não named volume).

## 2. Configurar `.env`

```bash
cp .env.example .env
```

Os valores default já apontam pro `mock-api` (porta 8080) e pro DynamoDB local (porta 8010).
`app/src/app/core/settings.py` não foi alterado — só as variáveis de ambiente mudam.

## 3. Rodar a aplicação

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export $(cat .env | xargs)
export PYTHONPATH=app/src:dev-stubs

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

(Se a 8000 também estiver ocupada por outro projeto seu, use `--port 8001` e ajuste onde for
testar.)

> **`dev-stubs` no `PYTHONPATH` é obrigatório localmente**: `adapters/parametros.py` importa
> a lib interna `manager` (QuickConfig) no topo do arquivo — sem o stub, o `uvicorn` quebra
> ao importar `app.main` (mesmo o `pytest` já tem seu próprio stub equivalente, em
> `app/tests/conftest.py`, então os testes não precisam disso).

## 4. Testar

```bash
curl http://localhost:8000/health
curl http://localhost:8000/irb-cra-faturamento/v1/faturamento/050746577
```

O fluxo de BUSCAR deve: pegar token do mock → resolver conglomerado no NJ6 mock (CNPJ
`050746577`, grupo "COSAN S A") → buscar spread no Endpoint mock → aplicar R1/R2/R3 →
consultar DynamoDB local (vazio até você gravar algo com POST) → devolver o agregado.

Pra testar o autocomplete (`GET /grupos-economicos`, busca "like"):

```bash
curl "http://localhost:8000/irb-cra-faturamento/v1/grupos-economicos?documento=9000"
```

Deve devolver os 20 grupos dos casos de `docs/CASOS_TESTE_MOCK.md` (todos com documento
começando em `9000...`). Buscar pelo documento de um SUBGRUPO (não a cabeça), ex.
`900002001` (Beta Norte), também deve resolver o conglomerado inteiro, igual buscar pela
cabeça `900002000` — confirma que o mock trata subgrupo e cabeça do mesmo jeito que o NJ6
real.

## Trocar os mocks depois

Os JSONs em `mocks/app/fixtures/*.json` são as fixtures reais que você mandou. Pra trocar o
cenário de teste, edita esses arquivos e reconstrói:

```bash
docker compose up -d --build mock-api
```

## Parar tudo

```bash
docker compose down
```

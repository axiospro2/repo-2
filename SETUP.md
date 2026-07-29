# Setup Local

## Estrutura

```
docker-compose.yml       # orquestra os 3 serviços de mock (nada aqui toca em app/)
mocks/
  app/
    main.py              # FastAPI: mock de NJ6, Endpoint, Parâmetros e OAuth2/STS
    fixtures/
      faixas.json
      nj6.json
      endpoint.json
  db/
    init_table.py        # cria a tabela no DynamoDB local (roda 1x, container sobe e sai)
app/                      # aplicação real — NENHUM arquivo aqui foi alterado para os mocks
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
  - `GET /parametros` — faixas + moedas (fixture `faixas.json`)
  - `GET /consulta-gruposeconomicos/v1/grupos-economicos` — NJ6 (fixture `nj6.json`)
  - `GET /gestaobalanco/v1/spreads-faturamento` — Endpoint/CRA (fixture `endpoint.json`)

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
export PYTHONPATH=app/src

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

(Se a 8000 também estiver ocupada por outro projeto seu, use `--port 8001` e ajuste onde for
testar.)

## 4. Testar

```bash
curl http://localhost:8000/health
curl http://localhost:8000/faturamento/050746577
```

O fluxo de BUSCAR deve: pegar token do mock → resolver conglomerado no NJ6 mock (CNPJ
`050746577`, grupo "COSAN S A") → buscar spread no Endpoint mock → aplicar R1/R2/R3 →
consultar DynamoDB local (vazio até você gravar algo com POST) → devolver o agregado.

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

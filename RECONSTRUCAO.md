# Reconstrução do Projeto: itau-cv4-app-lambda-gdf-irb-faturamento

## Metodologia (retrabalho após primeira tentativa falha do Haiku)

- **2402 frames** extraídos a 10 fps do vídeo (240s), sem OCR — análise 100% visual
- 13 agentes paralelos transcreveram o código verbatim, com números de linha do gutter da IDE
- Um agente dedicado mapeou a árvore de arquivos completa a partir da sidebar do IntelliJ
- Script de merge stitching por número de linha real (não simples concatenação)
- **Todo arquivo final foi validado com `ast.parse` — 0 erros de sintaxe nos 22 arquivos**
- Onde a transcrição automática saiu inconsistente, o código foi verificado manualmente
  contra os frames originais (lido diretamente, sem OCR) antes de corrigir

## Problemas encontrados e corrigidos durante o merge

1. **Hierarquia errada**: alguns chunks reportaram caminhos sem o prefixo `src/app/`
   (ex: `app/domain/service.py` em vez de `app/src/app/domain/service.py`). Corrigido
   normalizando todos os caminhos contra a árvore confirmada pela sidebar.
2. **`service_buscador.py` vs `service_buscar.py`**: um agente leu o nome errado —
   confirmado como o mesmo arquivo (mesmo docstring/lógica vista diretamente nos frames).
3. **Números de gutter embutidos no código**: alguns agentes deixaram o número da linha
   dentro do próprio bloco de código (ex: `71\tdef _resolver_metadados(`), quebrando a
   sintaxe. Corrigido removendo os prefixos numéricos linha a linha.
4. **Dedução agressiva demais**: a lógica inicial descartava linhas repetidas pelo mesmo
   número de gutter, mas isso apagava conteúdo real em instruções que ocupam várias linhas
   de tela com o mesmo número (ex: import multilinhas). Corrigido para só deduplicar quando
   número E texto são idênticos.
5. **Fence markdown não fechado**: `chunk_10.md` esqueceu de fechar um bloco ```` ```python ```` 
   antes da seção `## SIDEBAR`, fazendo o parser engolir texto da árvore de arquivos como se
   fosse código Python. Corrigido no arquivo fonte.
6. **Transcrição genuinamente corrompida**: alguns trechos (`service.py` função
   `_resolver_metadados`, `service_buscar.py` funções `_alvos_da_aba`/`_paginar`) vieram
   com `if`/`else` duplicados ou nomes de função errados na origem. Nesses casos, fui
   diretamente aos frames do vídeo (sem OCR) para ler o código real e corrigir manualmente.

## Estrutura confirmada (via leitura direta da sidebar, frame f_00001 e outros)

```
itau-cv4-app-lambda-gdf-irb-faturamento/
  .github/
  .idea/
  app/
    src/
      app/
        adapters/
          fixtures/
          __init__.py, auth.py, endpoint.py, nj6.py, parametros.py, repository.py
        api/
          __init__.py, deps.py, errors.py, routes.py, routes_buscar.py, schemas.py
        core/
          __init__.py, logging.py, oauth2.py, retry.py, settings.py
        domain/
          __init__.py, divergencia.py, eleicao.py, errors.py, faixa.py, models.py,
          service.py, service_buscar.py
        __init__.py
        main.py
    tests/
    lambda_function.py, pyproject.toml, requirements.txt, requirements-tests.txt
    docs/
    infra/
  tests/
```

## Gaps honestos (não inventados)

- **`app/src/app/api/schemas.py`**: confirmado por varredura completa de 161 frames
  (cobrindo os ~240s inteiros) que este arquivo NUNCA foi aberto no editor durante a
  gravação. Deixado como stub documentado — não foi reconstruído por evidência nenhuma.
- **`app/src/app/domain/eleicao.py`**: capturado até a linha ~190. Duas buscas dedicadas
  não encontraram o restante do arquivo em nenhum momento do vídeo (a aba nunca voltou a
  ficar em foco). O arquivo real pode ter mais conteúdo além do que está aqui.
- **`app/src/app/domain/service_buscar.py`**, linha `_marcador_do_endpoint`: alguns
  parâmetros/corpo foram reconstruídos combinando duas leituras parciais da mesma função;
  validado que o resultado final compila e é logicamente consistente com o resto do arquivo.
- **Arquivos de configuração raiz** (`lambda_function.py`, `pyproject.toml`,
  `requirements.txt`, `requirements-tests.txt` dentro de `app/`, além de `docs/`, `infra/`,
  `tests/`): existência confirmada na sidebar, mas conteúdo nunca ficou visível no vídeo —
  não recriados com conteúdo inventado.

## Estatísticas

| Métrica | Valor |
|---|---|
| Frames analisados | 2402 (10 fps) |
| Arquivos Python com código real | 22 |
| Linhas de código total | 2649 |
| Erros de sintaxe | 0 |
| Arquivos com gap conhecido documentado | 2 (schemas.py, eleicao.py parcial) |

## Como usar

```bash
cd /Users/emersonsantos/Movies/frames/projeto_reconstruido/app
python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn pydantic httpx boto3 mangum
PYTHONPATH=src uvicorn app.main:app --reload
```

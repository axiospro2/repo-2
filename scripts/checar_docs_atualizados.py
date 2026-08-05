#!/usr/bin/env python3
"""Hook de pre-commit: bloqueia o commit se código de produção mudou sem
nenhuma documentação (`docs/*.md` ou os `.md` da raiz) junto no mesmo commit.

Motivo: `docs/REGRAS.md` e `docs/DIVERGENCIAS_PO.md` só continuam confiáveis
se forem atualizados junto com o código que descrevem — documentação que
fica pra trás é pior que nenhuma (engana quem lê). Ver a lição do bug
"atualizacao" vs "atualizado": um campo com nome errado passou despercebido
porque nada forçava revisar a documentação/testes na hora da mudança.

Escopo: só `app/src/app/**/*.py` (código de produção) exige doc junto.
Mudança só em testes, mocks, config etc. não dispara a checagem.
"""

from __future__ import annotations

import subprocess
import sys

CODE_PREFIX = "app/src/app/"
DOC_PREFIXES = ("docs/",)
DOC_ROOT_FILES = {"README.md", "SETUP.md", "RECONSTRUCAO.md"}


def _arquivos_staged() -> list[str]:
    saida = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [linha for linha in saida.stdout.splitlines() if linha]


def _e_codigo(caminho: str) -> bool:
    return caminho.startswith(CODE_PREFIX) and caminho.endswith(".py")


def _e_doc(caminho: str) -> bool:
    if caminho in DOC_ROOT_FILES:
        return True
    return any(caminho.startswith(p) for p in DOC_PREFIXES) and caminho.endswith(".md")


def main() -> int:
    arquivos = _arquivos_staged()
    codigo_mudou = [a for a in arquivos if _e_codigo(a)]
    doc_mudou = any(_e_doc(a) for a in arquivos)

    if codigo_mudou and not doc_mudou:
        print("\n🚫 Commit bloqueado: código de produção mudou sem nenhuma documentação junto.\n")
        print("Arquivos de código no commit:")
        for a in codigo_mudou:
            print(f"  - {a}")
        print(
            "\nAtualize pelo menos um arquivo de docs/*.md (ou README.md/SETUP.md) "
            "descrevendo a mudança, e adicione ele ao commit (`git add`)."
        )
        print(
            "\nSe a mudança realmente não precisa de doc (ex.: typo, formatação), "
            "use 'git commit --no-verify' conscientemente.\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Hooks do behave — garante que `src` e `app/` (para `tests.fakes`) estejam
no sys.path antes de qualquer import dos steps, independente do diretório de
onde `behave` for chamado."""

from __future__ import annotations

import os
import sys

_FEATURES_DIR = os.path.dirname(__file__)
_APP_ROOT = os.path.abspath(os.path.join(_FEATURES_DIR, ".."))
_SRC = os.path.join(_APP_ROOT, "src")

for caminho in (_SRC, _APP_ROOT):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

"""Dependências do BFF (singletons reaproveitados na Lambda quente)."""
from __future__ import annotations

from functools import lru_cache

from app.adapters.parametros import ParametrosCatalogo


@lru_cache(maxsize=1)
def get_parametros() -> ParametrosCatalogo:
    return ParametrosCatalogo()

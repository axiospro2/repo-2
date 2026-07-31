"""Testes para app.api.deps."""
from __future__ import annotations

from app.adapters.parametros import ParametrosCatalogo
from app.api.deps import get_parametros


class TestGetParametros:
    def test_retorna_instancia_de_parametros_catalogo(self):
        get_parametros.cache_clear()
        try:
            resultado = get_parametros()
            assert isinstance(resultado, ParametrosCatalogo)
        finally:
            get_parametros.cache_clear()

    def test_e_singleton_via_lru_cache(self):
        get_parametros.cache_clear()
        try:
            assert get_parametros() is get_parametros()
        finally:
            get_parametros.cache_clear()

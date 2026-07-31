"""Testes de regressão para os bugs críticos corrigidos (ver docs/AVALIACAO.md §4).

Cada teste aqui existe para que, se alguém reintroduzir um destes bugs no
futuro, a suíte quebre imediatamente — em vez de só descobrirmos em produção.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.adapters.endpoint import _extrair_spreads
from app.domain import service_buscar


def test_service_buscar_compila_sem_erro_de_sintaxe():
    """Bug #1 (AVALIACAO.md §4.1): `_log_resolucao` chamava `log_event()` com
    keywords repetidas — um SyntaxError que impedia o import de todo o módulo
    (e, por consequência, o cold start da Lambda inteira)."""
    caminho = Path(service_buscar.__file__)
    ast.parse(caminho.read_text(encoding="utf-8"))


def test_obter_faturamento_usa_a_instancia_do_catalogo_nao_a_classe():
    """Bug #3 (AVALIACAO.md §4.3): o código chamava `Catalogo.obter()` na classe
    Protocol (levantando TypeError) em vez de `catalogo.obter()` na instância
    recebida por parâmetro — quebrava todo GET de BUSCAR."""
    fonte = inspect.getsource(service_buscar.obter_faturamento)
    assert "Catalogo.obter()" not in fonte
    assert "catalogo.obter()" in fonte


def test_tenacity_esta_declarado_em_requirements():
    """Bug #4 (AVALIACAO.md §4.4): `core/retry.py` importa `tenacity`, usado por
    nj6/endpoint/parametros, mas o pacote não constava em requirements.txt —
    um `pip install` limpo resultava em ModuleNotFoundError."""
    repo_root = Path(service_buscar.__file__).resolve().parents[4]
    requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")
    assert "tenacity" in requirements


def test_extrair_spreads_de_resposta_em_lista_crua():
    """Bug #5 (AVALIACAO.md §4.5), caso 1: quando a resposta já vem como lista
    (`[...]`), o bug de precedência de operador lançava AttributeError."""
    resposta_lista = [{"codigo": 1}, {"codigo": 2}]
    assert _extrair_spreads(resposta_lista) == resposta_lista


def test_extrair_spreads_de_resposta_envelopada_em_data():
    """Bug #5 (AVALIACAO.md §4.5), caso 2 (o mais comum): quando a resposta vem
    como `{"data": [...]}`, o bug de precedência fazia o resultado ser SEMPRE
    uma lista vazia, descartando os spreads reais silenciosamente."""
    spreads_reais = [{"codigo": 1}, {"codigo": 2}]
    assert _extrair_spreads({"data": spreads_reais}) == spreads_reais


def test_extrair_spreads_de_resposta_envelopada_em_spreads():
    spreads_reais = [{"codigo": 1}]
    assert _extrair_spreads({"spreads": spreads_reais}) == spreads_reais


def test_extrair_spreads_de_resposta_sem_lista_reconhecivel_retorna_vazio():
    assert _extrair_spreads({"outro_campo": "valor"}) == []

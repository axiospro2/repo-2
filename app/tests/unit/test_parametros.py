"""Testes de ParametrosClient/ParametrosCatalogo (QuickConfig).

`ConfigurationService`/`QuickConfigConfigurationSource` são sempre mockados
diretamente aqui (via `@patch`) — o stub de `manager` registrado em
`tests/conftest.py` só existe pra permitir o import do módulo, nunca é
exercitado de verdade.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.parametros import ParametrosCatalogo, ParametrosClient, _ClienteQuickConfig

# ─────────── inicialização ───────────


def test_client_com_defaults():
    cliente = ParametrosClient(cluster_members="test-cluster:5701")
    assert cliente._cluster_members == "test-cluster:5701"
    assert cliente._app_name == "Faturamento-irb-lambda"
    assert cliente._ttl == 300
    assert cliente._key_faixas == "catalogo-faixas"
    assert cliente._key_moedas == "catalogo-moedas"
    assert cliente._key_auditorias == "catalogo-auditorias"
    assert cliente._key_limite_divergencia == "limite-Maximo-Divergencia-Porcentagem"


def test_client_com_parametros_customizados():
    cliente = ParametrosClient(
        cluster_members="custom-cluster:5701",
        app_name="CustomApp",
        ttl_s=600,
        key_faixas="custom.faixas",
        key_moedas="custom.moedas",
        key_auditorias="custom.auditorias",
        key_limite_divergencia="custom.limite",
    )
    assert cliente._app_name == "CustomApp"
    assert cliente._ttl == 600
    assert cliente._key_faixas == "custom.faixas"
    assert cliente._key_moedas == "custom.moedas"
    assert cliente._key_auditorias == "custom.auditorias"
    assert cliente._key_limite_divergencia == "custom.limite"


def test_catalogo_com_defaults():
    catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
    assert catalogo._key_faixas == "catalogo-faixas"
    assert catalogo._key_moedas == "catalogo-moedas"
    assert catalogo._key_auditorias == "catalogo-auditorias"


# ─────────── _inicializar_servico ───────────


def test_cluster_members_vazio_gera_erro():
    cliente = ParametrosClient(cluster_members="")
    with pytest.raises(ValueError, match="QUICKCONFIG_CLUSTER_MEMBERS"):
        cliente._inicializar_servico()


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
def test_erro_de_conexao_e_relancado(mock_config_source):
    mock_config_source.side_effect = RuntimeError("QuickConfig unreachable")

    cliente = ParametrosClient(cluster_members="test-cluster:5701")
    with pytest.raises(RuntimeError, match="QuickConfig unreachable"):
        cliente._inicializar_servico()


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_sucesso_com_um_membro(mock_config_service, mock_config_source):
    cliente = ParametrosClient(cluster_members="test-cluster:5701")
    service = cliente._inicializar_servico()

    assert service is not None
    mock_config_source.assert_called_once_with(
        app_name="Faturamento-irb-lambda",
        sync=True,
        listener_mode=False,
        cluster_members=["test-cluster:5701"],
    )
    mock_config_service.assert_called_once()


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_multiplos_membros_sao_separados_por_virgula(mock_config_service, mock_config_source):
    cliente = ParametrosClient(cluster_members="host1:5701,host2:5701,host3:5701")
    cliente._inicializar_servico()

    kwargs = mock_config_source.call_args.kwargs
    assert kwargs["cluster_members"] == ["host1:5701", "host2:5701", "host3:5701"]


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_reaproveita_servico_ja_inicializado(mock_config_service, mock_config_source):
    cliente = ParametrosClient(cluster_members="test-cluster:5701")
    s1 = cliente._inicializar_servico()
    s2 = cliente._inicializar_servico()

    assert s1 is s2
    mock_config_source.assert_called_once()


# ─────────── ParametrosClient.obter() — SALVAR ───────────


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_client_obter_monta_snapshot_completo(mock_config_service_class, mock_config_source):
    mock_service = MagicMock()
    mock_service.get_config_for_app.side_effect = [
        json.dumps([{"codigo": "FAIXA_1", "descricao": "d", "min": 0, "max": 1000}]),
        json.dumps(["BRL"]),
        json.dumps(["KPMG"]),
        "30",
    ]
    mock_config_service_class.return_value = mock_service

    snapshot = ParametrosClient(cluster_members="test-cluster:5701").obter()

    assert snapshot["gateDivergenciaAtivo"] is True
    assert snapshot["limiteVariacaoPercentual"] == 30
    assert snapshot["faixas"][0]["codigo"] == "FAIXA_1"
    assert snapshot["moedas"] == ["BRL"]
    assert snapshot["auditorias"] == ["KPMG"]


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_client_gate_sempre_ativo_mesmo_com_limite_zero(
    mock_config_service_class, mock_config_source
):
    mock_service = MagicMock()
    mock_service.get_config_for_app.side_effect = ["[]", "[]", "[]", "0"]
    mock_config_service_class.return_value = mock_service

    snapshot = ParametrosClient(cluster_members="test-cluster:5701").obter()
    assert snapshot["gateDivergenciaAtivo"] is True
    assert snapshot["limiteVariacaoPercentual"] == 0


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_client_segunda_chamada_usa_cache(mock_config_service_class, mock_config_source):
    mock_service = MagicMock()
    mock_service.get_config_for_app.side_effect = [
        json.dumps([{"codigo": "FAIXA_1", "descricao": "d", "min": 0, "max": 1000}]),
        json.dumps(["BRL"]),
        json.dumps(["KPMG"]),
        "30",
    ]
    mock_config_service_class.return_value = mock_service

    cliente = ParametrosClient(cluster_members="test-cluster:5701", ttl_s=3600)
    resultado1 = cliente.obter()
    resultado2 = cliente.obter()

    assert resultado1 == resultado2
    assert mock_service.get_config_for_app.call_count == 4  # só a 1ª chamada buscou


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_client_cache_expirado_busca_de_novo(mock_config_service_class, mock_config_source):
    mock_service = MagicMock()
    mock_service.get_config_for_app.side_effect = ["[]", "[]", "[]", "30"] * 2
    mock_config_service_class.return_value = mock_service

    cliente = ParametrosClient(cluster_members="test-cluster:5701", ttl_s=0)
    cliente.obter()
    cliente.obter()

    assert mock_service.get_config_for_app.call_count == 8


def test_client_fallback_quando_quickconfig_indisponivel():
    """Sem `cluster_members`, `_inicializar_servico` falha antes de qualquer chamada —
    exercita o fallback sem precisar mockar QuickConfig."""
    snapshot = ParametrosClient(cluster_members="").obter()

    assert snapshot["gateDivergenciaAtivo"] is True
    assert snapshot["limiteVariacaoPercentual"] == 30
    assert len(snapshot["faixas"]) == 11
    assert snapshot["faixas"][0]["codigo"] == "ate_360_mil"
    assert snapshot["moedas"] == [
        "USD",
        "EUR",
        "BRL",
        "AFN",
        "ARS",
        "AUD",
        "CAD",
        "CHF",
        "CLP",
        "CNY",
    ]
    assert snapshot["auditorias"] == [
        "KPMG",
        "PWC (Price Waterhouse Coopers)",
        "Deloitte",
        "EY (Ernst & Young)",
    ]


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_client_fallback_nao_e_cacheado(mock_config_service_class, mock_config_source):
    mock_service = MagicMock()
    mock_service.get_config_for_app.side_effect = Exception("QuickConfig unavailable")
    mock_config_service_class.return_value = mock_service

    cliente = ParametrosClient(cluster_members="test-cluster:5701", ttl_s=9999)
    primeiro = cliente.obter()

    mock_service.get_config_for_app.side_effect = [
        json.dumps([{"codigo": "FAIXA_1", "descricao": "d", "min": 0, "max": 1000}]),
        json.dumps(["BRL"]),
        json.dumps(["KPMG"]),
        "30",
    ]
    segundo = cliente.obter()

    assert len(primeiro["faixas"]) == 11  # fallback
    assert segundo["faixas"][0]["codigo"] == "FAIXA_1"  # 2ª tentativa buscou de novo


# ─────────── ParametrosCatalogo.obter() — BUSCAR ───────────


@patch("app.adapters.parametros.QuickConfigConfigurationSource")
@patch("app.adapters.parametros.ConfigurationService")
def test_catalogo_obter_so_faixas_moedas_e_auditorias(
    mock_config_service_class, mock_config_source
):
    mock_service = MagicMock()
    mock_service.get_config_for_app.side_effect = [
        json.dumps([{"codigo": "FAIXA_1", "descricao": "d", "min": 0, "max": 1000}]),
        json.dumps(["BRL"]),
        json.dumps(["KPMG"]),
    ]
    mock_config_service_class.return_value = mock_service

    snapshot = ParametrosCatalogo(cluster_members="test-cluster:5701").obter()

    assert snapshot == {
        "faixas": [{"codigo": "FAIXA_1", "descricao": "d", "min": 0, "max": 1000}],
        "moedas": ["BRL"],
        "auditorias": ["KPMG"],
    }


def test_catalogo_fallback_quando_quickconfig_indisponivel():
    snapshot = ParametrosCatalogo(cluster_members="").obter()

    assert len(snapshot["faixas"]) == 11
    assert snapshot["moedas"] == [
        "USD",
        "EUR",
        "BRL",
        "AFN",
        "ARS",
        "AUD",
        "CAD",
        "CHF",
        "CLP",
        "CNY",
    ]
    assert len(snapshot["auditorias"]) == 4


# ───────── base abstrata ─────────


def test_base_buscar_e_fallback_sao_abstratos():
    cliente = _ClienteQuickConfig(cluster_members="test-cluster:5701")
    with pytest.raises(NotImplementedError):
        cliente._buscar(MagicMock())
    with pytest.raises(NotImplementedError):
        cliente._fallback()


# ───────── _parse_json ─────────


def test_parse_json_string_valida():
    assert _ClienteQuickConfig._parse_json('[{"id": 1}]') == [{"id": 1}]


def test_parse_json_objeto_python():
    obj = [{"id": 1}]
    assert _ClienteQuickConfig._parse_json(obj) is obj


def test_parse_json_none_retorna_default():
    assert _ClienteQuickConfig._parse_json(None, default=[]) == []


def test_parse_json_invalido_retorna_default():
    assert _ClienteQuickConfig._parse_json("invalido", default=[]) == []

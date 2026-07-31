"""Testes unitários para ParametrosCatalogo com QuickConfig.

O import de `manager` é satisfeito pelo stub registrado em conftest.py -
`ConfigurationService`/`QuickConfigConfigurationSource` são sempre mockados
diretamente aqui, então o stub em si nunca é exercitado.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.parametros import ParametrosCatalogo


class TestInicializacao:
    def test_com_defaults(self):
        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
        assert catalogo._cluster_members == "test-cluster:5701"
        assert catalogo._app_name == "Faturamento-irb-lambda"
        assert catalogo._ttl == 300

    def test_com_parametros_customizados(self):
        catalogo = ParametrosCatalogo(
            cluster_members="custom-cluster:5701",
            app_name="CustomApp",
            ttl_s=600,
            key_faixas="custom.faixas",
            key_moedas="custom.moedas",
        )
        assert catalogo._cluster_members == "custom-cluster:5701"
        assert catalogo._app_name == "CustomApp"
        assert catalogo._ttl == 600
        assert catalogo._key_faixas == "custom.faixas"
        assert catalogo._key_moedas == "custom.moedas"


class TestInicializarServico:
    def test_cluster_members_vazio_gera_erro(self):
        catalogo = ParametrosCatalogo(cluster_members="")
        with pytest.raises(ValueError, match="QUICKCONFIG_CLUSTER_MEMBERS"):
            catalogo._inicializar_servico()

    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    def test_erro_de_conexao_e_relancado(self, mock_config_source):
        """Se a conexão com o QuickConfig falhar, o erro deve propagar (não é engolido)."""
        mock_config_source.side_effect = RuntimeError("QuickConfig unreachable")

        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
        with pytest.raises(RuntimeError, match="QuickConfig unreachable"):
            catalogo._inicializar_servico()

    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    @patch("app.adapters.parametros.ConfigurationService")
    def test_sucesso_com_um_membro(self, mock_config_service, mock_config_source):
        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
        service = catalogo._inicializar_servico()

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
    def test_multiplos_membros_sao_separados_por_virgula(self, mock_config_service, mock_config_source):
        """Regressão: o cluster_members inteiro era embrulhado numa lista de 1
        elemento, em vez de ser separado por vírgula em múltiplos membros."""
        catalogo = ParametrosCatalogo(cluster_members="host1:5701,host2:5701,host3:5701")
        catalogo._inicializar_servico()

        kwargs = mock_config_source.call_args.kwargs
        assert kwargs["cluster_members"] == ["host1:5701", "host2:5701", "host3:5701"]

    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    @patch("app.adapters.parametros.ConfigurationService")
    def test_reaproveita_servico_ja_inicializado(self, mock_config_service, mock_config_source):
        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
        s1 = catalogo._inicializar_servico()
        s2 = catalogo._inicializar_servico()

        assert s1 is s2
        mock_config_source.assert_called_once()


class TestCatalogo:
    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    @patch("app.adapters.parametros.ConfigurationService")
    def test_busca_sem_cache(self, mock_config_service_class, mock_config_source):
        mock_service = MagicMock()
        mock_service.get_config_for_app.side_effect = [
            json.dumps([{"id": 1, "descricao": "Faixa A"}]),
            json.dumps([{"id": 1, "codigo": "BRL"}]),
        ]
        mock_config_service_class.return_value = mock_service

        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
        result = catalogo.catalogo()

        assert len(result["faixas"]) == 1
        assert len(result["moedas"]) == 1
        assert result["faixas"][0]["descricao"] == "Faixa A"
        assert result["moedas"][0]["codigo"] == "BRL"

    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    @patch("app.adapters.parametros.ConfigurationService")
    def test_segunda_chamada_usa_cache(self, mock_config_service_class, mock_config_source):
        mock_service = MagicMock()
        mock_service.get_config_for_app.side_effect = [
            json.dumps([{"id": 1, "descricao": "Faixa A"}]),
            json.dumps([{"id": 1, "codigo": "BRL"}]),
        ]
        mock_config_service_class.return_value = mock_service

        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701", ttl_s=3600)
        result1 = catalogo.catalogo()
        result2 = catalogo.catalogo()

        assert result1 == result2
        assert mock_service.get_config_for_app.call_count == 2

    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    @patch("app.adapters.parametros.ConfigurationService")
    def test_fallback_para_cache_expirado_em_erro(self, mock_config_service_class, mock_config_source):
        mock_service = MagicMock()
        mock_service.get_config_for_app.side_effect = [
            json.dumps([{"id": 1, "descricao": "Faixa A"}]),
            json.dumps([{"id": 1, "codigo": "BRL"}]),
            Exception("QuickConfig unavailable"),
        ]
        mock_config_service_class.return_value = mock_service

        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701", ttl_s=-1)

        result1 = catalogo.catalogo()
        assert len(result1["faixas"]) == 1

        result2 = catalogo.catalogo()
        assert result2 == result1

    @patch("app.adapters.parametros.QuickConfigConfigurationSource")
    @patch("app.adapters.parametros.ConfigurationService")
    def test_sem_cache_e_com_erro_relanca_excecao(self, mock_config_service_class, mock_config_source):
        mock_service = MagicMock()
        mock_service.get_config_for_app.side_effect = Exception("QuickConfig unavailable")
        mock_config_service_class.return_value = mock_service

        catalogo = ParametrosCatalogo(cluster_members="test-cluster:5701")
        with pytest.raises(Exception, match="QuickConfig unavailable"):
            catalogo.catalogo()


class TestParseJson:
    def test_string_valida(self):
        result = ParametrosCatalogo._parse_json('[{"id": 1, "nome": "Item"}]')
        assert result == [{"id": 1, "nome": "Item"}]

    def test_objeto_python(self):
        obj = [{"id": 1, "nome": "Item"}]
        assert ParametrosCatalogo._parse_json(obj) == obj

    def test_none_retorna_default(self):
        assert ParametrosCatalogo._parse_json(None, default=[]) == []

    def test_invalido_retorna_default(self):
        assert ParametrosCatalogo._parse_json("invalid json", default=[]) == []

    def test_invalido_sem_default_retorna_none(self):
        assert ParametrosCatalogo._parse_json("invalid json") is None

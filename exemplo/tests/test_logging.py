"""Testes para o módulo de logging estruturado."""
from __future__ import annotations

import json
import logging
import os
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.logging import (
    _safe_update,
    bind_context,
    clear_context,
    get_logger,
    log_event,
    setup_logging,
)


@pytest.fixture(autouse=True)
def reset_logging():
    """Reseta o state do logging entre testes."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    clear_context()
    yield
    clear_context()


@pytest.fixture
def captured_logs() -> StringIO:
    """Captura stdout para validar JSON."""
    setup_logging()
    stream = StringIO()
    root = logging.getLogger()
    root.handlers[0].stream = stream
    return stream


def parse_log(stream: StringIO) -> dict[str, Any]:
    """Extrai o último log JSON."""
    stream.seek(0)
    lines = stream.readlines()
    return json.loads(lines[-1]) if lines else {}


class TestDDTraceIds:
    """Testes para integração com ddtrace."""

    def test_dd_trace_ids_sem_tracer(self, captured_logs):
        """Quando ddtrace não está disponível, não adiciona trace IDs."""
        with patch("app.core.logging._tracer", None):
            log = get_logger("test")
            log.info("test message")

            payload = parse_log(captured_logs)
            assert "dd.trace_id" not in payload
            assert "dd.span_id" not in payload

    def test_dd_trace_ids_sem_span_ativo(self, captured_logs):
        """Quando não há span ativo, não adiciona trace IDs."""
        mock_tracer = MagicMock()
        mock_tracer.current_span.return_value = None

        with patch("app.core.logging._tracer", mock_tracer):
            log = get_logger("test")
            log.info("test message")

            payload = parse_log(captured_logs)
            assert "dd.trace_id" not in payload
            assert "dd.span_id" not in payload

    def test_dd_trace_ids_com_span_ativo(self, captured_logs):
        """Quando há span ativo, adiciona trace IDs."""
        mock_span = MagicMock()
        mock_span.trace_id = 123456789
        mock_span.span_id = 987654321

        mock_tracer = MagicMock()
        mock_tracer.current_span.return_value = mock_span

        with patch("app.core.logging._tracer", mock_tracer):
            log = get_logger("test")
            log.info("test message")

            payload = parse_log(captured_logs)
            assert payload["dd.trace_id"] == "123456789"
            assert payload["dd.span_id"] == "987654321"

    def test_dd_trace_ids_exception_silenciada(self, captured_logs):
        """Exceções ao buscar trace IDs são silenciadas."""
        mock_tracer = MagicMock()
        mock_tracer.current_span.side_effect = RuntimeError("tracer error")

        with patch("app.core.logging._tracer", mock_tracer):
            log = get_logger("test")
            log.info("test message")

            payload = parse_log(captured_logs)
            assert "dd.trace_id" not in payload
            assert "dd.span_id" not in payload
            assert payload["message"] == "test message"


class TestSafeUpdate:
    """Testes para proteção de campos reservados."""

    def test_safe_update_ignora_none(self, captured_logs):
        """Campos None no contexto são ignorados."""
        bind_context(user_id="123", nullable=None)
        log = get_logger("test")
        log.info("test")

        payload = parse_log(captured_logs)
        assert payload["user_id"] == "123"
        assert "nullable" not in payload

    def test_safe_update_protege_campos_reservados(self, captured_logs):
        """Campos reservados não podem ser sobrescritos."""
        bind_context(
            timestamp="fake-time",
            status="fake-status",
            service="fake-service",
        )
        log = get_logger("test")
        log.info("test")

        payload = parse_log(captured_logs)
        assert payload["timestamp"].endswith(("+00:00", "Z"))
        assert payload["status"] == "info"
        assert payload["service"] == os.environ.get("DD_SERVICE", "faturamento-bff")

    def test_safe_update_com_extra_none(self, captured_logs):
        """_safe_update lida com extra=None."""
        log = get_logger("test")
        log.info("test", extra={"ctx": None})

        payload = parse_log(captured_logs)
        assert payload["message"] == "test"


class TestSafeUpdateDirect:
    """Testes diretos de _safe_update (sem passar pelo formatter/handler)."""

    def test_extra_none_nao_faz_nada(self):
        payload = {"a": 1}
        _safe_update(payload, None)
        assert payload == {"a": 1}

    def test_ignora_valores_none_no_extra(self):
        payload: dict = {}
        _safe_update(payload, {"a": None, "b": "value"})
        assert payload == {"b": "value"}


class TestMessageTruncation:
    """Testes para truncamento de mensagens longas."""

    def test_mensagem_longa_e_truncada(self, captured_logs):
        """Mensagens maiores que MAX_MESSAGE_LEN são truncadas."""
        with patch("app.core.logging._MAX_MESSAGE_LEN", 100):
            log = get_logger("test")
            long_message = "x" * 200
            log.info(long_message)

            payload = parse_log(captured_logs)
            assert payload["message"] == ("x" * 100) + "...[truncated]"
            assert len(payload["message"]) == 114

    def test_mensagem_curta_nao_e_truncada(self, captured_logs):
        """Mensagens menores que MAX_MESSAGE_LEN ficam intactas."""
        with patch("app.core.logging._MAX_MESSAGE_LEN", 100):
            log = get_logger("test")
            short_message = "x" * 50
            log.info(short_message)

            payload = parse_log(captured_logs)
            assert payload["message"] == short_message


class TestExceptionHandling:
    """Testes para formatação de exceções."""

    def test_excecao_com_ctx(self, captured_logs):
        """Exceções com contexto extra são formatadas corretamente."""
        log = get_logger("test")
        try:
            raise ValueError("test error")
        except ValueError:
            log.exception("error occurred", extra={"ctx": {"user_id": "123"}})

        payload = parse_log(captured_logs)
        assert payload["error"]["kind"] == "ValueError"
        assert "test error" in payload["error"]["stack"]
        assert payload["user_id"] == "123"


class TestSetupLogging:
    """Testes para setup e configuração."""

    def test_setup_e_idempotente(self):
        """Múltiplas chamadas a setup_logging não duplicam handlers."""
        setup_logging()
        setup_logging()
        setup_logging()

        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if getattr(h, "_faturamento_json", False)]
        assert len(json_handlers) == 1

    def test_loggers_ruidosos_sao_silenciados(self):
        """Loggers de bibliotecas ruidosas têm nível WARNING."""
        setup_logging()

        noisy_loggers = ["uvicorn.access", "botocore", "boto3", "urllib3", "aiobotocore"]
        for logger_name in noisy_loggers:
            logger = logging.getLogger(logger_name)
            assert logger.level == logging.WARNING

    def test_remove_handlers_pre_existentes(self):
        """Handlers pré-existentes são removidos no setup."""
        root = logging.getLogger()
        old_handler = logging.StreamHandler()
        root.addHandler(old_handler)

        setup_logging()

        assert old_handler not in root.handlers


class TestContextManagement:
    """Testes para gerenciamento de contexto."""

    def test_bind_context_com_multiplos_valores(self, captured_logs):
        """bind_context adiciona múltiplos campos."""
        bind_context(user_id="123", request_id="req-456", org_id="org-789")
        log = get_logger("test")
        log.info("test")

        payload = parse_log(captured_logs)
        assert payload["user_id"] == "123"
        assert payload["request_id"] == "req-456"
        assert payload["org_id"] == "org-789"

    def test_clear_context_remove_todos_campos(self, captured_logs):
        """clear_context remove todo o contexto."""
        bind_context(user_id="123")
        clear_context()

        log = get_logger("test")
        log.info("test")

        payload = parse_log(captured_logs)
        assert "user_id" not in payload


class TestLogEvent:
    """Testes para log_event."""

    def test_log_event_com_nivel_customizado(self, captured_logs):
        """log_event respeita o nível especificado."""
        log = get_logger("test")
        log_event(log, "user.login", level="warning", user_id="123")

        payload = parse_log(captured_logs)
        assert payload["status"] == "warning"
        assert payload["event"] == "user.login"
        assert payload["user_id"] == "123"

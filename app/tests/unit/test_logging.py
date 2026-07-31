import json
import logging
import sys
from types import SimpleNamespace

from app.core import logging as flog


def test_bind_context_e_clear_context():
    flog.clear_context()
    flog.bind_context(foo="bar", ignorado=None)
    assert flog._context.get() == {"foo": "bar"}
    flog.clear_context()
    assert flog._context.get() == {}


def test_dd_trace_ids_sem_ddtrace_retorna_vazio(monkeypatch):
    monkeypatch.setitem(sys.modules, "ddtrace", None)  # simula import falhando
    assert flog._dd_trace_ids() == {}


def test_dd_trace_ids_com_span_ativo(monkeypatch):
    fake_span = SimpleNamespace(trace_id=123, span_id=456)
    fake_module = SimpleNamespace(tracer=SimpleNamespace(current_span=lambda: fake_span))
    monkeypatch.setitem(sys.modules, "ddtrace", fake_module)

    assert flog._dd_trace_ids() == {"dd.trace_id": "123", "dd.span_id": "456"}


def test_dd_trace_ids_sem_span_ativo(monkeypatch):
    fake_module = SimpleNamespace(tracer=SimpleNamespace(current_span=lambda: None))
    monkeypatch.setitem(sys.modules, "ddtrace", fake_module)

    assert flog._dd_trace_ids() == {}


def test_json_formatter_formata_payload_basico():
    flog.clear_context()
    logger = flog.get_logger("teste.logger")
    record = logger.makeRecord("teste.logger", logging.INFO, __file__, 1, "mensagem", (), None)
    saida = json.loads(flog._JsonFormatter().format(record))

    assert saida["message"] == "mensagem"
    assert saida["status"] == "info"
    assert saida["logger"] == "teste.logger"
    assert "timestamp" in saida


def test_json_formatter_inclui_ctx_extra():
    logger = flog.get_logger("teste.logger")
    record = logger.makeRecord(
        "teste.logger",
        logging.INFO,
        __file__,
        1,
        "mensagem",
        (),
        None,
        extra={"ctx": {"event": "teste.evento", "x": 1}},
    )
    saida = json.loads(flog._JsonFormatter().format(record))
    assert saida["event"] == "teste.evento"
    assert saida["x"] == 1


def test_json_formatter_inclui_erro_quando_ha_exc_info():
    logger = flog.get_logger("teste.logger")
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logger.makeRecord("teste.logger", logging.ERROR, __file__, 1, "falhou", (), exc_info)
    saida = json.loads(flog._JsonFormatter().format(record))
    assert "ValueError" in saida["error"]


def test_setup_logging_configura_handler_json_na_primeira_vez():
    """Simula "cold start": root sem o handler tagueado ainda -> setup_logging()
    troca os handlers existentes pelo handler JSON próprio."""
    root = logging.getLogger()
    handlers_originais = list(root.handlers)
    try:
        root.handlers = [logging.NullHandler()]  # nenhum com _faturamento_json ainda
        flog.setup_logging()
        assert len(root.handlers) == 1
        assert getattr(root.handlers[0], "_faturamento_json", False) is True
    finally:
        root.handlers = handlers_originais


def test_setup_logging_e_idempotente():
    root = logging.getLogger()
    handlers_originais = list(root.handlers)
    try:
        flog.setup_logging()
        qtd_apos_primeira = len(root.handlers)
        flog.setup_logging()
        assert len(root.handlers) == qtd_apos_primeira
    finally:
        root.handlers = handlers_originais


def test_log_event_nivel_desabilitado_nao_loga():
    logger = flog.get_logger("teste.log_event_desabilitado")
    logger.setLevel(logging.INFO)
    chamadas = []
    logger.log = lambda *a, **k: chamadas.append((a, k))

    flog.log_event(logger, "teste.evento.debug", level="debug")

    assert chamadas == []


def test_log_event_nivel_habilitado_loga():
    logger = flog.get_logger("teste.log_event_habilitado")
    logger.setLevel(logging.INFO)
    chamadas = []
    logger.log = lambda *a, **k: chamadas.append((a, k))

    flog.log_event(logger, "teste.evento.info", nivel_extra="x")

    assert len(chamadas) == 1
    args, kwargs = chamadas[0]
    assert args[1] == "teste.evento.info"
    assert kwargs["extra"]["ctx"]["nivel_extra"] == "x"

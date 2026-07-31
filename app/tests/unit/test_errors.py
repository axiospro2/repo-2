from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.domain.errors import (
    ConfirmacaoNecessaria,
    DominioError,
    ErroValidacao,
    FaixaObrigatoria,
    NaoEncontrado,
)


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/confirmacao")
    def _confirmacao():
        raise ConfirmacaoNecessaria([{"tipo": "VALOR", "de": "1", "para": "2"}])

    @app.get("/nao-encontrado")
    def _nao_encontrado():
        raise NaoEncontrado("nenhum conglomerado encontrado")

    @app.get("/validacao")
    def _validacao():
        raise ErroValidacao("valor fora das faixas")

    @app.get("/faixa-obrigatoria")
    def _faixa_obrigatoria():
        raise FaixaObrigatoria("informe valor ou faixa")

    @app.get("/dominio-generico")
    def _dominio():
        raise DominioError("erro genérico de domínio")

    @app.get("/nao-tratado")
    def _boom():
        raise RuntimeError("BOOM")

    return TestClient(app, raise_server_exceptions=False)


def test_confirmacao_necessaria_409():
    resp = _client().get("/confirmacao")
    assert resp.status_code == 409
    body = resp.json()
    assert body["tipo"] == "ConfirmacaoNecessaria"
    assert body["divergencias"] == [{"tipo": "VALOR", "de": "1", "para": "2"}]


def test_nao_encontrado_404():
    resp = _client().get("/nao-encontrado")
    assert resp.status_code == 404
    assert resp.json() == {"erro": "nenhum conglomerado encontrado"}


def test_erro_validacao_422():
    resp = _client().get("/validacao")
    assert resp.status_code == 422
    body = resp.json()
    assert body["tipo"] == "ErroValidacao"


def test_faixa_obrigatoria_e_subclasse_de_erro_validacao_422():
    resp = _client().get("/faixa-obrigatoria")
    assert resp.status_code == 422
    body = resp.json()
    assert body["tipo"] == "FaixaObrigatoria"  # MRO resolve pro handler de ErroValidacao


def test_dominio_error_generico_400():
    resp = _client().get("/dominio-generico")
    assert resp.status_code == 400
    assert resp.json() == {"erro": "erro genérico de domínio"}


def test_excecao_nao_tratada_500():
    resp = _client().get("/nao-tratado")
    assert resp.status_code == 500
    body = resp.json()
    assert body["erro"] == "Internal Server Error"
    assert body["tipo"] == "RuntimeError"

from app.api import deps
from tests.fakes import FakeCatalogo, FakeEndpoint, FakeRepositorio

CDOC = "123456789"
PREFIXO = "/irb-cra-faturamento/v1"


def _body_valor(valor="5000000", moeda="BRL", unidade="unitario"):
    return {
        "conglomeradoDoc": CDOC,
        "marcadores": [{
            "subgrupoDoc": CDOC,
            "nome": "Grupo Teste",
            "faturamentoModificado": True,
            "atual": {"valor": valor, "moeda": moeda, "unidade": unidade},
        }],
    }


def test_salvar_com_sucesso_201(api_app, api_client):
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_parametros] = lambda: FakeCatalogo()
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()

    resp = api_client.post(
        f"{PREFIXO}/faturamento/{CDOC}", json=_body_valor(), headers={"X-RACF": "r123"}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["conglomeradoDoc"] == CDOC
    assert body["marcadores"][0]["atual"]["faixaCodigo"] == "FAIXA_2"


def test_salvar_persiste_no_repo_e_racf_vai_pro_atual(api_app, api_client):
    repo = FakeRepositorio()
    api_app.dependency_overrides[deps.get_repo] = lambda: repo
    api_app.dependency_overrides[deps.get_parametros] = lambda: FakeCatalogo()
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()

    api_client.post(f"{PREFIXO}/faturamento/{CDOC}", json=_body_valor(), headers={"X-RACF": "r999"})

    salvo = repo.get_subgrupo(CDOC, CDOC)
    assert salvo.atual.racf == "r999"


def test_salvar_documento_invalido_422(api_app, api_client):
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_parametros] = lambda: FakeCatalogo()
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()

    resp = api_client.post(
        f"{PREFIXO}/faturamento/abc", json=_body_valor(), headers={"X-RACF": "r1"}
    )
    assert resp.status_code == 422


def test_salvar_erro_de_dominio_propaga_pelo_handler_422(api_app, api_client):
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_parametros] = lambda: FakeCatalogo()
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()

    resp = api_client.post(
        f"{PREFIXO}/faturamento/{CDOC}",
        json=_body_valor(valor="1", unidade="unitario"),  # fora de qualquer faixa
        headers={"X-RACF": "r1"},
    )

    assert resp.status_code == 422
    assert resp.json()["tipo"] == "ErroValidacao"


def test_salvar_sem_racf_header(api_app, api_client):
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_parametros] = lambda: FakeCatalogo()
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()

    resp = api_client.post(f"{PREFIXO}/faturamento/{CDOC}", json=_body_valor())
    assert resp.status_code == 201

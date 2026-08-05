from app.api import deps
from tests.fakes import FakeCatalogo, FakeEndpoint, FakeNJ6, FakeRepositorio, conglomerado_simples

CDOC = "123456789"
PREFIXO = "/irb-cra-faturamento/v1"


def test_buscar_faturamento_sucesso(api_app, api_client):
    cong = conglomerado_simples(CDOC, "Grupo Teste", [CDOC])
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(cong)
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()
    api_app.dependency_overrides[deps.get_catalogo] = lambda: FakeCatalogo()

    resp = api_client.get(f"{PREFIXO}/faturamento/{CDOC}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["nomeGrupoEconomico"] == "Grupo Teste"
    assert body["origemDados"] == "PREVIEW"  # nada salvo, nada no endpoint -> MANUAL


def test_buscar_faturamento_traz_matriz_e_subgrupos_sem_paginacao(api_app, api_client):
    cong = conglomerado_simples(CDOC, "Grupo Teste", [CDOC, "SUB2"])
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(cong)
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()
    api_app.dependency_overrides[deps.get_catalogo] = lambda: FakeCatalogo()

    resp = api_client.get(f"{PREFIXO}/faturamento/{CDOC}")

    assert resp.status_code == 200
    body = resp.json()
    assert "paginacao" not in body
    assert len(body["marcadores"]) == 2  # matriz + SUB2 (CDOC deduplicado)


def test_buscar_faturamento_documento_invalido_422(api_app, api_client):
    cong = conglomerado_simples(CDOC, "Grupo Teste", [CDOC])
    api_app.dependency_overrides[deps.get_repo] = lambda: FakeRepositorio()
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(cong)
    api_app.dependency_overrides[deps.get_endpoint] = lambda: FakeEndpoint()
    api_app.dependency_overrides[deps.get_catalogo] = lambda: FakeCatalogo()

    resp = api_client.get(f"{PREFIXO}/faturamento/abc")
    assert resp.status_code == 422


# ─────────── GET /grupos-economicos (busca "like") ───────────


def test_buscar_grupos_economicos_sucesso(api_app, api_client):
    grupo1 = conglomerado_simples("900001000", "Grupo Um", [])
    grupo2 = conglomerado_simples("900002000", "Grupo Dois", ["900002001"])
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(grupo1, grupos=[grupo1, grupo2])

    resp = api_client.get(f"{PREFIXO}/grupos-economicos", params={"documento": "9000"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["grupos"]) == 2
    assert body["grupos"][0]["nomeGrupoEconomico"] == "Grupo Um"
    assert body["grupos"][1]["subgrupos"] == [
        {"nome": "Subgrupo 900002001", "documento": "900002001"}
    ]


def test_buscar_grupos_economicos_sem_match_retorna_lista_vazia(api_app, api_client):
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(
        conglomerado_simples(CDOC, "Grupo Teste", []), grupos=[]
    )

    resp = api_client.get(f"{PREFIXO}/grupos-economicos", params={"documento": "999"})

    assert resp.status_code == 200
    assert resp.json() == {"grupos": []}


def test_buscar_grupos_economicos_documento_invalido_422(api_app, api_client):
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(
        conglomerado_simples(CDOC, "Grupo Teste", [])
    )

    resp = api_client.get(f"{PREFIXO}/grupos-economicos", params={"documento": "abc"})
    assert resp.status_code == 422


def test_buscar_grupos_economicos_documento_ausente_422(api_app, api_client):
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(
        conglomerado_simples(CDOC, "Grupo Teste", [])
    )

    resp = api_client.get(f"{PREFIXO}/grupos-economicos")
    assert resp.status_code == 422

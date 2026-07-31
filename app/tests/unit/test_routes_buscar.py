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


def test_buscar_subgrupos_sucesso(api_app, api_client):
    cong = conglomerado_simples(CDOC, "Grupo Teste", [CDOC, "SUB2"])
    api_app.dependency_overrides[deps.get_nj6] = lambda: FakeNJ6(cong)

    resp = api_client.get(f"{PREFIXO}/conglomerados/{CDOC}/subgrupos")

    assert resp.status_code == 200
    body = resp.json()
    assert body["nomeGrupoEconomico"] == "Grupo Teste"
    assert len(body["subgrupos"]) == 2


def test_buscar_subgrupos_erro_no_nj6_propaga_como_500(api_app, api_client):
    class NJ6Quebrado:
        def get_por_documento(self, documento):
            raise RuntimeError("NJ6 indisponível (simulado)")

    api_app.dependency_overrides[deps.get_nj6] = lambda: NJ6Quebrado()

    resp = api_client.get(f"{PREFIXO}/conglomerados/{CDOC}/subgrupos")

    assert resp.status_code == 500
    assert resp.json()["tipo"] == "RuntimeError"

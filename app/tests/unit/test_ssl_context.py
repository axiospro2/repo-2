from app.core import ssl_context as sslctx


class _FakeSSLContext:
    def __init__(self, falha: bool = False):
        self._falha = falha
        self.carregado_cafile = None
        self.carregado_capath = None

    def load_verify_locations(self, cafile=None, capath=None):
        if self._falha:
            raise RuntimeError("cert inválido (simulado)")
        self.carregado_cafile = cafile
        self.carregado_capath = capath


def test_sem_env_vars_retorna_none(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert sslctx.criar_contexto_ssl() is None


def test_com_espacos_em_branco_conta_como_vazio(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "   ")
    monkeypatch.setenv("SSL_CERT_DIR", "  ")
    assert sslctx.criar_contexto_ssl() is None


def test_cert_file_existente_e_carregado(monkeypatch, tmp_path):
    cert = tmp_path / "ca.pem"
    cert.write_text("fake cert")
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    fake_ctx = _FakeSSLContext()
    monkeypatch.setattr(sslctx.ssl, "create_default_context", lambda: fake_ctx)

    resultado = sslctx.criar_contexto_ssl()
    assert resultado is fake_ctx
    assert fake_ctx.carregado_cafile == str(cert)


def test_cert_dir_existente_e_carregado(monkeypatch, tmp_path):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    fake_ctx = _FakeSSLContext()
    monkeypatch.setattr(sslctx.ssl, "create_default_context", lambda: fake_ctx)

    resultado = sslctx.criar_contexto_ssl()
    assert resultado is fake_ctx
    assert fake_ctx.carregado_capath == str(tmp_path)


def test_cert_file_e_dir_configurados_mas_inexistentes_nao_carrega_nada(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/caminho/que/nao/existe.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/caminho/que/nao/existe/dir")
    fake_ctx = _FakeSSLContext()
    monkeypatch.setattr(sslctx.ssl, "create_default_context", lambda: fake_ctx)

    resultado = sslctx.criar_contexto_ssl()
    assert resultado is fake_ctx
    assert fake_ctx.carregado_cafile is None
    assert fake_ctx.carregado_capath is None


def test_erro_ao_carregar_certificado_retorna_none(monkeypatch, tmp_path):
    cert = tmp_path / "ca.pem"
    cert.write_text("fake cert")
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(sslctx.ssl, "create_default_context", lambda: _FakeSSLContext(falha=True))

    assert sslctx.criar_contexto_ssl() is None

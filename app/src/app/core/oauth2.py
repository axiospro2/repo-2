"""OAuth2Manager: obtém e cacheia tokens de acesso M2M para autenticação com o STS interno do Itaú.

Fluxo:
    Lambda → OAuth2Manager.get_token()
        → POST /api/oauth/token (STS Itaú)
        → { access_token, expires_in, ... }
        → Authorization: Bearer <token> → API Interna

Token é cacheado em memória e reutilizado até 60 segundos antes de expirar.
Em Lambda, o cache sobrevive entre invocações enquanto o container estiver quente.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

from app.core.logging import get_logger, log_event

_logger = get_logger("oauth2")

# Cache global de tokens por URL do STS
_token_cache: dict[str, dict] = {}


def _get_ssl_context() -> Optional[ssl.SSLContext]:
    """Cria contexto SSL que valida certificados com CA bundle customizada (layer Lambda)."""
    # Tentar caminhos possíveis do certificado
    cert_paths = [
        "/opt/ca_bundle.crt",     # Layer nova (layer-crito-pki-dev/prod)
        "/opt/certs/ca_bundle.crt",  # Layer legada
    ]

    for cert_path in cert_paths:
        if os.path.isfile(cert_path):
            try:
                context = ssl.create_default_context()
                context.load_verify_locations(cafile=cert_path)
                log_event(
                    _logger, "ssl.certificado_carregado",
                    level="debug",
                    caminho=cert_path,
                )
                return context
            except Exception as e:
                log_event(
                    _logger, "ssl.erro_carregando_cert",
                    level="warning",
                    caminho=cert_path,
                    erro=str(e),
                )

    # Fallback: usar certificate store do SO
    log_event(
        _logger, "ssl.usando_certificado_sistema",
        level="debug",
    )
    return ssl.create_default_context()


@dataclass
class OAuth2Manager:
    """Manager para autenticação M2M com o STS interno do Itaú."""

    token_url: str
    client_id: str
    client_secret: str
    margem_renovacao_s: int = 60  # Renovar 60s antes de expirar
    timeout_s: float = 5.0

    # Headers customizados do Itaú (lê do environment, permite override)
    itau_apikey: str = field(default_factory=lambda: os.environ.get("ITAU_API_KEY", ""))
    itau_correlationid: str = field(default_factory=lambda: os.environ.get("ITAU_CORRELATION_ID", ""))
    itau_flowid: str = field(default_factory=lambda: os.environ.get("ITAU_FLOW_ID", ""))

    def __post_init__(self):
        """Validar configuração após inicialização."""
        if not self.token_url:
            raise ValueError("token_url é obrigatório")
        if not self.client_id:
            raise ValueError("client_id é obrigatório")
        if not self.client_secret:
            raise ValueError("client_secret é obrigatório")

        log_event(
            _logger,
            "oauth2.manager.inicializado",
            level="info",
            token_url=self.token_url,
            client_id_length=len(self.client_id),
            has_apikey=bool(self.itau_apikey),
            has_correlationid=bool(self.itau_correlationid),
            has_flowid=bool(self.itau_flowid),
        )

    def get_token(self) -> str:
        """Obtém token válido (usa cache se disponível, renova se necessário)."""
        agora = time.time()

        # Verificar cache
        if self.token_url in _token_cache:
            cache_entry = _token_cache[self.token_url]
            expira_em = cache_entry["expira_em"]
            margem_renovacao = cache_entry.get("margem_renovacao_s", self.margem_renovacao_s)

            # Token ainda é válido?
            if agora < (expira_em - margem_renovacao):
                log_event(
                    _logger,
                    "oauth2.token.cache_hit",
                    level="debug",
                    segundos_restantes=int(expira_em - agora),
                )
                return cache_entry["access_token"]

        # Token expirado ou não em cache → obter novo
        log_event(
            _logger,
            "oauth2.token.renovando",
            level="info",
            token_url=self.token_url,
        )

        token, expires_in = self._obter_token()

        # Armazenar em cache
        _token_cache[self.token_url] = {
            "access_token": token,
            "expira_em": agora + expires_in,
            "margem_renovacao_s": self.margem_renovacao_s,
        }

        log_event(
            _logger,
            "oauth2.token.obtido",
            level="info",
            expires_in=expires_in,
            token_url=self.token_url,
        )

        return token

    def _obter_token(self) -> tuple[str, int]:
        """Faz a requisição POST ao STS e retorna (token, ttl_segundos)."""
        corpo = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }).encode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Headers obrigatórios do Itaú
        if self.itau_apikey:
            headers["x-itau-apikey"] = self.itau_apikey
        if self.itau_correlationid:
            headers["x-itau-correlationid"] = self.itau_correlationid
        if self.itau_flowid:
            headers["x-itau-flowid"] = self.itau_flowid

        log_event(
            _logger,
            "oauth2.requisicao.enviando",
            level="debug",
            token_url=self.token_url,
            headers_enviados=list(headers.keys()),
        )

        try:
            req = urllib.request.Request(
                self.token_url,
                data=corpo,
                method="POST",
                headers=headers,
            )

            ssl_context = _get_ssl_context()

            with urllib.request.urlopen(req, timeout=self.timeout_s, context=ssl_context) as response:
                data = json.loads(response.read().decode("utf-8"))

            token = data.get("access_token")
            if not token:
                raise ValueError("access_token não encontrado na resposta do STS")

            expires_in = int(data.get("expires_in", 3600))

            log_event(
                _logger,
                "oauth2.token.sucesso",
                level="info",
                expires_in=expires_in,
            )

            return token, expires_in

        except urllib.error.HTTPError as e:
            try:
                erro_body = e.read().decode("utf-8")
            except Exception:
                erro_body = str(e)

            log_event(
                _logger,
                "oauth2.erro.http",
                level="error",
                token_url=self.token_url,
                status_code=e.code,
                erro_body=erro_body,
            )
            raise

        except urllib.error.URLError as e:
            log_event(
                _logger,
                "oauth2.erro.rede",
                level="error",
                token_url=self.token_url,
                erro=str(e),
            )
            raise

        except json.JSONDecodeError as e:
            log_event(
                _logger,
                "oauth2.erro.json",
                level="error",
                token_url=self.token_url,
                erro=str(e),
            )
            raise

        except Exception as e:
            log_event(
                _logger,
                "oauth2.erro.desconhecido",
                level="error",
                token_url=self.token_url,
                tipo_erro=type(e).__name__,
                erro=str(e),
            )
            raise

    def get_auth_header(self) -> dict[str, str]:
        """Retorna o header Authorization pronto para usar em requisições."""
        token = self.get_token()
        return {"Authorization": f"Bearer {token}"}

    def clear_cache(self) -> None:
        """Limpa o cache de token (útil para testes)."""
        if self.token_url in _token_cache:
            del _token_cache[self.token_url]
            log_event(_logger, "oauth2.cache.limpo", level="debug", token_url=self.token_url)

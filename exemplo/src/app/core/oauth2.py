"""Módulo de autenticação OAuth2 para chamadas M2M com cache de token."""
from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass

import httpx

from app.core.http_client import get_client
from app.core.logging import get_logger, log_event

_logger = get_logger("bff.oauth2")

# Cache de tokens por (token_url, client_id) - evita colisão entre managers
# com credenciais diferentes apontando para o mesmo endpoint de token.
_token_cache: dict[str, "OAuth2Token"] = {}
_cache_lock: asyncio.Lock | None = None
_cache_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_cache_lock() -> asyncio.Lock:
    """Lock do cache, recriado se o event loop mudou (ver core/http_client.py)."""
    global _cache_lock, _cache_lock_loop
    loop = asyncio.get_running_loop()
    if _cache_lock is None or _cache_lock_loop is not loop:
        _cache_lock = asyncio.Lock()
        _cache_lock_loop = loop
    return _cache_lock


@dataclass
class OAuth2Token:
    """Resposta de token OAuth2."""
    access_token: str
    token_type: str
    expires_in: int
    expiration_time: float


class OAuth2Manager:
    """Gerencia autenticação OAuth2 para chamadas M2M de API."""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        timeout: float = 10.0,
        correlation_id_prefix: str = "bff-faturamento",
        use_basic_auth: bool = True,
    ):
        """Inicializa o gerenciador OAuth2.

        Args:
            token_url: URL do endpoint de token OAuth2
            client_id: ID do cliente OAuth2
            client_secret: Segredo do cliente OAuth2
            timeout: Timeout em segundos para requisições HTTP
            correlation_id_prefix: Prefixo para IDs de correlação
            use_basic_auth: Se True, usa Authorization Basic (RFC 6749). Se
                False, envia credentials no body (padrão interno Itaú).
        """
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.correlation_id_prefix = correlation_id_prefix
        self.use_basic_auth = use_basic_auth
        self._cache_key = f"{token_url}:{client_id}"

        if not use_basic_auth:
            log_event(
                _logger,
                "bff.oauth2_body_credentials_mode",
                level="info",
                detail="credentials no body (nao-padrao RFC 6749, requisito STS interno Itau)",
            )

    def _montar_requisicao_token(self) -> tuple[dict[str, str], dict[str, str], str]:
        """Monta headers e dados de form comuns aos dois modos de auth.

        Retorna (headers, dados_form, correlation_id).
        """
        correlation_id = f"{self.correlation_id_prefix}-{uuid.uuid4().hex[:8]}"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "x-itau-apikey": self.client_id,
            "x-itau-correlationid": correlation_id,
            "x-itau-flowid": self.correlation_id_prefix,
        }
        dados: dict[str, str] = {"grant_type": "client_credentials"}

        if self.use_basic_auth:
            # RFC 6749 Section 2.3.1 - Client Password (Basic Auth)
            credenciais = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {credenciais}"
        else:
            # Padrão STS interno Itaú - credentials no body
            dados["client_id"] = self.client_id
            dados["client_secret"] = self.client_secret

        return headers, dados, correlation_id

    async def _solicitar_token(self) -> OAuth2Token:
        """Solicita um novo token OAuth2 do endpoint de token.

        Levanta:
            RuntimeError: Se a solicitação de token falhar
        """
        headers, dados, correlation_id = self._montar_requisicao_token()

        masked_id = (
            self.client_id[:4] + "****" + self.client_id[-4:]
            if len(self.client_id) > 8 else "****"
        )
        log_event(
            _logger, "bff.oauth2_token_request", level="debug",
            token_url=self.token_url, client_id=masked_id, correlation_id=correlation_id,
        )

        try:
            client = await get_client()
            response = await client.post(
                self.token_url, data=dados, headers=headers, timeout=self.timeout,
            )
            response.raise_for_status()
            token_data = response.json()
        except httpx.HTTPStatusError as e:
            log_event(
                _logger, "bff.oauth2_token_http_error", level="error",
                status=e.response.status_code, correlation_id=correlation_id,
            )
            raise RuntimeError(
                f"Solicitacao de token OAuth2 falhou: {e.response.status_code}"
            ) from e
        except httpx.HTTPError as e:
            log_event(
                _logger, "bff.oauth2_token_unreachable", level="error",
                erro=str(e), correlation_id=correlation_id,
            )
            raise RuntimeError(f"Endpoint de token OAuth2 nao alcancavel: {e}") from e
        except ValueError as e:
            # response.json() malformado - NAO logar o corpo (pode conter token)
            log_event(
                _logger, "bff.oauth2_token_invalid_json", level="error",
                correlation_id=correlation_id,
            )
            raise RuntimeError(f"Resposta JSON invalida do endpoint de token: {e}") from e

        try:
            access_token = token_data["access_token"]
        except KeyError as e:
            log_event(
                _logger, "bff.oauth2_token_missing_field", level="error",
                campo=str(e), correlation_id=correlation_id,
            )
            raise RuntimeError(f"Campo obrigatorio ausente na resposta de token: {e}") from e

        # Buffer dinamico de expiracao: 10% do TTL, minimo 60s
        expires_in = token_data.get("expires_in", 3600)
        buffer = max(60, int(expires_in * 0.1))
        expiration_time = time.time() + expires_in - buffer

        return OAuth2Token(
            access_token=access_token,
            token_type=token_data.get("token_type", "Bearer"),
            expires_in=expires_in,
            expiration_time=expiration_time,
        )

    async def get_token(self) -> str:
        """Obtém um token de acesso OAuth2 válido, usando cache quando disponível.

        Retorna:
            A string do token de acesso

        Levanta:
            RuntimeError: Se a obtenção do token falhar
        """
        lock = _get_cache_lock()

        async with lock:
            cached = _token_cache.get(self._cache_key)
            if cached and time.time() < cached.expiration_time:
                return cached.access_token
            if cached:
                del _token_cache[self._cache_key]

        # Solicita fora do lock para nao bloquear outras chaves durante o I/O
        token = await self._solicitar_token()

        async with lock:
            _token_cache[self._cache_key] = token

        return token.access_token

    async def get_auth_header(self) -> dict[str, str]:
        """Obtém o cabeçalho Authorization com o token de acesso."""
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}


def clear_token_cache() -> None:
    """Limpa o cache de tokens OAuth2 (útil em testes)."""
    _token_cache.clear()

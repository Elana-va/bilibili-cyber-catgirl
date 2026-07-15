from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

from cyber_catgirl.security.credential_store import (
    DeepSeekCredentialData,
    DeepSeekCredentialStore,
)

OFFICIAL_BASE_URL = "https://api.deepseek.com"
ALLOWED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})
DEFAULT_MODEL = "deepseek-v4-flash"


class InvalidApiKey(RuntimeError):
    pass


class InsufficientBalance(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class DeepSeekUnavailable(RuntimeError):
    pass


class SelectedModelUnavailable(RuntimeError):
    pass


class EnvironmentCredentialManaged(RuntimeError):
    pass


class ModelsProbe(Protocol):
    async def list_models(self, api_key: str) -> set[str]: ...


@dataclass(frozen=True)
class DeepSeekConnectionView:
    configured: bool
    verified: bool
    source: str
    model: str | None
    verified_at: str | None


class DeepSeekModelsProbe:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def list_models(self, api_key: str) -> set[str]:
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=self.timeout_seconds
            ) as client:
                response = await client.get(
                    f"{OFFICIAL_BASE_URL}/models",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )
        except httpx.RequestError as exc:
            raise DeepSeekUnavailable() from exc
        if response.status_code == 401:
            raise InvalidApiKey()
        if response.status_code == 402:
            raise InsufficientBalance()
        if response.status_code == 429:
            raise RateLimited()
        if response.status_code >= 500:
            raise DeepSeekUnavailable()
        if response.status_code != 200:
            raise DeepSeekUnavailable()
        try:
            return {item["id"] for item in response.json()["data"]}
        except (KeyError, TypeError, ValueError) as exc:
            raise DeepSeekUnavailable() from exc


class DeepSeekConnectionService:
    def __init__(
        self,
        store: DeepSeekCredentialStore,
        probe: ModelsProbe,
        *,
        env_api_key: str | None = None,
        env_model: str = DEFAULT_MODEL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.probe = probe
        self.env_api_key = env_api_key or None
        self.env_model = env_model
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._local_verified_override: bool | None = None
        self._environment_verified = False

    def configured(self) -> bool:
        return self.store.configured() or self.env_api_key is not None

    def connection_view(self) -> DeepSeekConnectionView:
        local = self.store.load()
        if local:
            return DeepSeekConnectionView(
                True,
                self._local_verified_override is not False,
                "local_encrypted",
                local.model,
                local.verified_at,
            )
        if self.env_api_key:
            return DeepSeekConnectionView(
                True,
                self._environment_verified,
                "environment",
                self.env_model,
                None,
            )
        return DeepSeekConnectionView(False, False, "none", None, None)

    async def connect(self, api_key: str, model: str) -> DeepSeekConnectionView:
        if model not in ALLOWED_MODELS:
            raise ValueError("unsupported_model")
        models = await self.probe.list_models(api_key)
        if model not in models:
            raise SelectedModelUnavailable()
        credential = DeepSeekCredentialData(api_key, model, self.clock().isoformat())
        self.store.save(credential)
        self._local_verified_override = True
        return self.connection_view()

    async def verify(self) -> DeepSeekConnectionView:
        local = self.store.load()
        if local:
            try:
                models = await self.probe.list_models(local.api_key)
                if local.model not in models:
                    raise SelectedModelUnavailable()
            except Exception:
                self._local_verified_override = False
                raise
            self.store.save(replace(local, verified_at=self.clock().isoformat()))
            self._local_verified_override = True
            return self.connection_view()
        if self.env_api_key:
            try:
                models = await self.probe.list_models(self.env_api_key)
                if self.env_model not in models:
                    raise SelectedModelUnavailable()
            except Exception:
                self._environment_verified = False
                raise
            self._environment_verified = True
            return DeepSeekConnectionView(
                True,
                True,
                "environment",
                self.env_model,
                self.clock().isoformat(),
            )
        return self.connection_view()

    def disconnect(self) -> None:
        if self.store.configured():
            self.store.delete()
            self._local_verified_override = None
            return
        if self.env_api_key:
            raise EnvironmentCredentialManaged()

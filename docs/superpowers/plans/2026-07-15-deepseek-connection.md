# DeepSeek Secure Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a localhost-only DeepSeek connection flow that validates an API key against the official `/models` endpoint, stores it with Windows DPAPI, and exposes only non-sensitive status in the settings UI.

**Architecture:** A dedicated encrypted credential store owns DeepSeek secrets, while a connection service coordinates an injectable HTTP probe, credential precedence, and public status views. A focused FastAPI router exposes connect/verify/disconnect operations, and a standalone browser module renders the settings card without ever persisting or redisplaying the key.

**Tech Stack:** Python 3.11–3.12, FastAPI, Pydantic, httpx, Windows DPAPI, Jinja2, vanilla JavaScript, pytest, Ruff

## Global Constraints

- Page-submitted API keys and later verification requests must use exactly `https://api.deepseek.com`.
- The only selectable models are `deepseek-v4-flash` and `deepseek-v4-pro`; default to `deepseek-v4-flash`.
- Never place an API key in a database, template context, URL, browser storage, log, exception response, or model context.
- API responses may expose only configured/verified state, source, model, and verification time.
- Save local credentials only after successful `/models` authentication and selected-model availability checks.
- Preserve an existing local credential when a replacement key fails validation.
- Local DPAPI credentials take precedence over legacy `DEEPSEEK_API_KEY`; environment-managed credentials cannot be deleted from the UI.
- This phase must not call `/chat/completions`, read Bilibili comments, generate content, publish content, or alter `manual_only` safety behavior.

---

## File Map

- `src/cyber_catgirl/security/credential_store.py`: DeepSeek credential data and DPAPI-backed store.
- `src/cyber_catgirl/services/deepseek_connection.py`: public connection view, official `/models` probe, error taxonomy, credential precedence, connect/verify/disconnect orchestration.
- `src/cyber_catgirl/web/deepseek_auth.py`: request schema and non-sensitive FastAPI endpoints.
- `src/cyber_catgirl/web/routes.py`: attach the new router and carry the service in runtime state.
- `src/cyber_catgirl/main.py`: construct the DeepSeek store/service and allow test injection.
- `src/cyber_catgirl/web/pages.py`: expose only a configured boolean to initial page rendering.
- `src/cyber_catgirl/web/templates/settings.html`: DeepSeek connection card markup.
- `src/cyber_catgirl/web/templates/base.html`: load the standalone DeepSeek browser module.
- `src/cyber_catgirl/web/static/deepseek-connection.js`: connect, refresh, verify, disconnect, and key-clearing behavior.
- `src/cyber_catgirl/web/static/app.css`: visual states for the DeepSeek card.
- `src/cyber_catgirl/agent/client.py`: update the future generation client's default model only.
- `tests/test_deepseek_credential_store.py`: encrypted storage contract.
- `tests/test_deepseek_connection.py`: probe/service behavior and secret-preservation tests.
- `tests/test_deepseek_auth_api.py`: endpoint contract and error mapping.
- `tests/test_admin_visual_contract.py`: settings markup contract.
- `tests/test_agent_client.py`: V4 default-model regression test.
- `README.md` and `.env.example`: operator-facing connection notes and updated model default.

---

### Task 1: DPAPI-backed DeepSeek credential storage

**Files:**
- Modify: `src/cyber_catgirl/security/credential_store.py`
- Create: `tests/test_deepseek_credential_store.py`

**Interfaces:**
- Produces: `DeepSeekCredentialData(api_key: str, model: str, verified_at: str)`.
- Produces: `DeepSeekCredentialStore(path: Path, protector: DataProtector)` with `configured()`, `save(data)`, `load()`, and `delete()`.
- Consumes: existing `DataProtector`, `CredentialUnreadable`, and atomic temporary-file pattern.

- [ ] **Step 1: Write encrypted round-trip and corrupt-ciphertext tests**

```python
# tests/test_deepseek_credential_store.py
from pathlib import Path

import pytest

from cyber_catgirl.security.credential_store import (
    CredentialUnreadable,
    DeepSeekCredentialData,
    DeepSeekCredentialStore,
)


class PrefixProtector:
    def protect(self, value: bytes) -> bytes:
        return b"encrypted:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"encrypted:"):
            raise ValueError("invalid ciphertext")
        return value.removeprefix(b"encrypted:")[::-1]


def test_deepseek_store_round_trip_never_writes_plaintext(tmp_path: Path):
    path = tmp_path / "secrets" / "deepseek-credential.bin"
    store = DeepSeekCredentialStore(path, PrefixProtector())
    credential = DeepSeekCredentialData(
        api_key="sk-secret-value",
        model="deepseek-v4-flash",
        verified_at="2026-07-15T08:00:00+00:00",
    )

    store.save(credential)

    assert b"sk-secret-value" not in path.read_bytes()
    assert store.load() == credential
    assert not path.with_suffix(".tmp").exists()


def test_deepseek_store_overwrites_and_deletes(tmp_path: Path):
    path = tmp_path / "deepseek-credential.bin"
    store = DeepSeekCredentialStore(path, PrefixProtector())
    store.save(DeepSeekCredentialData("old", "deepseek-v4-flash", "old-time"))
    store.save(DeepSeekCredentialData("new", "deepseek-v4-pro", "new-time"))

    assert store.load().api_key == "new"
    store.delete()
    assert store.configured() is False
    assert store.load() is None


def test_deepseek_store_maps_corrupt_ciphertext_to_domain_error(tmp_path: Path):
    path = tmp_path / "deepseek-credential.bin"
    path.write_bytes(b"not-encrypted")

    with pytest.raises(CredentialUnreadable, match="DeepSeek 凭证无法解密"):
        DeepSeekCredentialStore(path, PrefixProtector()).load()
```

- [ ] **Step 2: Run tests and confirm the missing-type failure**

Run: `pytest tests/test_deepseek_credential_store.py -v`

Expected: collection fails because `DeepSeekCredentialData` and `DeepSeekCredentialStore` do not exist.

- [ ] **Step 3: Add the focused DeepSeek store**

Append to `src/cyber_catgirl/security/credential_store.py`:

```python
@dataclass(frozen=True)
class DeepSeekCredentialData:
    api_key: str
    model: str
    verified_at: str


class DeepSeekCredentialStore:
    def __init__(self, path: Path, protector: DataProtector):
        self.path = path
        self.protector = protector

    def configured(self) -> bool:
        return self.path.is_file()

    def save(self, data: DeepSeekCredentialData) -> None:
        plaintext = json.dumps(asdict(data), ensure_ascii=False).encode("utf-8")
        ciphertext = self.protector.protect(plaintext)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(ciphertext)
        temporary.replace(self.path)

    def load(self) -> DeepSeekCredentialData | None:
        if not self.configured():
            return None
        try:
            plaintext = self.protector.unprotect(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
            return DeepSeekCredentialData(**payload)
        except CredentialUnreadable:
            raise
        except Exception as exc:
            raise CredentialUnreadable("DeepSeek 凭证无法解密") from exc

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run the focused and existing credential tests**

Run: `pytest tests/test_deepseek_credential_store.py tests/test_credential_store.py -v`

Expected: all tests pass, including the Windows DPAPI round trip.

- [ ] **Step 5: Commit the storage unit**

```bash
git add src/cyber_catgirl/security/credential_store.py tests/test_deepseek_credential_store.py
git commit -m "feat: securely store DeepSeek credentials"
```

---

### Task 2: Official-model probe and connection service

**Files:**
- Create: `src/cyber_catgirl/services/deepseek_connection.py`
- Create: `tests/test_deepseek_connection.py`

**Interfaces:**
- Consumes: `DeepSeekCredentialStore` and `DeepSeekCredentialData` from Task 1.
- Produces: `DeepSeekConnectionView(configured: bool, verified: bool, source: str, model: str | None, verified_at: str | None)`.
- Produces: `DeepSeekModelsProbe.list_models(api_key: str) -> set[str]`.
- Produces: `DeepSeekConnectionService.connection_view()`, `connect(api_key, model)`, `verify()`, and `disconnect()`.
- Produces errors: `InvalidApiKey`, `InsufficientBalance`, `RateLimited`, `DeepSeekUnavailable`, `SelectedModelUnavailable`, and `EnvironmentCredentialManaged`.

- [ ] **Step 1: Write service tests with an injectable probe and clock**

```python
# tests/test_deepseek_connection.py
from datetime import datetime, timezone

import httpx
import pytest

from cyber_catgirl.security.credential_store import DeepSeekCredentialData
from cyber_catgirl.services.deepseek_connection import (
    DeepSeekConnectionService,
    DeepSeekModelsProbe,
    DeepSeekUnavailable,
    EnvironmentCredentialManaged,
    InsufficientBalance,
    InvalidApiKey,
    RateLimited,
    SelectedModelUnavailable,
)


class MemoryStore:
    def __init__(self, credential=None):
        self.credential = credential

    def configured(self):
        return self.credential is not None

    def save(self, credential):
        self.credential = credential

    def load(self):
        return self.credential

    def delete(self):
        self.credential = None


class FakeProbe:
    def __init__(self, models=None, error=None):
        self.models = models or {"deepseek-v4-flash", "deepseek-v4-pro"}
        self.error = error
        self.keys = []

    async def list_models(self, api_key):
        self.keys.append(api_key)
        if self.error:
            raise self.error
        return self.models


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


async def test_connect_validates_then_saves_and_returns_public_view():
    store = MemoryStore()
    probe = FakeProbe()
    service = DeepSeekConnectionService(store, probe, clock=lambda: NOW)

    view = await service.connect("sk-secret", "deepseek-v4-flash")

    assert probe.keys == ["sk-secret"]
    assert store.credential == DeepSeekCredentialData(
        "sk-secret", "deepseek-v4-flash", NOW.isoformat()
    )
    assert view.source == "local_encrypted"
    assert "secret" not in repr(view)


async def test_failed_replacement_preserves_existing_credential():
    old = DeepSeekCredentialData("old-secret", "deepseek-v4-flash", "old-time")
    store = MemoryStore(old)
    service = DeepSeekConnectionService(store, FakeProbe(error=InvalidApiKey()))

    with pytest.raises(InvalidApiKey):
        await service.connect("bad-secret", "deepseek-v4-pro")

    assert store.credential == old


async def test_connect_rejects_unavailable_or_unapproved_model():
    service = DeepSeekConnectionService(MemoryStore(), FakeProbe({"deepseek-v4-flash"}))
    with pytest.raises(SelectedModelUnavailable):
        await service.connect("sk-secret", "deepseek-v4-pro")
    with pytest.raises(ValueError, match="unsupported_model"):
        await service.connect("sk-secret", "other-model")


async def test_environment_fallback_is_public_and_cannot_be_deleted():
    service = DeepSeekConnectionService(
        MemoryStore(), FakeProbe(), env_api_key="env-secret", env_model="deepseek-v4-flash"
    )
    assert service.connection_view().source == "environment"
    with pytest.raises(EnvironmentCredentialManaged):
        service.disconnect()


async def test_failed_reverification_preserves_key_but_marks_view_unverified():
    old = DeepSeekCredentialData("old-secret", "deepseek-v4-flash", "old-time")
    service = DeepSeekConnectionService(
        MemoryStore(old), FakeProbe(error=DeepSeekUnavailable())
    )

    with pytest.raises(DeepSeekUnavailable):
        await service.verify()

    view = service.connection_view()
    assert view.configured is True
    assert view.verified is False
    assert service.store.credential == old


async def test_probe_maps_status_and_never_includes_key_in_errors():
    async def handler(request: httpx.Request):
        assert request.url == "https://api.deepseek.com/models"
        assert request.headers["Authorization"] == "Bearer sk-secret"
        return httpx.Response(401, json={"error": {"message": "echo sk-secret"}})

    probe = DeepSeekModelsProbe(
        transport=httpx.MockTransport(handler), timeout_seconds=1
    )
    with pytest.raises(InvalidApiKey) as error:
        await probe.list_models("sk-secret")
    assert "sk-secret" not in str(error.value)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(402, InsufficientBalance), (429, RateLimited), (500, DeepSeekUnavailable)],
)
async def test_probe_maps_transient_upstream_errors(status, error_type):
    async def handler(request: httpx.Request):
        return httpx.Response(status, json={})

    probe = DeepSeekModelsProbe(transport=httpx.MockTransport(handler))
    with pytest.raises(error_type):
        await probe.list_models("sk-secret")
```

- [ ] **Step 2: Run the tests and confirm the module-not-found failure**

Run: `pytest tests/test_deepseek_connection.py -v`

Expected: collection fails because `cyber_catgirl.services.deepseek_connection` does not exist.

- [ ] **Step 3: Implement the probe, public view, and service**

Create `src/cyber_catgirl/services/deepseek_connection.py`:

```python
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
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
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
                True, self._environment_verified, "environment", self.env_model, None
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
                True, True, "environment", self.env_model, self.clock().isoformat()
            )
        return self.connection_view()

    def disconnect(self) -> None:
        if self.store.configured():
            self.store.delete()
            self._local_verified_override = None
            return
        if self.env_api_key:
            raise EnvironmentCredentialManaged()
```

- [ ] **Step 4: Run service tests and lint the new module**

Run: `pytest tests/test_deepseek_connection.py -v && ruff check src/cyber_catgirl/services/deepseek_connection.py tests/test_deepseek_connection.py`

Expected: all tests pass and Ruff prints no errors.

- [ ] **Step 5: Commit the service unit**

```bash
git add src/cyber_catgirl/services/deepseek_connection.py tests/test_deepseek_connection.py
git commit -m "feat: validate DeepSeek connections"
```

---

### Task 3: Non-sensitive FastAPI connection endpoints

**Files:**
- Create: `src/cyber_catgirl/web/deepseek_auth.py`
- Modify: `src/cyber_catgirl/web/routes.py`
- Modify: `src/cyber_catgirl/main.py`
- Modify: `src/cyber_catgirl/web/pages.py`
- Create: `tests/test_deepseek_auth_api.py`

**Interfaces:**
- Consumes: `DeepSeekConnectionService` and errors from Task 2.
- Produces: `GET /api/deepseek/connection`, `POST /api/deepseek/connection`, `POST /api/deepseek/verify`, and `POST /api/deepseek/disconnect`.
- Produces: `create_app(..., deepseek_service=None)` injection point.

- [ ] **Step 1: Write endpoint contract and secret-leak tests**

```python
# tests/test_deepseek_auth_api.py
from dataclasses import replace

from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.services.deepseek_connection import (
    DeepSeekConnectionView,
    InvalidApiKey,
)


class FakeBilibiliLogin:
    def cancel_all(self):
        pass


class FakeBilibiliAccount:
    def configured(self):
        return False


class FakeDeepSeekService:
    def __init__(self):
        self.view = DeepSeekConnectionView(False, False, "none", None, None)
        self.connected_with = None

    def configured(self):
        return self.view.configured

    def connection_view(self):
        return self.view

    async def connect(self, api_key, model):
        self.connected_with = (api_key, model)
        if api_key == "bad-secret":
            raise InvalidApiKey()
        self.view = DeepSeekConnectionView(
            True, True, "local_encrypted", model, "2026-07-15T08:00:00+00:00"
        )
        return self.view

    async def verify(self):
        self.view = replace(self.view, verified=True)
        return self.view

    def disconnect(self):
        self.view = DeepSeekConnectionView(False, False, "none", None, None)


def make_client():
    deepseek = FakeDeepSeekService()
    app = create_app(
        Settings(),
        session_factory=create_session_factory("sqlite+pysqlite:///:memory:"),
        login_manager=FakeBilibiliLogin(),
        account_service=FakeBilibiliAccount(),
        deepseek_service=deepseek,
    )
    return TestClient(app), deepseek


def test_connect_and_status_never_return_api_key():
    client, service = make_client()
    response = client.post(
        "/api/deepseek/connection",
        json={"api_key": "sk-secret-value", "model": "deepseek-v4-flash"},
    )

    assert response.status_code == 200
    assert service.connected_with == ("sk-secret-value", "deepseek-v4-flash")
    assert response.json()["source"] == "local_encrypted"
    assert "sk-secret-value" not in response.text
    assert "sk-secret-value" not in client.get("/api/deepseek/connection").text


def test_invalid_key_uses_stable_error_without_echoing_secret():
    client, _ = make_client()
    response = client.post(
        "/api/deepseek/connection",
        json={"api_key": "bad-secret", "model": "deepseek-v4-flash"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_api_key"}
    assert "bad-secret" not in response.text


def test_connect_rejects_unknown_model_before_service_call():
    client, service = make_client()
    response = client.post(
        "/api/deepseek/connection",
        json={"api_key": "sk-secret", "model": "other-model"},
    )
    assert response.status_code == 422
    assert service.connected_with is None


def test_verify_and_disconnect_return_public_state():
    client, _ = make_client()
    client.post(
        "/api/deepseek/connection",
        json={"api_key": "sk-secret", "model": "deepseek-v4-pro"},
    )
    assert client.post("/api/deepseek/verify").json()["verified"] is True
    assert client.post("/api/deepseek/disconnect").json() == {
        "configured": False,
        "verified": False,
        "source": "none",
        "model": None,
        "verified_at": None,
    }
```

- [ ] **Step 2: Run the endpoint tests and confirm missing injection/router failures**

Run: `pytest tests/test_deepseek_auth_api.py -v`

Expected: tests fail because `create_app` has no `deepseek_service` parameter and the routes do not exist.

- [ ] **Step 3: Implement the focused router and stable error mapping**

Create `src/cyber_catgirl/web/deepseek_auth.py`:

```python
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cyber_catgirl.security.credential_store import (
    CredentialUnreadable,
    SecureStorageUnavailable,
)
from cyber_catgirl.services.deepseek_connection import (
    DeepSeekUnavailable,
    EnvironmentCredentialManaged,
    InsufficientBalance,
    InvalidApiKey,
    RateLimited,
    SelectedModelUnavailable,
)


class DeepSeekConnectRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)
    model: Literal["deepseek-v4-flash", "deepseek-v4-pro"]


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidApiKey):
        return HTTPException(401, "invalid_api_key")
    if isinstance(exc, InsufficientBalance):
        return HTTPException(402, "insufficient_balance")
    if isinstance(exc, RateLimited):
        return HTTPException(429, "rate_limited")
    if isinstance(exc, SelectedModelUnavailable):
        return HTTPException(409, "selected_model_unavailable")
    if isinstance(exc, EnvironmentCredentialManaged):
        return HTTPException(409, "environment_credential_managed")
    if isinstance(exc, SecureStorageUnavailable):
        return HTTPException(501, "secure_storage_unavailable")
    if isinstance(exc, CredentialUnreadable):
        return HTTPException(503, "credential_unreadable")
    return HTTPException(503, "deepseek_unavailable")


def build_deepseek_auth_router(service) -> APIRouter:
    router = APIRouter()

    @router.get("/api/deepseek/connection")
    def connection() -> dict:
        try:
            return asdict(service.connection_view())
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/deepseek/connection")
    async def connect(payload: DeepSeekConnectRequest) -> dict:
        try:
            return asdict(await service.connect(payload.api_key, payload.model))
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/deepseek/verify")
    async def verify() -> dict:
        try:
            return asdict(await service.verify())
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/deepseek/disconnect")
    def disconnect() -> dict:
        try:
            service.disconnect()
            return asdict(service.connection_view())
        except Exception as exc:
            raise _map_error(exc) from exc

    return router
```

- [ ] **Step 4: Wire the service into application construction and routing**

In `src/cyber_catgirl/web/routes.py`, import `build_deepseek_auth_router`, add `deepseek_service: object` to `RuntimeState`, and include:

```python
router.include_router(build_deepseek_auth_router(state.deepseek_service))
```

In `src/cyber_catgirl/main.py`, add imports and the optional argument:

```python
from os import getenv

from cyber_catgirl.security.credential_store import DeepSeekCredentialStore
from cyber_catgirl.services.deepseek_connection import (
    DEFAULT_MODEL,
    DeepSeekConnectionService,
    DeepSeekModelsProbe,
)

# create_app keyword argument
deepseek_service=None,
```

Before building `RuntimeState`, construct the default service:

```python
if deepseek_service is None:
    deepseek_store = DeepSeekCredentialStore(
        Path("data/secrets/deepseek-credential.bin"), DpapiProtector()
    )
    deepseek_service = DeepSeekConnectionService(
        deepseek_store,
        DeepSeekModelsProbe(),
        env_api_key=getenv("DEEPSEEK_API_KEY"),
        env_model=getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
    )
```

Pass `deepseek_service=deepseek_service` into `RuntimeState`.

In `src/cyber_catgirl/web/pages.py`, remove `from os import getenv` and replace:

```python
"llm_configured": bool(getenv("DEEPSEEK_API_KEY")),
```

with:

```python
"llm_configured": state.deepseek_service.configured(),
```

- [ ] **Step 5: Run endpoint and page regression tests**

Run: `pytest tests/test_deepseek_auth_api.py tests/test_bilibili_auth_api.py tests/test_admin_pages.py -v`

Expected: all selected tests pass; Bilibili routes remain unchanged.

- [ ] **Step 6: Commit the API unit**

```bash
git add src/cyber_catgirl/main.py src/cyber_catgirl/web/routes.py src/cyber_catgirl/web/pages.py src/cyber_catgirl/web/deepseek_auth.py tests/test_deepseek_auth_api.py
git commit -m "feat: expose secure DeepSeek connection API"
```

---

### Task 4: Settings-page connection experience

**Files:**
- Modify: `src/cyber_catgirl/web/templates/settings.html`
- Modify: `src/cyber_catgirl/web/templates/base.html`
- Create: `src/cyber_catgirl/web/static/deepseek-connection.js`
- Modify: `src/cyber_catgirl/web/static/app.css`
- Modify: `tests/test_admin_visual_contract.py`

**Interfaces:**
- Consumes: all `/api/deepseek/*` endpoints from Task 3 and global `showToast` / `confirmAction` helpers.
- Produces: DOM contract rooted at `[data-deepseek-root]`; the password value is cleared in a `finally` block after every connect attempt.

- [ ] **Step 1: Add visual-contract assertions first**

Append to the settings-page test in `tests/test_admin_visual_contract.py`:

```python
assert 'data-deepseek-root' in html
assert 'type="password"' in html
assert 'autocomplete="new-password"' in html
assert 'data-deepseek-model' in html
assert 'value="deepseek-v4-flash"' in html
assert 'value="deepseek-v4-pro"' in html
assert 'data-deepseek-connect' in html
assert 'data-deepseek-verify' in html
assert 'data-deepseek-disconnect' in html
assert '/static/deepseek-connection.js' in html
```

Also extend the JavaScript syntax loop in that file:

```python
for script in ["app.js", "bilibili-login.js", "deepseek-connection.js"]:
```

- [ ] **Step 2: Run the visual test and confirm missing-markup failures**

Run: `pytest tests/test_admin_visual_contract.py -v`

Expected: fail on `data-deepseek-root`.

- [ ] **Step 3: Replace the passive DeepSeek row with an interactive card**

In `src/cyber_catgirl/web/templates/settings.html`, replace the existing DeepSeek list row with:

```html
<section class="deepseek-card" data-deepseek-root>
  <header class="deepseek-card-heading">
    <span class="connection-icon">AI</span>
    <span><strong>DeepSeek 模型</strong><small>本机 DPAPI 加密密钥</small></span>
    <span class="state-badge state-disabled" data-deepseek-status>未连接</span>
  </header>
  <form class="deepseek-connect-form" data-deepseek-form>
    <label>
      <span>API Key</span>
      <input type="password" name="api_key" autocomplete="new-password"
             maxlength="512" required data-deepseek-key
             placeholder="仅提交给本机与 DeepSeek 官方验证">
    </label>
    <label>
      <span>模型</span>
      <select name="model" data-deepseek-model>
        <option value="deepseek-v4-flash">DeepSeek V4 Flash（推荐）</option>
        <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
      </select>
    </label>
    <button class="button button-primary" type="submit" data-deepseek-connect>
      验证并连接
    </button>
  </form>
  <div class="deepseek-connected" data-deepseek-connected hidden>
    <span><small>当前模型</small><strong data-deepseek-current-model>—</strong></span>
    <span><small>最近验证</small><strong data-deepseek-verified-at>—</strong></span>
    <span class="deepseek-actions">
      <button class="button button-secondary" type="button" data-deepseek-verify>重新验证</button>
      <button class="button button-danger-ghost" type="button" data-deepseek-disconnect>断开连接</button>
    </span>
  </div>
  <p class="deepseek-note">连接只调用官方模型列表，不发起对话生成，不产生模型回复。</p>
</section>
```

In `src/cyber_catgirl/web/templates/base.html`, add after `bilibili-login.js`:

```html
<script src="/static/deepseek-connection.js"></script>
```

- [ ] **Step 4: Implement safe browser behavior**

Create `src/cyber_catgirl/web/static/deepseek-connection.js`:

```javascript
(() => {
  const root = document.querySelector("[data-deepseek-root]");
  if (!root) return;

  const form = root.querySelector("[data-deepseek-form]");
  const keyInput = root.querySelector("[data-deepseek-key]");
  const modelInput = root.querySelector("[data-deepseek-model]");
  const statusBadge = root.querySelector("[data-deepseek-status]");
  const connectedPanel = root.querySelector("[data-deepseek-connected]");
  const modelText = root.querySelector("[data-deepseek-current-model]");
  const verifiedAt = root.querySelector("[data-deepseek-verified-at]");
  const verifyButton = root.querySelector("[data-deepseek-verify]");
  const disconnectButton = root.querySelector("[data-deepseek-disconnect]");
  const errors = {
    invalid_api_key: "API Key 无效，请检查后重试。",
    insufficient_balance: "DeepSeek 账户余额不足。",
    rate_limited: "验证过于频繁，请稍后重试。",
    selected_model_unavailable: "所选模型当前不可用。",
    environment_credential_managed: "该密钥由启动环境管理，请停止服务后移除环境变量。",
    secure_storage_unavailable: "当前系统无法使用 Windows 安全存储。",
    credential_unreadable: "本机保存的 DeepSeek 凭证无法解密。",
    deepseek_unavailable: "当前无法连接 DeepSeek，请稍后重试。",
  };

  async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = typeof payload.detail === "string" ? payload.detail : "deepseek_unavailable";
      throw new Error(errors[code] || "操作失败，请重试。");
    }
    return payload;
  }

  function render(view) {
    const configured = Boolean(view.configured);
    form.hidden = configured && view.source === "local_encrypted";
    connectedPanel.hidden = !configured;
    statusBadge.textContent = configured ? (view.verified ? "已连接" : "待验证") : "未连接";
    statusBadge.className = `state-badge state-${view.verified ? "active" : "disabled"}`;
    modelText.textContent = view.model || "—";
    verifiedAt.textContent = view.verified_at
      ? new Date(view.verified_at).toLocaleString("zh-CN")
      : "尚未验证";
    disconnectButton.hidden = view.source === "environment";
  }

  async function refresh() {
    try {
      render(await readJson(await fetch("/api/deepseek/connection")));
    } catch (error) {
      showToast(error.message, true);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const apiKey = keyInput.value;
    try {
      const response = await fetch("/api/deepseek/connection", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({api_key: apiKey, model: modelInput.value}),
      });
      render(await readJson(response));
      showToast("DeepSeek 已安全连接");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      keyInput.value = "";
    }
  });

  verifyButton.addEventListener("click", async () => {
    try {
      render(await readJson(await fetch("/api/deepseek/verify", {method: "POST"})));
      showToast("DeepSeek 连接验证通过");
    } catch (error) {
      await refresh();
      showToast(error.message, true);
    }
  });

  disconnectButton.addEventListener("click", () => {
    confirmAction("断开后将删除这台电脑保存的 DeepSeek API Key。确认继续吗？", async () => {
      try {
        render(await readJson(await fetch("/api/deepseek/disconnect", {method: "POST"})));
        showToast("DeepSeek 已断开");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });

  refresh();
})();
```

- [ ] **Step 5: Add the compact card styles**

Append to `src/cyber_catgirl/web/static/app.css`:

```css
.deepseek-card{display:grid;gap:12px;padding:16px;border:1px solid #e7e1f5;border-radius:16px;background:linear-gradient(135deg,#fbf9ff,#f3fbff)}
.deepseek-card-heading{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center}.deepseek-card-heading strong,.deepseek-card-heading small{display:block}.deepseek-card-heading small{margin-top:3px;color:var(--muted);font-size:8px}
.deepseek-connect-form{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(150px,.8fr) auto;gap:10px;align-items:end}.deepseek-connect-form label{display:grid;gap:5px}.deepseek-connect-form label>span{font-size:8px;font-weight:700;color:var(--muted)}
.deepseek-connected{display:grid;grid-template-columns:1fr 1fr auto;gap:14px;align-items:center}.deepseek-connected small,.deepseek-connected strong{display:block}.deepseek-connected small{font-size:8px;color:var(--muted)}.deepseek-connected strong{margin-top:4px;font-size:10px}.deepseek-actions{display:flex;gap:7px}.deepseek-note{margin:0;color:var(--muted);font-size:8px;line-height:1.6}
@media (max-width:760px){.deepseek-connect-form,.deepseek-connected{grid-template-columns:1fr}.deepseek-actions{flex-wrap:wrap}}
```

- [ ] **Step 6: Run visual regression tests**

Run: `pytest tests/test_admin_visual_contract.py tests/test_admin_pages.py -v`

Expected: all selected tests pass.

- [ ] **Step 7: Commit the UI unit**

```bash
git add src/cyber_catgirl/web/templates/settings.html src/cyber_catgirl/web/templates/base.html src/cyber_catgirl/web/static/deepseek-connection.js src/cyber_catgirl/web/static/app.css tests/test_admin_visual_contract.py
git commit -m "feat: add DeepSeek connection settings"
```

---

### Task 5: V4 default, documentation, full verification, and live acceptance

**Files:**
- Modify: `src/cyber_catgirl/agent/client.py`
- Create or modify: `tests/test_agent_client.py`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: `DEFAULT_MODEL = "deepseek-v4-flash"` from Task 2.
- Produces: a future generation client whose default is not the deprecated `deepseek-chat` alias.

- [ ] **Step 1: Add a default-model regression test**

```python
# tests/test_agent_client.py
from cyber_catgirl.agent.client import DeepSeekClient


def test_deepseek_client_defaults_to_v4_flash():
    client = DeepSeekClient("not-a-real-key")
    assert client.model == "deepseek-v4-flash"
```

- [ ] **Step 2: Run the test and confirm the legacy default failure**

Run: `pytest tests/test_agent_client.py -v`

Expected: fail because the current value is `deepseek-chat`.

- [ ] **Step 3: Reuse the canonical default constant**

In `src/cyber_catgirl/agent/client.py`, import and use:

```python
from cyber_catgirl.services.deepseek_connection import DEFAULT_MODEL

# constructor default
model: str = DEFAULT_MODEL,
```

- [ ] **Step 4: Update operator examples**

Add to `.env.example`:

```dotenv
DEEPSEEK_MODEL=deepseek-v4-flash
```

In `README.md`, document these exact facts:

```markdown
### DeepSeek 连接

打开本地管理台的“系统设置”，在 DeepSeek 卡片中输入 API Key 并选择
`deepseek-v4-flash`（默认）或 `deepseek-v4-pro`。系统仅使用官方
`https://api.deepseek.com/models` 验证连接，成功后由当前 Windows 用户的
DPAPI 加密保存在 `data/secrets/deepseek-credential.bin`；页面和接口不会回显密钥。

已有部署仍可使用 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和
`DEEPSEEK_MODEL` 环境变量。本机加密凭证优先于环境变量凭证。
```

- [ ] **Step 5: Run all automated verification**

Run: `pytest -q`

Expected: all tests pass.

Run: `ruff check .`

Expected: `All checks passed!`

Run: `git diff --check`

Expected: no output.

- [ ] **Step 6: Restart the localhost service and inspect the settings page**

Run the existing project start command, then open `http://127.0.0.1:8765/settings`.

Verify:

- DeepSeek shows “未连接” without a stored credential;
- the key field is a password input and is blank after a failed connection attempt;
- selecting both V4 models updates the submitted model;
- no browser-console errors occur;
- Bilibili remains connected and `manual_only` remains unchanged.

- [ ] **Step 7: Perform the real-key acceptance test locally**

Ask the user to paste the API Key only into the local password field, never into chat. Click “验证并连接” and verify:

- `GET /api/deepseek/connection` reports `source: local_encrypted` and never includes the key;
- a service restart preserves connected status, model, and `verified_at`;
- “重新验证” succeeds without invoking `/chat/completions`;
- “断开连接” removes only `data/secrets/deepseek-credential.bin`;
- service output and browser console contain no API Key.

- [ ] **Step 8: Commit documentation and final compatibility changes**

```bash
git add src/cyber_catgirl/agent/client.py tests/test_agent_client.py .env.example README.md
git commit -m "docs: complete DeepSeek V4 connection setup"
```

- [ ] **Step 9: Record final repository state**

Run: `git status --short && git log -5 --oneline`

Expected: clean working tree and the DeepSeek implementation commits visible at the top of `main`.

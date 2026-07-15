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
    view = service.connection_view()
    assert view.source == "environment"
    assert "env-secret" not in repr(view)
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

    probe = DeepSeekModelsProbe(transport=httpx.MockTransport(handler), timeout_seconds=1)
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


async def test_probe_returns_model_ids_from_official_response():
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "deepseek-v4-flash"},
                    {"id": "deepseek-v4-pro"},
                ],
            },
        )

    probe = DeepSeekModelsProbe(transport=httpx.MockTransport(handler))

    assert await probe.list_models("sk-secret") == {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    }

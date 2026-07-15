from dataclasses import replace

from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.services.deepseek_connection import (
    DeepSeekConnectionView,
    EnvironmentCredentialManaged,
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


class EnvironmentDeepSeekService(FakeDeepSeekService):
    def disconnect(self):
        raise EnvironmentCredentialManaged()


def make_client(deepseek=None):
    deepseek = deepseek or FakeDeepSeekService()
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


def test_environment_managed_key_cannot_be_deleted():
    client, _ = make_client(EnvironmentDeepSeekService())

    response = client.post("/api/deepseek/disconnect")

    assert response.status_code == 409
    assert response.json() == {"detail": "environment_credential_managed"}

from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.connectors.bilibili_login import (
    LoginPhase,
    LoginSessionNotFound,
    LoginSessionView,
)
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.services.bilibili_account import AccountIdentity, ConnectionView


class FakeLoginManager:
    def __init__(self):
        self.cancelled = False

    async def create_session(self):
        return LoginSessionView(
            "safe-session-id",
            LoginPhase.WAITING,
            "data:image/png;base64,ZmFrZS1wbmc=",
            180,
        )

    async def check_session(self, session_id):
        if session_id != "safe-session-id":
            raise LoginSessionNotFound("cookie=sess-secret")
        return LoginSessionView(session_id, LoginPhase.SCANNED, None, 170)

    def cancel_all(self):
        self.cancelled = True


class FakeAccountService:
    def __init__(self):
        self.deleted = False

    def configured(self):
        return not self.deleted

    async def connection_view(self):
        return ConnectionView(
            True,
            "verified",
            AccountIdentity("123", "测试账号", None),
        )

    def disconnect(self):
        self.deleted = True


def make_client():
    login = FakeLoginManager()
    account = FakeAccountService()
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    app = create_app(
        Settings(),
        session_factory=sessions,
        login_manager=login,
        account_service=account,
    )
    return TestClient(app), login, account


def test_qr_creation_and_status_never_return_credentials():
    client, _, _ = make_client()

    created = client.post("/api/bilibili/login/qr")
    payload = created.json()
    status = client.get(f"/api/bilibili/login/qr/{payload['session_id']}")

    assert created.status_code == 201
    assert payload["phase"] == "waiting"
    assert payload["qr_data_url"].startswith("data:image/png;base64,")
    assert status.status_code == 200
    assert status.json()["qr_data_url"] is None
    assert "sess-secret" not in created.text + status.text


def test_connection_response_contains_only_public_identity():
    client, _, _ = make_client()

    response = client.get("/api/bilibili/connection")

    assert response.json() == {
        "connected": True,
        "verification": "verified",
        "account": {"uid": "123", "name": "测试账号", "avatar_url": None},
    }


def test_login_does_not_change_runtime_safety_state():
    client, _, _ = make_client()
    before = client.get("/api/health").json()

    client.post("/api/bilibili/login/qr")

    assert client.get("/api/health").json() == before == {
        "status": "ok",
        "run_mode": "manual_only",
        "kill_switch": False,
    }


def test_disconnect_cancels_login_and_deletes_local_credential():
    client, login, account = make_client()

    response = client.post("/api/bilibili/disconnect")

    assert response.status_code == 200
    assert response.json() == {"connected": False}
    assert login.cancelled is True
    assert account.deleted is True


def test_unknown_login_session_returns_fixed_error_without_exception_text():
    client, _, _ = make_client()

    response = client.get("/api/bilibili/login/qr/unknown")

    assert response.status_code == 404
    assert response.json() == {"detail": "login_session_not_found"}
    assert "sess-secret" not in response.text

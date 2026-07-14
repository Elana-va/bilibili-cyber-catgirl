from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.services.audit import AuditService


def make_client():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    return TestClient(create_app(Settings(), session_factory=sessions)), sessions


def test_logs_never_render_nested_credentials():
    client, sessions = make_client()
    AuditService(sessions).record(
        "connector_error",
        "probe",
        {"nested": {"SESSDATA": "secret-cookie"}, "code": -412},
    )

    response = client.get("/logs")

    assert "secret-cookie" not in response.text
    assert "[REDACTED]" in response.text


def test_empty_allowlist_cannot_enable_limited_auto():
    client, _ = make_client()

    response = client.post(
        "/api/system/settings",
        json={
            "run_mode": "limited_auto",
            "auto_reply_allowlist": [],
            "poll_seconds": 60,
        },
    )

    assert response.status_code == 422


def test_settings_show_presence_not_credential_value(monkeypatch):
    monkeypatch.setenv("BILI_SESSDATA", "secret-cookie")
    monkeypatch.setenv("BILI_JCT", "secret-csrf")
    client, _ = make_client()

    response = client.get("/settings")

    assert "已配置" in response.text
    assert "secret-cookie" not in response.text
    assert "secret-csrf" not in response.text


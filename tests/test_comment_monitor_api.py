import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from cyber_catgirl.config import RunMode, Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import AuditLogRecord, SystemSettingRecord


class StubRuntime:
    def __init__(self):
        self.settings = Settings()
        self.accept_sync = True

    async def run_cycle(self):
        return None

    async def discover_contents(self):
        return None

    def request_manual_cycle(self):
        return self.accept_sync


class StubScheduler:
    def start(self):
        pass

    def shutdown(self, wait=True):
        pass


def make_client(settings: Settings | None = None):
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    runtime = StubRuntime()
    app = create_app(
        settings or Settings(),
        session_factory=sessions,
        monitor_runtime=runtime,
        scheduler_factory=lambda _: StubScheduler(),
    )
    return TestClient(app), sessions, runtime


def setting(sessions, key: str):
    with sessions() as session:
        row = session.scalar(
            select(SystemSettingRecord).where(SystemSettingRecord.setting_key == key)
        )
        return row.setting_value if row else None


def audit_actions(sessions):
    with sessions() as session:
        return list(
            session.scalars(
                select(AuditLogRecord.action).order_by(AuditLogRecord.id)
            ).all()
        )


def test_start_monitor_persists_enabled_and_audits():
    client, sessions, _ = make_client()

    response = client.post("/api/comment-monitor/start")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert setting(sessions, "comment_monitor_enabled") == "true"
    assert audit_actions(sessions)[-1] == "comment_monitor_started"


def test_auto_reply_settings_default_to_disabled():
    client, _, _ = make_client()

    payload = client.get("/api/auto-reply/settings").json()

    assert payload["enabled"] is False
    assert payload["account_hourly_limit"] == 60
    assert payload["write_enabled"] is False


def test_sync_is_queued_and_duplicate_request_is_rejected():
    client, _, runtime = make_client()

    accepted = client.post("/api/comment-monitor/sync")
    runtime.accept_sync = False
    duplicate = client.post("/api/comment-monitor/sync")

    assert accepted.status_code == 202
    assert duplicate.status_code == 409


def test_enabling_auto_reply_requires_limited_mode_and_write_authorization():
    client, sessions, _ = make_client(
        Settings(run_mode=RunMode.LIMITED_AUTO, bilibili_write_enabled=False)
    )
    payload = {
        "enabled": True,
        "user_daily_limit": 10,
        "account_hourly_limit": 60,
        "account_daily_limit": 300,
        "min_delay_seconds": 8,
        "max_delay_seconds": 20,
    }

    response = client.patch("/api/auto-reply/settings", json=payload)

    assert response.status_code == 409
    assert setting(sessions, "comment_auto_reply_enabled") is None


def test_disabled_auto_reply_settings_are_persisted_and_audited():
    client, sessions, _ = make_client()
    payload = {
        "enabled": False,
        "user_daily_limit": 8,
        "account_hourly_limit": 40,
        "account_daily_limit": 200,
        "min_delay_seconds": 10,
        "max_delay_seconds": 30,
    }

    response = client.patch("/api/auto-reply/settings", json=payload)

    assert response.status_code == 200
    assert setting(sessions, "auto_reply_user_daily_limit") == "8"
    assert audit_actions(sessions)[-1] == "auto_reply_settings_changed"
    with sessions() as session:
        audit = session.scalar(
            select(AuditLogRecord).order_by(AuditLogRecord.id.desc())
        )
    assert json.loads(audit.details_json)["enabled"] is False

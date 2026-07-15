from fastapi.testclient import TestClient
from sqlalchemy import select

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import DraftRecord, PublishJobRecord, SystemSettingRecord


class RecordingScheduler:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def shutdown(self, wait: bool = True):
        self.stopped = True


class StubMonitorRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def run_cycle(self):
        return None

    async def discover_contents(self):
        return None


def make_client():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    app = create_app(Settings(), session_factory=session_factory)
    return TestClient(app), session_factory


def test_kill_switch_cancels_pending_writes():
    client, session_factory = make_client()
    with session_factory() as session:
        session.add(PublishJobRecord(idempotency_key="reply:c1", status="pending"))
        session.commit()

    response = client.post("/api/system/kill-switch", json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["kill_switch"] is True
    with session_factory() as session:
        job = session.scalar(select(PublishJobRecord))
        assert job.status == "cancelled"


def test_approve_draft_creates_one_publish_job():
    client, session_factory = make_client()
    with session_factory() as session:
        draft = DraftRecord(
            content_key="schedule:morning:1",
            draft_type="dynamic",
            content="早上好喵～",
            risk_level="low",
            review_status="pending",
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

    first = client.post(f"/api/drafts/{draft_id}/approve")
    second = client.post(f"/api/drafts/{draft_id}/approve")

    assert first.status_code == 200
    assert second.status_code == 409
    with session_factory() as session:
        assert len(session.scalars(select(PublishJobRecord)).all()) == 1


def test_health_defaults_to_manual_mode():
    client, _ = make_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["run_mode"] == "manual_only"


def test_app_lifespan_starts_and_stops_scheduler():
    scheduler = RecordingScheduler()
    runtime = StubMonitorRuntime(Settings())
    app = create_app(
        Settings(),
        monitor_runtime=runtime,
        scheduler_factory=lambda _: scheduler,
    )

    with TestClient(app):
        assert scheduler.started is True
    assert scheduler.stopped is True


def test_persisted_monitor_setting_is_loaded_on_restart():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions.begin() as session:
        session.add(
            SystemSettingRecord(
                setting_key="comment_monitor_enabled", setting_value="true"
            )
        )
    runtime = StubMonitorRuntime(Settings(comment_monitor_enabled=False))

    app = create_app(
        Settings(comment_monitor_enabled=False),
        session_factory=sessions,
        monitor_runtime=runtime,
        scheduler_factory=lambda _: RecordingScheduler(),
    )

    assert app.state.runtime.settings.comment_monitor_enabled is True
    assert app.state.monitor_runtime.settings.comment_monitor_enabled is True

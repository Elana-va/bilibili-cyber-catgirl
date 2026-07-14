from fastapi.testclient import TestClient
from sqlalchemy import select

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import DraftRecord, PublishJobRecord


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

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import PublishJobRecord, ScheduledContentRecord


def make_client():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    return TestClient(create_app(Settings(), session_factory=sessions)), sessions


def test_create_plan_stores_schedule_without_publish_job():
    client, sessions = make_client()

    response = client.post(
        "/api/content-plans",
        json={
            "schedule_key": "evening-hello",
            "prompt": "写一条晚间问候",
            "category": "normal",
            "run_at": "2026-07-16T20:00:00+08:00",
        },
    )

    assert response.status_code == 201
    with sessions() as session:
        assert len(session.scalars(select(ScheduledContentRecord)).all()) == 1
        assert len(session.scalars(select(PublishJobRecord)).all()) == 0


def test_disable_plan_keeps_record_but_marks_inactive():
    client, sessions = make_client()
    with sessions() as session:
        plan = ScheduledContentRecord(
            schedule_key="morning",
            prompt="早安",
            category="normal",
            run_at=datetime.now(timezone.utc),
        )
        session.add(plan)
        session.commit()
        plan_id = plan.id

    response = client.post(
        f"/api/content-plans/{plan_id}/enabled",
        json={"enabled": False},
    )

    assert response.status_code == 200
    with sessions() as session:
        assert session.get(ScheduledContentRecord, plan_id).enabled is False


def test_content_page_explains_plans_do_not_publish_directly():
    client, _ = make_client()

    response = client.get("/content")

    assert "只安排草稿生成，不会直接发布" in response.text


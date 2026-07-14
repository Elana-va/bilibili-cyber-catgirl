from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import DraftRecord, PublishJobRecord


def make_client():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    return TestClient(create_app(Settings(), session_factory=sessions)), sessions


def seed_draft(sessions, *, content: str, draft_type: str, risk: str) -> int:
    with sessions() as session:
        row = DraftRecord(
            draft_type=draft_type,
            content=content,
            risk_level=risk,
            review_status="pending",
        )
        session.add(row)
        session.commit()
        return row.id


def test_reviews_filter_by_risk_and_type():
    client, sessions = make_client()
    seed_draft(sessions, content="低风险回复", draft_type="reply", risk="low")
    seed_draft(sessions, content="中风险日报", draft_type="daily_report", risk="medium")

    response = client.get("/reviews?draft_type=reply&risk_level=low")

    assert "低风险回复" in response.text
    assert "中风险日报" not in response.text


def test_visibility_unknown_never_offers_retry():
    client, sessions = make_client()
    draft_id = seed_draft(sessions, content="待人工核验", draft_type="reply", risk="low")
    with sessions() as session:
        session.add(
            PublishJobRecord(
                draft_id=draft_id,
                idempotency_key="reply:unknown",
                status="visibility_unknown",
            )
        )
        session.commit()

    response = client.get("/reviews")

    assert "平台可能已写入" in response.text
    assert 'data-action="retry"' not in response.text


def test_kill_switch_blocks_edit_and_approve():
    client, sessions = make_client()
    draft_id = seed_draft(sessions, content="原始内容", draft_type="reply", risk="low")
    client.post("/api/system/kill-switch", json={"enabled": True})

    response = client.post(
        f"/api/drafts/{draft_id}/edit-and-approve",
        json={"content": "编辑后的内容"},
    )

    assert response.status_code == 409


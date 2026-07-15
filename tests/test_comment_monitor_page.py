from datetime import datetime, timezone

from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import DraftRecord, EventRecord, MonitoredContentRecord
from cyber_catgirl.schemas import InteractionEvent


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def make_client():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    return TestClient(create_app(Settings(), session_factory=sessions)), sessions


def test_monitor_page_shows_status_metrics_and_controls():
    client, _ = make_client()

    response = client.get("/comment-monitor")

    assert response.status_code == 200
    assert "data-monitor-state" in response.text
    assert 'data-action="sync-comments"' in response.text
    assert "历史回溯" in response.text
    assert "/static/comment-monitor.js" in response.text


def test_review_card_shows_source_comment_and_priority():
    client, sessions = make_client()
    event = InteractionEvent(
        event_id="comment_102",
        event_type="new_comment",
        actor_id="u1",
        actor_name="测试用户",
        content="这是怎么接入的？",
        target_type="video",
        target_id="42",
        root_comment_id="102",
        platform_created_at=NOW,
    )
    with sessions.begin() as session:
        source = MonitoredContentRecord(
            platform_content_id="video:42",
            display_type="video",
            comment_oid="42",
            resource_type="video",
            title="测试视频",
            published_at=NOW,
        )
        session.add(source)
        session.flush()
        event_row = EventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            payload_json=event.model_dump_json(),
            monitored_content_id=source.id,
            priority="urgent",
            status="drafted",
        )
        session.add(event_row)
        session.flush()
        session.add(
            DraftRecord(
                event_id=event_row.id,
                draft_type="reply",
                content="通过受控接口接入喵。",
                risk_level="low",
                review_status="pending",
                safety_reasons_json='["manual_only"]',
            )
        )

    response = client.get("/reviews")

    assert "这是怎么接入的？" in response.text
    assert "测试用户" in response.text
    assert "测试视频" in response.text
    assert "优先" in response.text
    assert "B站真实写入未授权" in response.text


from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import EventRecord, PublishJobRecord
from cyber_catgirl.schemas import AgentDecision, InteractionEvent, PlatformContentTarget


def test_unknown_agent_action_is_rejected():
    with pytest.raises(ValidationError):
        AgentDecision(
            action="delete_account",
            content="x",
            risk_level="low",
            reason="unsupported action",
        )


def test_event_requires_stable_platform_id():
    event = InteractionEvent(
        event_id="comment_123",
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="dynamic",
        target_id="d1",
        platform_created_at=datetime.fromisoformat("2026-07-14T10:00:00+08:00"),
    )

    assert event.event_id == "comment_123"


def test_nested_event_keeps_root_and_parent_ids():
    event = InteractionEvent(
        event_id="comment_102",
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="楼中楼",
        target_type="video",
        target_id="42",
        root_comment_id="100",
        parent_comment_id="101",
        platform_created_at=datetime.fromisoformat("2026-07-14T10:00:00+08:00"),
    )

    assert event.root_comment_id == "100"
    assert event.parent_comment_id == "101"


def test_platform_content_target_separates_display_and_comment_resource_types():
    target = PlatformContentTarget(
        platform_content_id="dynamic_1",
        display_type="dynamic_draw",
        comment_oid="42",
        resource_type="article",
        title="图文动态",
        published_at=datetime.fromisoformat("2026-07-14T10:00:00+08:00"),
    )

    assert target.display_type == "dynamic_draw"
    assert target.resource_type == "article"


def test_event_id_is_unique_in_database():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    with session_factory() as session:
        session.add(EventRecord(event_id="comment_1", event_type="new_comment"))
        session.commit()
        session.add(EventRecord(event_id="comment_1", event_type="new_comment"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_publish_job_idempotency_key_is_unique():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    with session_factory() as session:
        session.add(PublishJobRecord(idempotency_key="reply:comment_1", status="pending"))
        session.commit()
        session.add(PublishJobRecord(idempotency_key="reply:comment_1", status="pending"))
        with pytest.raises(IntegrityError):
            session.commit()

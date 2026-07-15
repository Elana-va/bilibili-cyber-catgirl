from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cyber_catgirl.agent.service import AgentGenerationError
from cyber_catgirl.config import RunMode
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import AgentDecision, InteractionEvent
from cyber_catgirl.services.memory import MemoryService
from cyber_catgirl.services.replies import ReplyGenerationError, ReplyService
from cyber_catgirl.services.safety import SafetyEngine


class StaticAgent:
    async def decide(self, event, context):
        return AgentDecision(
            action="reply",
            content="你好呀，今天也要开心喵～",
            risk_level="low",
            reason="普通问候",
            requires_human_review=False,
        )


class IgnoreAgent:
    async def decide(self, event, context):
        return AgentDecision(
            action="ignore",
            content="",
            risk_level="low",
            reason="无需回复",
            requires_human_review=False,
        )


class FailingAgent:
    async def decide(self, event, context):
        raise AgentGenerationError("deepseek_timeout")


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def seed_event(session_factory, event_id="comment_1"):
    event = InteractionEvent(
        event_id=event_id,
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="dynamic",
        target_id="d1",
        platform_created_at=NOW,
    )
    with session_factory() as session:
        session.add(
            EventRecord(
                event_id=event.event_id,
                event_type=event.event_type,
                payload_json=event.model_dump_json(),
            )
        )
        session.commit()
    return event


async def test_low_risk_reply_creates_one_publish_job():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    seed_event(session_factory)

    service = ReplyService(
        session_factory,
        StaticAgent(),
        MemoryService(session_factory),
        SafetyEngine(
            run_mode=RunMode.LIMITED_AUTO,
            comment_auto_reply_enabled=True,
            write_enabled=True,
        ),
        now_provider=lambda: NOW,
        delay_selector=lambda low, high: 12,
    )

    await service.process_event("comment_1")
    await service.process_event("comment_1")

    with session_factory() as session:
        drafts = session.scalars(select(DraftRecord)).all()
        jobs = session.scalars(select(PublishJobRecord)).all()
    assert len(drafts) == 1
    assert len(jobs) == 1
    assert jobs[0].idempotency_key == "reply:comment_1"
    assert jobs[0].source == "auto"
    assert jobs[0].next_attempt_at == (NOW + timedelta(seconds=12)).replace(tzinfo=None)


async def test_ignore_marks_event_without_creating_draft():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    seed_event(sessions)
    service = ReplyService(
        sessions,
        IgnoreAgent(),
        MemoryService(sessions),
        SafetyEngine(run_mode=RunMode.MANUAL_ONLY),
    )

    assert await service.process_event("comment_1") is None

    with sessions() as session:
        event = session.scalar(select(EventRecord))
        drafts = session.scalars(select(DraftRecord)).all()
    assert event.status == "ignored"
    assert drafts == []


async def test_model_failure_is_retryable_without_empty_draft():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    seed_event(sessions)
    service = ReplyService(
        sessions,
        FailingAgent(),
        MemoryService(sessions),
        SafetyEngine(run_mode=RunMode.MANUAL_ONLY),
        now_provider=lambda: NOW,
    )

    with pytest.raises(ReplyGenerationError) as exc_info:
        await service.process_event("comment_1")

    with sessions() as session:
        event = session.scalar(select(EventRecord))
        drafts = session.scalars(select(DraftRecord)).all()
    assert exc_info.value.code == "deepseek_timeout"
    assert event.status == "generation_failed"
    assert event.processing_attempts == 1
    assert event.next_attempt_at == (NOW + timedelta(minutes=1)).replace(tzinfo=None)
    assert drafts == []

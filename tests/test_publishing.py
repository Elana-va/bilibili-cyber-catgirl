from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from cyber_catgirl.connectors.bilibili_api import PlatformRateLimited
from cyber_catgirl.connectors.fake import FakeBilibiliConnector
from cyber_catgirl.config import RunMode, Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import InteractionEvent
from cyber_catgirl.services.publishing import AutoPublishGuard, Publisher


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def seed_reply_job(
    session_factory,
    *,
    root: str | None = "100",
    parent: str | None = "101",
    source: str = "manual",
    event_id: str = "comment_102",
) -> int:
    event = InteractionEvent(
        event_id=event_id,
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="video",
        target_id="42",
        root_comment_id=root,
        parent_comment_id=parent,
        platform_created_at=NOW,
    )
    with session_factory() as session:
        event_row = EventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            payload_json=event.model_dump_json(),
        )
        session.add(event_row)
        session.flush()
        draft = DraftRecord(
            event_id=event_row.id,
            draft_type="reply",
            content="回复喵",
            risk_level="low",
            review_status="auto_approved",
        )
        session.add(draft)
        session.flush()
        job = PublishJobRecord(
            draft_id=draft.id,
            idempotency_key=f"reply:{event_id}",
            status="pending",
            source=source,
        )
        session.add(job)
        session.commit()
        return job.id


class RateLimitedConnector(FakeBilibiliConnector):
    async def reply_to_comment(self, comment_oid: str, *args) -> str:
        raise PlatformRateLimited("limited")


async def test_invisible_success_is_not_retried():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    connector = FakeBilibiliConnector(visible=False, reply_id="r1")
    event = InteractionEvent(
        event_id="comment_1",
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="dynamic",
        target_id="d1",
        platform_created_at=datetime.now(timezone.utc),
    )
    with session_factory() as session:
        event_row = EventRecord(
            event_id=event.event_id,
            event_type=event.event_type,
            payload_json=event.model_dump_json(),
        )
        session.add(event_row)
        session.flush()
        draft = DraftRecord(
            event_id=event_row.id,
            draft_type="reply",
            content="你好呀，今天也要开心喵～",
            risk_level="low",
            review_status="auto_approved",
        )
        session.add(draft)
        session.flush()
        job = PublishJobRecord(
            draft_id=draft.id,
            idempotency_key="reply:comment_1",
            status="pending",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    publisher = Publisher(session_factory, connector)
    first = await publisher.execute(job_id)
    second = await publisher.execute(job_id)

    assert first.status == "visibility_unknown"
    assert second.status == "visibility_unknown"
    assert len(connector.write_calls) == 1


async def test_publisher_replies_to_direct_parent_with_root_context():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    job_id = seed_reply_job(sessions)
    connector = FakeBilibiliConnector(visible=True, reply_id="comment:500")

    result = await Publisher(sessions, connector).execute(job_id, now=NOW)

    assert result.status == "succeeded"
    assert connector.write_calls[0] == {
        "action": "reply",
        "target_id": "42",
        "resource_type": "video",
        "comment_id": "100",
        "parent_comment_id": "101",
        "text": "回复喵",
    }


async def test_rate_limit_moves_job_to_retry_wait():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    job_id = seed_reply_job(sessions)

    result = await Publisher(sessions, RateLimitedConnector()).execute(job_id, now=NOW)

    with sessions() as session:
        job = session.scalar(select(PublishJobRecord))
    assert result.status == "retry_wait"
    assert job.last_error_code == "bilibili_rate_limited"
    assert job.next_attempt_at == (NOW + timedelta(minutes=5)).replace(tzinfo=None)


async def test_retry_wait_job_is_not_sent_before_due_time():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    job_id = seed_reply_job(sessions)
    connector = FakeBilibiliConnector()
    with sessions() as session:
        job = session.get(PublishJobRecord, job_id)
        job.status = "retry_wait"
        job.next_attempt_at = NOW + timedelta(minutes=5)
        session.commit()

    result = await Publisher(sessions, connector).execute(job_id, now=NOW)

    assert result.status == "retry_wait"
    assert connector.write_calls == []


async def test_queued_auto_job_is_cancelled_when_auto_reply_is_disabled():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    job_id = seed_reply_job(sessions, source="auto")
    connector = FakeBilibiliConnector()
    settings = Settings(
        run_mode=RunMode.LIMITED_AUTO,
        comment_auto_reply_enabled=False,
        bilibili_write_enabled=True,
    )

    result = await Publisher(
        sessions,
        connector,
        auto_guard=AutoPublishGuard(sessions, settings),
    ).execute(job_id, now=NOW)

    assert result.status == "cancelled"
    assert connector.write_calls == []


async def test_auto_job_waits_when_minimum_interval_is_not_elapsed():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    prior_id = seed_reply_job(sessions, source="auto", event_id="comment_102")
    due_id = seed_reply_job(sessions, source="auto", event_id="comment_103")
    with sessions.begin() as session:
        prior = session.get(PublishJobRecord, prior_id)
        prior.status = "succeeded"
        prior.completed_at = NOW - timedelta(seconds=2)
    connector = FakeBilibiliConnector()
    settings = Settings(
        run_mode=RunMode.LIMITED_AUTO,
        comment_auto_reply_enabled=True,
        bilibili_write_enabled=True,
        auto_reply_min_delay_seconds=8,
    )

    result = await Publisher(
        sessions,
        connector,
        auto_guard=AutoPublishGuard(sessions, settings),
    ).execute(due_id, now=NOW)

    with sessions() as session:
        due = session.get(PublishJobRecord, due_id)
    assert result.status == "retry_wait"
    assert due.last_error_code == "auto_rate_limited"
    assert due.next_attempt_at == (NOW + timedelta(seconds=6)).replace(tzinfo=None)
    assert connector.write_calls == []


async def test_manual_job_obeys_account_send_interval():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    prior_id = seed_reply_job(sessions, event_id="comment_202")
    due_id = seed_reply_job(sessions, event_id="comment_203")
    with sessions.begin() as session:
        prior = session.get(PublishJobRecord, prior_id)
        prior.status = "visibility_unknown"
        prior.platform_id = "comment:500"
        prior.completed_at = NOW - timedelta(seconds=2)
    connector = FakeBilibiliConnector()
    settings = Settings(
        bilibili_write_enabled=True,
        auto_reply_min_delay_seconds=8,
    )

    result = await Publisher(
        sessions,
        connector,
        auto_guard=AutoPublishGuard(sessions, settings),
    ).execute(due_id, now=NOW)

    assert result.status == "retry_wait"
    assert connector.write_calls == []

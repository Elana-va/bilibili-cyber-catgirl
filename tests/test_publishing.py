from datetime import datetime, timezone

from cyber_catgirl.connectors.fake import FakeBilibiliConnector
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import InteractionEvent
from cyber_catgirl.services.publishing import Publisher


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

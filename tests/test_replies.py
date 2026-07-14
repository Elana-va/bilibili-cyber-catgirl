from datetime import datetime, timezone

from sqlalchemy import select

from cyber_catgirl.config import RunMode
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import AgentDecision, InteractionEvent
from cyber_catgirl.services.memory import MemoryService
from cyber_catgirl.services.replies import ReplyService
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


async def test_low_risk_reply_creates_one_publish_job():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
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
        session.add(
            EventRecord(
                event_id=event.event_id,
                event_type=event.event_type,
                payload_json=event.model_dump_json(),
            )
        )
        session.commit()

    service = ReplyService(
        session_factory,
        StaticAgent(),
        MemoryService(session_factory),
        SafetyEngine(run_mode=RunMode.LIMITED_AUTO, allowed_actor_ids={"u1"}),
    )

    await service.process_event("comment_1")
    await service.process_event("comment_1")

    with session_factory() as session:
        drafts = session.scalars(select(DraftRecord)).all()
        jobs = session.scalars(select(PublishJobRecord)).all()
    assert len(drafts) == 1
    assert len(jobs) == 1
    assert jobs[0].idempotency_key == "reply:comment_1"

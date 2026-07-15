import json
from pathlib import Path

import pytest
from sqlalchemy import select

from cyber_catgirl.config import RunMode
from cyber_catgirl.connectors.fake import FakeBilibiliConnector
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord
from cyber_catgirl.schemas import AgentDecision, InteractionEvent
from cyber_catgirl.services.replay import replay_events


class FriendlyAgent:
    async def decide(self, event, context):
        return AgentDecision(
            action="reply",
            content="正在认真研究新世界喵～",
            risk_level="low",
            reason="普通互动",
            requires_human_review=False,
            scene="casual",
            address="partner",
            emoticon="",
        )


def load_events() -> list[InteractionEvent]:
    path = Path(__file__).parent / "fixtures" / "comments.json"
    return [InteractionEvent.model_validate(item) for item in json.loads(path.read_text("utf-8"))]


async def test_replay_is_idempotent_and_risky_input_never_auto_publishes():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    connector = FakeBilibiliConnector(events=load_events())

    first = await replay_events(
        session_factory,
        connector,
        FriendlyAgent(),
        run_mode=RunMode.LIMITED_AUTO,
        allowed_actor_ids={"u100"},
        comment_auto_reply_enabled=True,
        write_enabled=True,
    )
    second = await replay_events(
        session_factory,
        connector,
        FriendlyAgent(),
        run_mode=RunMode.LIMITED_AUTO,
        allowed_actor_ids={"u100"},
        comment_auto_reply_enabled=True,
        write_enabled=True,
    )

    with session_factory() as session:
        drafts = session.scalars(select(DraftRecord).order_by(DraftRecord.id)).all()

    assert first.events_inserted == 2
    assert first.drafts_created == 2
    assert first.publications_succeeded == 1
    assert second.events_inserted == 0
    assert second.duplicates == 2
    assert len(drafts) == 2
    assert [draft.review_status for draft in drafts] == ["auto_approved", "pending"]
    assert len(connector.write_calls) == 1


async def test_kill_switch_prevents_all_external_writes():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    connector = FakeBilibiliConnector(events=[load_events()[0]])

    result = await replay_events(
        session_factory,
        connector,
        FriendlyAgent(),
        run_mode=RunMode.LIMITED_AUTO,
        allowed_actor_ids={"u100"},
        kill_switch=True,
        comment_auto_reply_enabled=True,
        write_enabled=True,
    )

    assert result.publications_succeeded == 0
    assert connector.write_calls == []


async def test_database_failure_never_reaches_external_write():
    connector = FakeBilibiliConnector(events=[load_events()[0]])

    def unavailable_database():
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await replay_events(
            unavailable_database,
            connector,
            FriendlyAgent(),
            run_mode=RunMode.LIMITED_AUTO,
            allowed_actor_ids={"u100"},
        )

    assert connector.write_calls == []

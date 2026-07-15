from datetime import datetime, timezone

from sqlalchemy import func, select

from cyber_catgirl.agent.service import CatgirlAgent
from cyber_catgirl.config import RunMode, Settings
from cyber_catgirl.connectors.fake import FakeBilibiliConnector
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import (
    AgentDecision,
    InteractionEvent,
    PlatformContentTarget,
)
from cyber_catgirl.services.comment_monitor import CommentMonitorService
from cyber_catgirl.services.content_discovery import ContentDiscoveryService
from cyber_catgirl.services.memory import MemoryService
from cyber_catgirl.services.monitor_runtime import MonitorRuntime
from cyber_catgirl.services.publishing import Publisher
from cyber_catgirl.services.replies import ReplyService
from cyber_catgirl.services.safety import SafetyEngine


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


class FriendlyLlm:
    async def generate_json(self, messages, schema):
        return AgentDecision(
            action="reply",
            content="通过受控评论接口接入喵。",
            risk_level="low",
            reason="普通问答",
            requires_human_review=False,
        ).model_dump(mode="json")


def fixture_connector() -> FakeBilibiliConnector:
    target = PlatformContentTarget(
        platform_content_id="video:42",
        display_type="video",
        comment_oid="42",
        resource_type="video",
        title="接入说明",
        published_at=NOW,
    )
    events = [
        InteractionEvent(
            event_id=f"comment_{index}",
            event_type="new_comment",
            actor_id=f"u{index}",
            actor_name=f"用户{index}",
            content="这是怎么接入的？" if index == 1 else "你好呀",
            target_type="video",
            target_id="42",
            platform_created_at=NOW,
        )
        for index in (1, 2)
    ]
    return FakeBilibiliConnector(targets=[target], events=events)


def build_runtime(database_url: str, connector: FakeBilibiliConnector):
    sessions = create_session_factory(database_url)
    settings = Settings(
        run_mode=RunMode.MANUAL_ONLY,
        comment_monitor_enabled=True,
        comment_auto_reply_enabled=False,
        bilibili_write_enabled=False,
    )
    replies = ReplyService(
        sessions,
        CatgirlAgent(FriendlyLlm()),
        MemoryService(sessions),
        SafetyEngine(
            run_mode=settings.run_mode,
            comment_auto_reply_enabled=settings.comment_auto_reply_enabled,
            write_enabled=settings.bilibili_write_enabled,
        ),
        now_provider=lambda: NOW,
    )
    runtime = MonitorRuntime(
        sessions,
        settings,
        CommentMonitorService(
            sessions,
            connector,
            account_id="owner",
            account_name="赛博猫娘",
            backfill_limit=500,
        ),
        replies,
        Publisher(sessions, connector),
        content_discovery=ContentDiscoveryService(
            sessions,
            connector,
            account_id="owner",
            backfill_days=30,
        ),
    )
    return runtime, sessions


async def test_discover_monitor_generate_review_without_real_write(tmp_path):
    connector = fixture_connector()
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'monitor.db').as_posix()}"
    runtime, sessions = build_runtime(database_url, connector)

    await runtime.discover_contents(now=NOW)
    result = await runtime.run_cycle(now=NOW)

    assert result.events_inserted == 2
    assert result.generation_started == 2
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DraftRecord)) == 2
        assert session.scalar(select(func.count()).select_from(PublishJobRecord)) == 0
    assert connector.write_calls == []


async def test_restart_resumes_without_duplicate_event_or_draft(tmp_path):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'restart.db').as_posix()}"
    first_connector = fixture_connector()
    first, _ = build_runtime(database_url, first_connector)
    await first.discover_contents(now=NOW)
    await first.run_cycle(now=NOW)

    second_connector = fixture_connector()
    second, sessions = build_runtime(database_url, second_connector)
    await second.discover_contents(now=NOW)
    result = await second.run_cycle(now=NOW)

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(EventRecord)) == 2
        assert session.scalar(select(func.count()).select_from(DraftRecord)) == 2
        assert session.scalar(select(func.count()).select_from(PublishJobRecord)) == 0
    assert result.generation_started == 0
    assert second_connector.write_calls == []

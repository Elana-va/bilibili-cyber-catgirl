import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from cyber_catgirl.connectors.base import CommentPage
from cyber_catgirl.connectors.bilibili_api import PlatformRateLimited
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import (
    EventRecord,
    MonitoredContentRecord,
    MonitorCheckpointRecord,
    SystemSettingRecord,
)
from cyber_catgirl.schemas import InteractionEvent
from cyber_catgirl.services.comment_monitor import CommentMonitorService


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


def interaction(
    comment_id: str,
    *,
    actor_id: str = "u1",
    content: str = "普通评论",
    root: str | None = None,
    parent: str | None = None,
    seconds: int = 0,
) -> InteractionEvent:
    return InteractionEvent(
        event_id=f"comment_{comment_id}",
        event_type="new_comment",
        actor_id=actor_id,
        actor_name="用户",
        content=content,
        target_type="video",
        target_id="42",
        root_comment_id=root or comment_id,
        parent_comment_id=parent,
        platform_created_at=NOW - timedelta(seconds=seconds),
    )


class MonitorConnector:
    def __init__(self):
        self.error = None
        self.calls = []
        self.top_page = CommentPage(
            events=[
                interaction("201", content="这是怎么接入的？"),
                interaction("self", actor_id="1801157579"),
            ],
            next_cursor=None,
            root_ids_with_replies=("201",),
        )
        self.sub_pages = {
            "201": CommentPage(
                events=[interaction("202", root="201", parent="201")],
                next_cursor=None,
            )
        }

    async def fetch_comment_page(self, target, cursor):
        self.calls.append(("top", target.platform_content_id, cursor))
        if self.error:
            raise self.error
        return self.top_page

    async def fetch_subcomment_page(self, target, root_comment_id, cursor):
        self.calls.append(("nested", root_comment_id, cursor))
        return self.sub_pages[root_comment_id]


def make_sessions():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions() as session:
        session.add(
            MonitoredContentRecord(
                platform_content_id="video:42",
                display_type="video",
                comment_oid="42",
                resource_type="video",
                title="测试视频",
                published_at=NOW - timedelta(days=1),
            )
        )
        session.commit()
    return sessions


def load_event(sessions, event_id: str) -> EventRecord:
    with sessions() as session:
        return session.scalar(select(EventRecord).where(EventRecord.event_id == event_id))


def setting(sessions, key: str) -> str | None:
    with sessions() as session:
        row = session.scalar(
            select(SystemSettingRecord).where(SystemSettingRecord.setting_key == key)
        )
        return row.setting_value if row else None


def seed_setting(sessions, key: str, value: str) -> None:
    with sessions() as session:
        session.add(SystemSettingRecord(setting_key=key, setting_value=value))
        session.commit()


async def test_poll_stores_top_level_and_nested_events_without_self_replies():
    sessions = make_sessions()
    connector = MonitorConnector()
    service = CommentMonitorService(
        sessions,
        connector,
        account_id="1801157579",
        account_name="听晴sil",
        backfill_limit=500,
    )

    result = await service.poll_once(NOW, page_budget=3)

    assert result.inserted == 2
    assert result.self_filtered == 1
    assert result.pages_read == 2
    assert load_event(sessions, "comment_201").priority == "priority"
    nested = InteractionEvent.model_validate_json(
        load_event(sessions, "comment_202").payload_json
    )
    assert (nested.root_comment_id, nested.parent_comment_id) == ("201", "201")


async def test_polling_same_comments_twice_does_not_duplicate_events():
    sessions = make_sessions()
    connector = MonitorConnector()
    service = CommentMonitorService(
        sessions,
        connector,
        account_id="1801157579",
        account_name="听晴sil",
        backfill_limit=500,
    )

    await service.poll_once(NOW, page_budget=3)
    second = await service.poll_once(NOW + timedelta(minutes=1), page_budget=3)

    with sessions() as session:
        count = session.scalar(select(func.count()).select_from(EventRecord))
    assert count == 2
    assert second.duplicates == 2


async def test_backfill_never_imports_more_than_configured_limit():
    sessions = make_sessions()
    seed_setting(sessions, "comment_backfill_imported", "499")
    connector = MonitorConnector()
    connector.top_page = CommentPage(
        events=[interaction("301"), interaction("302", seconds=1)],
        next_cursor="2",
    )
    connector.sub_pages = {}
    service = CommentMonitorService(
        sessions,
        connector,
        account_id="1801157579",
        account_name="听晴sil",
        backfill_limit=500,
    )

    result = await service.poll_once(NOW, page_budget=3)

    assert result.inserted == 1
    assert result.backfill_limit_reached is True
    assert setting(sessions, "comment_backfill_imported") == "500"
    assert setting(sessions, "comment_backfill_complete") == "true"
    assert setting(sessions, "comment_backfill_watermark") == NOW.isoformat()


async def test_platform_rate_limit_defers_target_without_losing_cursor():
    sessions = make_sessions()
    with sessions() as session:
        session.add(
            MonitorCheckpointRecord(
                checkpoint_key="comments:video:42",
                cursor_value="original-cursor",
            )
        )
        session.commit()
    connector = MonitorConnector()
    connector.error = PlatformRateLimited("limited")
    service = CommentMonitorService(
        sessions,
        connector,
        account_id="1801157579",
        account_name="听晴sil",
        backfill_limit=500,
    )

    result = await service.poll_once(NOW, page_budget=3)

    with sessions() as session:
        target = session.scalar(select(MonitoredContentRecord))
        checkpoint = session.scalar(select(MonitorCheckpointRecord))
    assert result.error_code == "bilibili_rate_limited"
    assert target.failure_count == 1
    assert target.next_poll_at == (NOW + timedelta(minutes=5)).replace(tzinfo=None)
    assert checkpoint.cursor_value == "original-cursor"
    assert json.loads(checkpoint.state_json) == {}

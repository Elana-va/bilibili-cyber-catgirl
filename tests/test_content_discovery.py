from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import MonitoredContentRecord, MonitorCheckpointRecord
from cyber_catgirl.schemas import PlatformContentTarget
from cyber_catgirl.services.content_discovery import ContentDiscoveryService


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


class FakeDiscoveryPort:
    def __init__(self, targets, next_cursor="dynamic:next"):
        self.targets = list(targets)
        self.next_cursor = next_cursor
        self.seen_cursor = None

    async def discover_contents(self, account_id, cursor):
        assert account_id == "1801157579"
        self.seen_cursor = cursor
        return list(self.targets), self.next_cursor


def target(content_id: str, *, days_old: int, title: str) -> PlatformContentTarget:
    is_video = content_id.startswith("video:")
    return PlatformContentTarget(
        platform_content_id=content_id,
        display_type="video" if is_video else "dynamic_text",
        comment_oid=content_id.rsplit(":", 1)[1],
        resource_type="video" if is_video else "dynamic",
        title=title,
        published_at=NOW - timedelta(days=days_old),
    )


def load_checkpoint(sessions, key: str) -> str | None:
    with sessions() as session:
        row = session.scalar(
            select(MonitorCheckpointRecord).where(
                MonitorCheckpointRecord.checkpoint_key == key
            )
        )
        return row.cursor_value if row else None


async def test_discovery_keeps_recent_targets_and_updates_existing():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    connector = FakeDiscoveryPort(
        [
            target("video:42", days_old=1, title="视频"),
            target("dynamic:77", days_old=30, title="动态"),
            target("video:99", days_old=31, title="旧视频"),
        ]
    )
    service = ContentDiscoveryService(
        sessions,
        connector,
        account_id="1801157579",
        backfill_days=30,
    )

    first = await service.run_once(NOW)

    assert first.inserted == 2
    assert first.updated == 0
    assert first.skipped_old == 1
    assert load_checkpoint(sessions, "content-discovery") == "dynamic:next"

    connector.targets = [target("video:42", days_old=1, title="新标题")]
    connector.next_cursor = None
    second = await service.run_once(NOW)

    with sessions() as session:
        count = session.scalar(select(func.count()).select_from(MonitoredContentRecord))
        video = session.scalar(
            select(MonitoredContentRecord).where(
                MonitoredContentRecord.platform_content_id == "video:42"
            )
        )
    assert second.updated == 1
    assert count == 2
    assert video.title == "新标题"
    assert load_checkpoint(sessions, "content-discovery") is None


async def test_discovery_resumes_from_saved_cursor():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions() as session:
        session.add(
            MonitorCheckpointRecord(
                checkpoint_key="content-discovery",
                cursor_value="dynamic:resume",
            )
        )
        session.commit()
    connector = FakeDiscoveryPort([], next_cursor=None)
    service = ContentDiscoveryService(
        sessions,
        connector,
        account_id="1801157579",
        backfill_days=30,
    )

    await service.run_once(NOW)

    assert connector.seen_cursor == "dynamic:resume"


async def test_discovery_failure_does_not_advance_checkpoint():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")

    class FailingPort:
        async def discover_contents(self, account_id, cursor):
            raise RuntimeError("temporary")

    service = ContentDiscoveryService(
        sessions,
        FailingPort(),
        account_id="1801157579",
        backfill_days=30,
    )

    with pytest.raises(RuntimeError, match="temporary"):
        await service.run_once(NOW)

    with sessions() as session:
        assert session.scalar(select(MonitorCheckpointRecord)) is None

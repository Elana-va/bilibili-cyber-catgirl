import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from cyber_catgirl.models import MonitoredContentRecord, MonitorCheckpointRecord
from cyber_catgirl.schemas import PlatformContentTarget


@dataclass(frozen=True)
class DiscoveryResult:
    inserted: int
    updated: int
    skipped_old: int
    next_cursor: str | None


class CheckpointStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def get(self, key: str) -> str | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(MonitorCheckpointRecord).where(
                    MonitorCheckpointRecord.checkpoint_key == key
                )
            )
            return row.cursor_value if row else None

    @staticmethod
    def set_in_session(
        session,
        key: str,
        cursor: str | None,
        *,
        state: dict | None = None,
        now: datetime | None = None,
    ) -> None:
        row = session.scalar(
            select(MonitorCheckpointRecord).where(
                MonitorCheckpointRecord.checkpoint_key == key
            )
        )
        state_json = json.dumps(state or {}, ensure_ascii=False, separators=(",", ":"))
        if row is None:
            session.add(
                MonitorCheckpointRecord(
                    checkpoint_key=key,
                    cursor_value=cursor,
                    state_json=state_json,
                    updated_at=now,
                )
            )
            return
        row.cursor_value = cursor
        row.state_json = state_json
        row.updated_at = now


class ContentDiscoveryService:
    CHECKPOINT_KEY = "content-discovery"

    def __init__(
        self,
        session_factory,
        connector,
        *,
        account_id: str,
        backfill_days: int = 30,
    ) -> None:
        self.session_factory = session_factory
        self.connector = connector
        self.account_id = account_id
        self.backfill_days = backfill_days
        self.checkpoints = CheckpointStore(session_factory)

    async def run_once(self, now: datetime) -> DiscoveryResult:
        cursor = self.checkpoints.get(self.CHECKPOINT_KEY)
        targets, next_cursor = await self.connector.discover_contents(
            self.account_id, cursor
        )
        cutoff = now - timedelta(days=self.backfill_days)
        inserted = 0
        updated = 0
        skipped_old = 0

        with self.session_factory.begin() as session:
            expired = session.scalars(
                select(MonitoredContentRecord).where(
                    MonitoredContentRecord.active.is_(True),
                    MonitoredContentRecord.published_at < cutoff,
                )
            ).all()
            for row in expired:
                row.active = False
            for target in targets:
                if target.published_at < cutoff:
                    skipped_old += 1
                    continue
                row = session.scalar(
                    select(MonitoredContentRecord).where(
                        MonitoredContentRecord.platform_content_id
                        == target.platform_content_id
                    )
                )
                if row is None:
                    session.add(self._to_record(target, now))
                    inserted += 1
                else:
                    self._update_record(row, target, now)
                    row.active = True
                    updated += 1
            self.checkpoints.set_in_session(
                session,
                self.CHECKPOINT_KEY,
                next_cursor,
                now=now,
            )

        return DiscoveryResult(inserted, updated, skipped_old, next_cursor)

    @staticmethod
    def _to_record(
        target: PlatformContentTarget, now: datetime
    ) -> MonitoredContentRecord:
        return MonitoredContentRecord(
            platform_content_id=target.platform_content_id,
            display_type=target.display_type,
            comment_oid=target.comment_oid,
            resource_type=target.resource_type,
            title=target.title,
            published_at=target.published_at,
            active=True,
            last_discovered_at=now,
        )

    @staticmethod
    def _update_record(
        row: MonitoredContentRecord,
        target: PlatformContentTarget,
        now: datetime,
    ) -> None:
        row.display_type = target.display_type
        row.comment_oid = target.comment_oid
        row.resource_type = target.resource_type
        row.title = target.title
        row.published_at = target.published_at
        row.active = True
        row.last_discovered_at = now

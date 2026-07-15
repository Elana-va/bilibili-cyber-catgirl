import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from cyber_catgirl.connectors.bilibili_api import (
    CredentialsUnavailable,
    PlatformRateLimited,
    PlatformRiskControl,
    PlatformUnavailable,
)
from cyber_catgirl.models import (
    EventRecord,
    MonitoredContentRecord,
    MonitorCheckpointRecord,
    SystemSettingRecord,
)
from cyber_catgirl.schemas import InteractionEvent, PlatformContentTarget
from cyber_catgirl.services.content_discovery import CheckpointStore
from cyber_catgirl.services.ingestion import store_unique_event
from cyber_catgirl.services.priority import classify_review_priority


BACKOFF_DELAYS = (timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60))


@dataclass
class BackfillState:
    imported: int
    complete: bool
    watermark: datetime | None
    limit_reached: bool = False


@dataclass(frozen=True)
class MonitorPollResult:
    inserted: int = 0
    duplicates: int = 0
    self_filtered: int = 0
    history_filtered: int = 0
    pages_read: int = 0
    error_code: str | None = None
    backfill_limit_reached: bool = False


@dataclass
class MutablePollResult:
    inserted: int = 0
    duplicates: int = 0
    self_filtered: int = 0
    history_filtered: int = 0
    pages_read: int = 0
    error_code: str | None = None
    backfill_limit_reached: bool = False

    def freeze(self) -> MonitorPollResult:
        return MonitorPollResult(**self.__dict__)


class CommentMonitorService:
    def __init__(
        self,
        session_factory,
        connector,
        *,
        account_id: str,
        account_name: str,
        backfill_limit: int = 500,
    ) -> None:
        self.session_factory = session_factory
        self.connector = connector
        self.account_id = account_id
        self.account_name = account_name
        self.backfill_limit = backfill_limit
        self.checkpoints = CheckpointStore(session_factory)

    async def poll_once(
        self, now: datetime, page_budget: int = 3
    ) -> MonitorPollResult:
        result = MutablePollResult()
        if page_budget <= 0:
            return result.freeze()
        backfill = self._load_backfill_state()

        for target_row in self._eligible_targets(now):
            if result.pages_read >= page_budget:
                break
            target = self._to_target(target_row)
            top_key = f"comments:{target.platform_content_id}"
            cursor = self.checkpoints.get(top_key)
            try:
                page = await self.connector.fetch_comment_page(target, cursor)
            except PlatformRateLimited:
                self._defer_target(target_row.id, now, "bilibili_rate_limited")
                result.error_code = "bilibili_rate_limited"
                break
            except PlatformRiskControl:
                self._pause_monitor("bilibili_risk_control")
                result.error_code = "bilibili_risk_control"
                break
            except CredentialsUnavailable:
                self._pause_monitor("bilibili_credentials_missing")
                result.error_code = "bilibili_credentials_missing"
                break
            except PlatformUnavailable:
                self._defer_target(target_row.id, now, "bilibili_unavailable")
                result.error_code = "bilibili_unavailable"
                continue

            result.pages_read += 1
            self._store_page(page.events, target_row.id, now, backfill, result)
            self._save_top_page(
                target_row.id,
                top_key,
                page.next_cursor,
                page.root_ids_with_replies,
                now,
                backfill.complete,
            )
            if backfill.limit_reached:
                result.backfill_limit_reached = True
                break

            pending_roots = self._pending_roots(target.platform_content_id)
            for root_comment_id in pending_roots:
                if result.pages_read >= page_budget:
                    break
                nested_key = self._nested_key(target.platform_content_id, root_comment_id)
                nested_cursor = self.checkpoints.get(nested_key)
                try:
                    nested_page = await self.connector.fetch_subcomment_page(
                        target, root_comment_id, nested_cursor
                    )
                except PlatformRateLimited:
                    self._defer_target(target_row.id, now, "bilibili_rate_limited")
                    result.error_code = "bilibili_rate_limited"
                    break
                except (PlatformRiskControl, CredentialsUnavailable) as exc:
                    code = (
                        "bilibili_risk_control"
                        if isinstance(exc, PlatformRiskControl)
                        else "bilibili_credentials_missing"
                    )
                    self._pause_monitor(code)
                    result.error_code = code
                    break
                except PlatformUnavailable:
                    self._defer_target(target_row.id, now, "bilibili_unavailable")
                    result.error_code = "bilibili_unavailable"
                    break

                result.pages_read += 1
                self._store_page(
                    nested_page.events, target_row.id, now, backfill, result
                )
                self._save_nested_page(
                    nested_key,
                    root_comment_id,
                    nested_page.next_cursor,
                    now,
                    backfill.complete,
                )
                if backfill.limit_reached:
                    result.backfill_limit_reached = True
                    break
            if result.error_code or backfill.limit_reached:
                break

        self._maybe_complete_backfill(now, backfill)
        return result.freeze()

    def _eligible_targets(self, now: datetime) -> list[MonitoredContentRecord]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(MonitoredContentRecord)
                    .where(MonitoredContentRecord.active.is_(True))
                    .where(
                        or_(
                            MonitoredContentRecord.next_poll_at.is_(None),
                            MonitoredContentRecord.next_poll_at <= now,
                        )
                    )
                    .order_by(
                        MonitoredContentRecord.last_polled_at.asc().nullsfirst(),
                        MonitoredContentRecord.published_at.desc(),
                    )
                ).all()
            )

    def _store_page(
        self,
        events: list[InteractionEvent],
        target_id: int,
        now: datetime,
        backfill: BackfillState,
        result: MutablePollResult,
    ) -> None:
        with self.session_factory.begin() as session:
            for event in events:
                if event.actor_id == self.account_id:
                    result.self_filtered += 1
                    continue
                existing = session.scalar(
                    select(EventRecord.id).where(EventRecord.event_id == event.event_id)
                )
                if existing is not None:
                    result.duplicates += 1
                    continue
                if (
                    backfill.complete
                    and backfill.watermark is not None
                    and event.platform_created_at <= backfill.watermark
                ):
                    result.history_filtered += 1
                    continue
                if not backfill.complete and backfill.imported >= self.backfill_limit:
                    self._mark_backfill_limit(session, backfill, now)
                    break
                row = EventRecord(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    payload_json=event.model_dump_json(),
                    monitored_content_id=target_id,
                    priority=classify_review_priority(event.content, self.account_name),
                    status="new",
                )
                if store_unique_event(session, row):
                    result.inserted += 1
                    if not backfill.complete:
                        backfill.imported += 1
                else:
                    result.duplicates += 1
                if not backfill.complete and backfill.imported >= self.backfill_limit:
                    self._mark_backfill_limit(session, backfill, now)
                    break
            self._set_setting(session, "comment_backfill_imported", str(backfill.imported))

    def _save_top_page(
        self,
        target_id: int,
        checkpoint_key: str,
        next_cursor: str | None,
        roots: tuple[str, ...],
        now: datetime,
        backfill_complete: bool,
    ) -> None:
        with self.session_factory.begin() as session:
            target = session.get(MonitoredContentRecord, target_id)
            target.last_polled_at = now
            target.next_poll_at = None
            target.failure_count = 0
            effective_cursor = None if backfill_complete else next_cursor
            self.checkpoints.set_in_session(
                session,
                checkpoint_key,
                effective_cursor,
                state={"initial_complete": next_cursor is None},
                now=now,
            )
            for root_comment_id in roots:
                nested_key = self._nested_key(
                    target.platform_content_id, root_comment_id
                )
                self.checkpoints.set_in_session(
                    session,
                    nested_key,
                    None,
                    state={"pending": True, "root_comment_id": root_comment_id},
                    now=now,
                )

    def _save_nested_page(
        self,
        checkpoint_key: str,
        root_comment_id: str,
        next_cursor: str | None,
        now: datetime,
        backfill_complete: bool,
    ) -> None:
        effective_cursor = None if backfill_complete else next_cursor
        with self.session_factory.begin() as session:
            self.checkpoints.set_in_session(
                session,
                checkpoint_key,
                effective_cursor,
                state={
                    "pending": effective_cursor is not None,
                    "root_comment_id": root_comment_id,
                    "initial_complete": next_cursor is None,
                },
                now=now,
            )

    def _pending_roots(self, platform_content_id: str) -> list[str]:
        prefix = f"subcomments:{platform_content_id}:"
        roots: list[str] = []
        with self.session_factory() as session:
            rows = session.scalars(
                select(MonitorCheckpointRecord)
                .where(MonitorCheckpointRecord.checkpoint_key.startswith(prefix))
                .order_by(MonitorCheckpointRecord.updated_at.asc())
            ).all()
            for row in rows:
                state = json.loads(row.state_json)
                if state.get("pending") and state.get("root_comment_id"):
                    roots.append(str(state["root_comment_id"]))
        return roots

    def _defer_target(self, target_id: int, now: datetime, error_code: str) -> None:
        with self.session_factory.begin() as session:
            target = session.get(MonitoredContentRecord, target_id)
            target.failure_count += 1
            index = min(target.failure_count - 1, len(BACKOFF_DELAYS) - 1)
            target.next_poll_at = now + BACKOFF_DELAYS[index]
            self._set_setting(session, "comment_monitor_error_code", error_code)

    def _pause_monitor(self, error_code: str) -> None:
        with self.session_factory.begin() as session:
            self._set_setting(session, "comment_monitor_enabled", "false")
            self._set_setting(session, "comment_monitor_error_code", error_code)

    def _load_backfill_state(self) -> BackfillState:
        with self.session_factory() as session:
            imported = int(self._get_setting(session, "comment_backfill_imported", "0"))
            complete = (
                self._get_setting(session, "comment_backfill_complete", "false") == "true"
            )
            raw_watermark = self._get_setting(
                session, "comment_backfill_watermark", ""
            )
        watermark = datetime.fromisoformat(raw_watermark) if raw_watermark else None
        return BackfillState(imported, complete, watermark)

    def _mark_backfill_limit(
        self, session, backfill: BackfillState, now: datetime
    ) -> None:
        backfill.complete = True
        backfill.limit_reached = True
        backfill.watermark = now
        self._set_setting(session, "comment_backfill_complete", "true")
        self._set_setting(session, "comment_backfill_watermark", now.isoformat())

    def _maybe_complete_backfill(
        self, now: datetime, backfill: BackfillState
    ) -> None:
        if backfill.complete:
            return
        with self.session_factory.begin() as session:
            targets = session.scalars(
                select(MonitoredContentRecord).where(
                    MonitoredContentRecord.active.is_(True)
                )
            ).all()
            if not targets:
                return
            for target in targets:
                checkpoint = session.scalar(
                    select(MonitorCheckpointRecord).where(
                        MonitorCheckpointRecord.checkpoint_key
                        == f"comments:{target.platform_content_id}"
                    )
                )
                if checkpoint is None or not json.loads(checkpoint.state_json).get(
                    "initial_complete"
                ):
                    return
            nested = session.scalars(
                select(MonitorCheckpointRecord).where(
                    MonitorCheckpointRecord.checkpoint_key.startswith("subcomments:")
                )
            ).all()
            if any(json.loads(row.state_json).get("pending") for row in nested):
                return
            backfill.complete = True
            backfill.watermark = now
            self._set_setting(session, "comment_backfill_complete", "true")
            self._set_setting(session, "comment_backfill_watermark", now.isoformat())

    @staticmethod
    def _get_setting(session, key: str, default: str) -> str:
        row = session.scalar(
            select(SystemSettingRecord).where(SystemSettingRecord.setting_key == key)
        )
        return row.setting_value if row else default

    @staticmethod
    def _set_setting(session, key: str, value: str) -> None:
        row = session.scalar(
            select(SystemSettingRecord).where(SystemSettingRecord.setting_key == key)
        )
        if row is None:
            session.add(SystemSettingRecord(setting_key=key, setting_value=value))
        else:
            row.setting_value = value

    @staticmethod
    def _nested_key(platform_content_id: str, root_comment_id: str) -> str:
        return f"subcomments:{platform_content_id}:{root_comment_id}"

    @staticmethod
    def _to_target(row: MonitoredContentRecord) -> PlatformContentTarget:
        return PlatformContentTarget(
            platform_content_id=row.platform_content_id,
            display_type=row.display_type,
            comment_oid=row.comment_oid,
            resource_type=row.resource_type,
            title=row.title,
            published_at=row.published_at,
        )

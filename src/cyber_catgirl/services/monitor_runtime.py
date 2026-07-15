import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, or_, select

from cyber_catgirl.models import EventRecord, PublishJobRecord


@dataclass(frozen=True)
class MonitorCycleResult:
    enabled: bool
    pages_read: int = 0
    events_inserted: int = 0
    generation_started: int = 0
    generation_failed: int = 0
    publish_started: int = 0
    publish_failed: int = 0

    @classmethod
    def disabled(cls) -> "MonitorCycleResult":
        return cls(enabled=False)


class MonitorRuntime:
    def __init__(
        self,
        session_factory,
        settings,
        comment_monitor,
        reply_service,
        publisher,
        content_discovery=None,
        prepare=None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.comment_monitor = comment_monitor
        self.reply_service = reply_service
        self.publisher = publisher
        self.content_discovery = content_discovery
        self.prepare = prepare or (lambda: None)
        self._cycle_lock = asyncio.Lock()
        self._manual_pending = False

    async def run_cycle(
        self, now: datetime | None = None, force: bool = False
    ) -> MonitorCycleResult:
        now = now or datetime.now(timezone.utc)
        if not force and not self.settings.comment_monitor_enabled:
            return MonitorCycleResult.disabled()

        async with self._cycle_lock:
            self.prepare()
            poll = await self.comment_monitor.poll_once(now, page_budget=3)
            event_ids = self._pending_event_ids(now, limit=20)
            semaphore = asyncio.Semaphore(2)

            async def generate(event_id: str):
                async with semaphore:
                    return await self.reply_service.process_event(event_id)

            generated = await asyncio.gather(
                *(generate(event_id) for event_id in event_ids),
                return_exceptions=True,
            )

            due_job_ids = []
            if not self.settings.kill_switch:
                due_job_ids = self._due_publish_job_ids(now, limit=5)
            published = []
            for job_id in due_job_ids:
                try:
                    published.append(await self.publisher.execute(job_id, now=now))
                except Exception as exc:
                    published.append(exc)
            return MonitorCycleResult(
                enabled=True,
                pages_read=poll.pages_read,
                events_inserted=poll.inserted,
                generation_started=len(event_ids),
                generation_failed=sum(
                    isinstance(item, Exception) for item in generated
                ),
                publish_started=len(due_job_ids),
                publish_failed=sum(
                    isinstance(item, Exception) for item in published
                ),
            )

    async def discover_contents(
        self, now: datetime | None = None, force: bool = False
    ):
        if self.content_discovery is None:
            return None
        if not force and not self.settings.comment_monitor_enabled:
            return None
        self.prepare()
        return await self.content_discovery.run_once(
            now or datetime.now(timezone.utc)
        )

    def request_manual_cycle(self) -> bool:
        if self._manual_pending or self._cycle_lock.locked():
            return False
        self._manual_pending = True

        async def execute_manual() -> None:
            try:
                await self.discover_contents(force=True)
                await self.run_cycle(force=True)
            finally:
                self._manual_pending = False

        asyncio.create_task(execute_manual())
        return True

    def apply_settings(self, settings) -> None:
        self.settings = settings
        self.reply_service.min_delay_seconds = settings.auto_reply_min_delay_seconds
        self.reply_service.max_delay_seconds = settings.auto_reply_max_delay_seconds
        safety = self.reply_service.safety_engine
        safety.run_mode = settings.run_mode
        safety.kill_switch = settings.kill_switch
        safety.comment_auto_reply_enabled = settings.comment_auto_reply_enabled
        safety.write_enabled = settings.bilibili_write_enabled
        safety.min_reply_interval_seconds = settings.auto_reply_min_delay_seconds
        safety.user_daily_limit = settings.auto_reply_user_daily_limit
        safety.account_hourly_limit = settings.auto_reply_account_hourly_limit
        safety.account_daily_limit = settings.auto_reply_account_daily_limit

    def _pending_event_ids(self, now: datetime, limit: int) -> list[str]:
        priority_order = case(
            (EventRecord.priority == "urgent", 0),
            (EventRecord.priority == "high", 1),
            else_=2,
        )
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(EventRecord.event_id)
                    .where(EventRecord.status.in_(("new", "generation_failed")))
                    .where(
                        or_(
                            EventRecord.next_attempt_at.is_(None),
                            EventRecord.next_attempt_at <= now,
                        )
                    )
                    .order_by(priority_order, EventRecord.created_at.desc())
                    .limit(limit)
                ).all()
            )

    def _due_publish_job_ids(self, now: datetime, limit: int) -> list[int]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(PublishJobRecord.id)
                    .where(PublishJobRecord.status.in_(("pending", "retry_wait")))
                    .where(
                        or_(
                            PublishJobRecord.next_attempt_at.is_(None),
                            PublishJobRecord.next_attempt_at <= now,
                        )
                    )
                    .order_by(PublishJobRecord.created_at.asc())
                    .limit(limit)
                ).all()
            )

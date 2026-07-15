import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import EventRecord, PublishJobRecord
from cyber_catgirl.services.comment_monitor import MonitorPollResult
from cyber_catgirl.services.monitor_runtime import MonitorRuntime


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)


class RecordingMonitor:
    async def poll_once(self, now: datetime, page_budget: int = 3):
        return MonitorPollResult(inserted=25, pages_read=page_budget)


class RecordingReplyService:
    def __init__(self):
        self.event_ids: list[str] = []
        self.active = 0
        self.max_observed_concurrency = 0

    async def process_event(self, event_id: str):
        self.active += 1
        self.max_observed_concurrency = max(
            self.max_observed_concurrency, self.active
        )
        await asyncio.sleep(0)
        self.event_ids.append(event_id)
        self.active -= 1
        return object()


class RecordingPublisher:
    def __init__(self):
        self.executed_job_ids: list[int] = []

    async def execute(self, job_id: int, now: datetime | None = None):
        self.executed_job_ids.append(job_id)
        return object()


@dataclass
class RuntimeFixture:
    runtime: MonitorRuntime
    sessions: object
    replies: RecordingReplyService
    publisher: RecordingPublisher


def make_runtime() -> RuntimeFixture:
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    replies = RecordingReplyService()
    publisher = RecordingPublisher()
    runtime = MonitorRuntime(
        sessions,
        Settings(comment_monitor_enabled=True),
        RecordingMonitor(),
        replies,
        publisher,
    )
    return RuntimeFixture(runtime, sessions, replies, publisher)


async def test_cycle_caps_generation_at_twenty_and_concurrency_at_two():
    fixture = make_runtime()
    with fixture.sessions.begin() as session:
        for index in range(25):
            session.add(
                EventRecord(
                    event_id=f"comment_{index}",
                    event_type="new_comment",
                    status="new",
                    priority="normal",
                )
            )

    result = await fixture.runtime.run_cycle(now=NOW)

    assert result.pages_read == 3
    assert result.generation_started == 20
    assert fixture.replies.max_observed_concurrency <= 2


async def test_cycle_executes_only_due_publish_jobs():
    fixture = make_runtime()
    with fixture.sessions.begin() as session:
        session.add_all(
            [
                PublishJobRecord(
                    idempotency_key="due",
                    status="pending",
                    next_attempt_at=NOW - timedelta(seconds=1),
                ),
                PublishJobRecord(
                    idempotency_key="future",
                    status="retry_wait",
                    next_attempt_at=NOW + timedelta(minutes=5),
                ),
            ]
        )

    result = await fixture.runtime.run_cycle(now=NOW)

    assert result.publish_started == 1
    assert fixture.publisher.executed_job_ids == [1]


async def test_disabled_cycle_performs_no_work_unless_forced():
    fixture = make_runtime()
    fixture.runtime.settings.comment_monitor_enabled = False

    result = await fixture.runtime.run_cycle(now=NOW)

    assert result.enabled is False
    assert fixture.replies.event_ids == []
    assert fixture.publisher.executed_job_ids == []


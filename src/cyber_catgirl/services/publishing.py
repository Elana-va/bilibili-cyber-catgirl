from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cyber_catgirl.connectors.base import BilibiliPort
from cyber_catgirl.connectors.bilibili_api import (
    CredentialsUnavailable,
    PlatformRateLimited,
    PlatformRiskControl,
    PlatformUnavailable,
    WriteNotAuthorized,
)
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import InteractionEvent


TERMINAL_STATUSES = {"succeeded", "failed", "visibility_unknown", "cancelled"}
RETRY_BACKOFF = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=60),
)


@dataclass(frozen=True)
class PublishResult:
    job_id: int
    status: str
    platform_id: str | None


class Publisher:
    def __init__(self, session_factory, connector: BilibiliPort) -> None:
        self.session_factory = session_factory
        self.connector = connector

    async def execute(
        self, job_id: int, now: datetime | None = None
    ) -> PublishResult:
        now = now or datetime.now(timezone.utc)
        with self.session_factory() as session:
            job = session.get(PublishJobRecord, job_id)
            if job is None:
                raise LookupError(f"publish job not found: {job_id}")
            if job.status in TERMINAL_STATUSES:
                return PublishResult(job.id, job.status, job.platform_id)
            if job.status == "retry_wait" and job.next_attempt_at:
                if _as_utc(job.next_attempt_at) > _as_utc(now):
                    return PublishResult(job.id, job.status, job.platform_id)
            if job.platform_id:
                job.status = "visibility_unknown"
                job.completed_at = now
                job.next_attempt_at = None
                session.commit()
                return PublishResult(job.id, job.status, job.platform_id)
            draft = session.get(DraftRecord, job.draft_id)
            if draft is None or draft.event_id is None:
                raise LookupError("reply draft or source event is missing")
            event_row = session.get(EventRecord, draft.event_id)
            if event_row is None:
                raise LookupError("source event is missing")
            event = InteractionEvent.model_validate_json(event_row.payload_json)
            content = draft.content
            job.status = "sending"
            job.attempts += 1
            attempts = job.attempts
            job.last_error_code = None
            job.next_attempt_at = None
            session.commit()

        try:
            platform_id = await self.connector.reply_to_comment(
                event.target_id,
                event.target_type,
                event.root_comment_id or event.event_id.removeprefix("comment_"),
                event.parent_comment_id,
                content,
            )
            with self.session_factory() as session:
                job = session.get(PublishJobRecord, job_id)
                job.platform_id = platform_id
                session.commit()

            visible = await self.connector.verify_publication(
                platform_id, event.target_id, event.target_type
            )
            final_status = "succeeded" if visible else "visibility_unknown"
            error_code = None
            next_attempt_at = None
        except PlatformRateLimited:
            final_status = "retry_wait"
            error_code = "bilibili_rate_limited"
            next_attempt_at = _retry_at(now, attempts)
        except PlatformUnavailable:
            final_status = "retry_wait"
            error_code = "bilibili_unavailable"
            next_attempt_at = _retry_at(now, attempts)
        except PlatformRiskControl:
            final_status = "cancelled"
            error_code = "bilibili_risk_control"
            next_attempt_at = None
        except CredentialsUnavailable:
            final_status = "failed"
            error_code = "bilibili_credentials_missing"
            next_attempt_at = None
        except WriteNotAuthorized:
            final_status = "failed"
            error_code = "bilibili_write_disabled"
            next_attempt_at = None
        except Exception:
            final_status = "failed"
            error_code = "bilibili_publish_failed"
            next_attempt_at = None

        with self.session_factory() as session:
            job = session.get(PublishJobRecord, job_id)
            job.status = final_status
            job.last_error_code = error_code
            job.next_attempt_at = next_attempt_at
            if final_status in TERMINAL_STATUSES:
                job.completed_at = now
            session.commit()
            return PublishResult(job.id, job.status, job.platform_id)


def _retry_at(now: datetime, attempts: int) -> datetime:
    index = min(max(attempts - 1, 0), len(RETRY_BACKOFF) - 1)
    return now + RETRY_BACKOFF[index]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

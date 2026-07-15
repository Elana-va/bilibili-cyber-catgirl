from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from cyber_catgirl.config import RunMode
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
    error_code: str | None = None


@dataclass(frozen=True)
class AutoGateDecision:
    allowed: bool
    status: str = "cancelled"
    error_code: str | None = None
    next_attempt_at: datetime | None = None


class AutoPublishGuard:
    def __init__(self, session_factory, settings) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def evaluate(self, job_id: int, now: datetime) -> AutoGateDecision:
        with self.session_factory() as session:
            job = session.get(PublishJobRecord, job_id)
            if job is None:
                return AutoGateDecision(False, error_code="publish_job_missing")
            draft = session.get(DraftRecord, job.draft_id)
            event_row = session.get(EventRecord, draft.event_id) if draft else None
            if self.settings.kill_switch or not self.settings.bilibili_write_enabled:
                return AutoGateDecision(False, error_code="publish_gate_closed")
            if job.source == "auto":
                if draft is None or event_row is None:
                    return AutoGateDecision(False, error_code="auto_source_missing")
                if (
                    self.settings.run_mode is not RunMode.LIMITED_AUTO
                    or not self.settings.comment_auto_reply_enabled
                ):
                    return AutoGateDecision(False, error_code="auto_gate_closed")
                if draft.review_status != "auto_approved" or draft.risk_level != "low":
                    return AutoGateDecision(
                        False, error_code="auto_draft_not_eligible"
                    )
            event = (
                InteractionEvent.model_validate_json(event_row.payload_json)
                if event_row is not None
                else None
            )
            sent_attempts = session.execute(
                select(PublishJobRecord, EventRecord)
                .join(DraftRecord, PublishJobRecord.draft_id == DraftRecord.id)
                .outerjoin(EventRecord, DraftRecord.event_id == EventRecord.id)
                .where(
                    or_(
                        PublishJobRecord.status.in_(
                            ("succeeded", "visibility_unknown")
                        ),
                        PublishJobRecord.platform_id.is_not(None),
                    )
                )
            ).all()

        start_hour = now.replace(minute=0, second=0, microsecond=0)
        start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        account_hour = account_day = user_day = 0
        latest: datetime | None = None
        for prior_job, prior_event_row in sent_attempts:
            completed = _as_utc(prior_job.completed_at or prior_job.created_at)
            if completed >= start_hour:
                account_hour += 1
            if completed >= start_day:
                account_day += 1
                if event is not None and prior_event_row is not None:
                    prior_event = InteractionEvent.model_validate_json(
                        prior_event_row.payload_json
                    )
                    if prior_event.actor_id == event.actor_id:
                        user_day += 1
            if latest is None or completed > latest:
                latest = completed

        retry_candidates: list[datetime] = []
        if latest is not None:
            earliest = latest + timedelta(
                seconds=self.settings.auto_reply_min_delay_seconds
            )
            if earliest > now:
                retry_candidates.append(earliest)
        if account_hour >= self.settings.auto_reply_account_hourly_limit:
            retry_candidates.append(start_hour + timedelta(hours=1))
        if (
            account_day >= self.settings.auto_reply_account_daily_limit
            or user_day >= self.settings.auto_reply_user_daily_limit
        ):
            retry_candidates.append(start_day + timedelta(days=1))
        if retry_candidates:
            return AutoGateDecision(
                False,
                status="retry_wait",
                error_code=(
                    "auto_rate_limited"
                    if job.source == "auto"
                    else "publish_rate_limited"
                ),
                next_attempt_at=max(retry_candidates),
            )
        return AutoGateDecision(True)


class Publisher:
    def __init__(
        self,
        session_factory,
        connector: BilibiliPort,
        *,
        auto_guard: AutoPublishGuard | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.connector = connector
        self.auto_guard = auto_guard

    async def execute(
        self, job_id: int, now: datetime | None = None
    ) -> PublishResult:
        now = now or datetime.now(timezone.utc)
        with self.session_factory() as session:
            job = session.get(PublishJobRecord, job_id)
            if job is None:
                raise LookupError(f"publish job not found: {job_id}")
            if job.status in TERMINAL_STATUSES:
                return PublishResult(
                    job.id, job.status, job.platform_id, job.last_error_code
                )
            if job.status == "retry_wait" and job.next_attempt_at:
                if _as_utc(job.next_attempt_at) > _as_utc(now):
                    return PublishResult(
                        job.id, job.status, job.platform_id, job.last_error_code
                    )
            if job.platform_id:
                job.status = "visibility_unknown"
                job.completed_at = now
                job.next_attempt_at = None
                session.commit()
                return PublishResult(
                    job.id, job.status, job.platform_id, job.last_error_code
                )
            if self.auto_guard is not None:
                gate = self.auto_guard.evaluate(job.id, now)
                if not gate.allowed:
                    job.status = gate.status
                    job.last_error_code = gate.error_code
                    job.next_attempt_at = gate.next_attempt_at
                    if gate.status == "cancelled":
                        job.completed_at = now
                    session.commit()
                    return PublishResult(
                        job.id, job.status, job.platform_id, job.last_error_code
                    )
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
                job.completed_at = now
                session.commit()

            visible = await self.connector.verify_publication(
                platform_id,
                event.target_id,
                event.target_type,
                event.root_comment_id,
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
            return PublishResult(
                job.id, job.status, job.platform_id, job.last_error_code
            )


def _retry_at(now: datetime, attempts: int) -> datetime:
    index = min(max(attempts - 1, 0), len(RETRY_BACKOFF) - 1)
    return now + RETRY_BACKOFF[index]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

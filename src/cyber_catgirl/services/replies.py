import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from cyber_catgirl.agent.service import AgentGenerationError
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import ActionType, InteractionEvent
from cyber_catgirl.services.memory import MemoryService
from cyber_catgirl.services.safety import SafetyCounters, SafetyEngine


GENERATION_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
)


class ReplyGenerationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ReplyService:
    def __init__(
        self,
        session_factory,
        agent,
        memory_service: MemoryService,
        safety_engine: SafetyEngine,
        *,
        now_provider=None,
        delay_selector=None,
        min_delay_seconds: int = 8,
        max_delay_seconds: int = 20,
    ) -> None:
        self.session_factory = session_factory
        self.agent = agent
        self.memory_service = memory_service
        self.safety_engine = safety_engine
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.delay_selector = delay_selector or random.randint
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    async def process_event(self, event_id: str) -> DraftRecord | None:
        with self.session_factory() as session:
            event_row = session.scalar(
                select(EventRecord).where(EventRecord.event_id == event_id)
            )
            if event_row is None:
                raise LookupError(f"event not found: {event_id}")
            existing = session.scalar(
                select(DraftRecord).where(
                    DraftRecord.event_id == event_row.id,
                    DraftRecord.draft_type == "reply",
                )
            )
            if existing is not None:
                return existing
            event = InteractionEvent.model_validate_json(event_row.payload_json)
            event_row.status = "generating"
            session.commit()

        context = self.memory_service.get_context(event.actor_id, event.content)
        try:
            decision = await self.agent.decide(event, context)
        except AgentGenerationError as exc:
            self._mark_generation_failure(event_id, exc.code)
            raise ReplyGenerationError(exc.code) from exc

        if decision.action is ActionType.IGNORE:
            self._mark_ignored(event_id)
            return None
        if decision.action is not ActionType.REPLY or not decision.content.strip():
            code = "model_escalated" if decision.action is ActionType.ESCALATE else "invalid_model_output"
            self._mark_generation_failure(event_id, code)
            raise ReplyGenerationError(code)

        now = self.now_provider()
        counters = self._safety_counters(event.actor_id, now)
        verdict = self.safety_engine.evaluate(event, decision, counters)

        with self.session_factory() as session:
            event_row = session.scalar(
                select(EventRecord).where(EventRecord.event_id == event_id)
            )
            if event_row is None:
                raise LookupError(f"event disappeared: {event_id}")
            existing = session.scalar(
                select(DraftRecord).where(
                    DraftRecord.event_id == event_row.id,
                    DraftRecord.draft_type == "reply",
                )
            )
            if existing is not None:
                return existing
            draft = DraftRecord(
                event_id=event_row.id,
                draft_type="reply",
                content=decision.content,
                risk_level=decision.risk_level.value,
                review_status=(
                    "auto_approved" if verdict.allow_auto_publish else "pending"
                ),
                safety_reasons_json=json.dumps(verdict.reasons, ensure_ascii=False),
                updated_at=now,
            )
            session.add(draft)
            session.flush()
            if verdict.allow_auto_publish:
                delay = self.delay_selector(
                    self.min_delay_seconds, self.max_delay_seconds
                )
                session.add(
                    PublishJobRecord(
                        draft_id=draft.id,
                        idempotency_key=f"reply:{event.event_id}",
                        status="pending",
                        source="auto",
                        next_attempt_at=now + timedelta(seconds=delay),
                    )
                )
            event_row.status = "drafted"
            event_row.last_error_code = None
            event_row.next_attempt_at = None
            session.commit()
            session.refresh(draft)

        self.memory_service.apply_updates(
            event.actor_id,
            event.event_id,
            decision.memory_updates,
        )
        return draft

    def _mark_ignored(self, event_id: str) -> None:
        with self.session_factory.begin() as session:
            event = session.scalar(
                select(EventRecord).where(EventRecord.event_id == event_id)
            )
            if event is None:
                raise LookupError(f"event disappeared: {event_id}")
            event.status = "ignored"
            event.last_error_code = None
            event.next_attempt_at = None

    def _mark_generation_failure(self, event_id: str, code: str) -> None:
        now = self.now_provider()
        with self.session_factory.begin() as session:
            event = session.scalar(
                select(EventRecord).where(EventRecord.event_id == event_id)
            )
            if event is None:
                raise LookupError(f"event disappeared: {event_id}")
            event.processing_attempts += 1
            event.status = "generation_failed"
            event.last_error_code = code
            if event.processing_attempts <= len(GENERATION_BACKOFF):
                event.next_attempt_at = now + GENERATION_BACKOFF[event.processing_attempts - 1]
            else:
                event.next_attempt_at = None

    def _safety_counters(self, actor_id: str, now: datetime) -> SafetyCounters:
        start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_hour = now.replace(minute=0, second=0, microsecond=0)
        with self.session_factory() as session:
            rows = session.execute(
                select(PublishJobRecord, EventRecord)
                .join(DraftRecord, PublishJobRecord.draft_id == DraftRecord.id)
                .join(EventRecord, DraftRecord.event_id == EventRecord.id)
                .where(PublishJobRecord.source == "auto")
                .where(PublishJobRecord.status == "succeeded")
            ).all()

        account_today = 0
        account_hour = 0
        user_today = 0
        latest: datetime | None = None
        for job, event_row in rows:
            completed_at = self._aware(job.completed_at or job.created_at)
            if completed_at >= start_day:
                account_today += 1
                event = InteractionEvent.model_validate_json(event_row.payload_json)
                if event.actor_id == actor_id:
                    user_today += 1
            if completed_at >= start_hour:
                account_hour += 1
            if latest is None or completed_at > latest:
                latest = completed_at
        elapsed = int((now - latest).total_seconds()) if latest else None
        return SafetyCounters(
            last_auto_reply_seconds_ago=elapsed,
            user_auto_replies_today=user_today,
            account_auto_replies_hour=account_hour,
            account_auto_replies_today=account_today,
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

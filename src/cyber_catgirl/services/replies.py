from sqlalchemy import select

from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import InteractionEvent
from cyber_catgirl.services.memory import MemoryService
from cyber_catgirl.services.safety import SafetyCounters, SafetyEngine


class ReplyService:
    def __init__(
        self,
        session_factory,
        agent,
        memory_service: MemoryService,
        safety_engine: SafetyEngine,
    ) -> None:
        self.session_factory = session_factory
        self.agent = agent
        self.memory_service = memory_service
        self.safety_engine = safety_engine

    async def process_event(self, event_id: str) -> DraftRecord:
        with self.session_factory() as session:
            event_row = session.scalar(select(EventRecord).where(EventRecord.event_id == event_id))
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

        context = self.memory_service.get_context(event.actor_id, event.content)
        decision = await self.agent.decide(event, context)
        verdict = self.safety_engine.evaluate(event, decision, SafetyCounters())

        with self.session_factory() as session:
            event_row = session.scalar(select(EventRecord).where(EventRecord.event_id == event_id))
            if event_row is None:
                raise LookupError(f"event disappeared: {event_id}")
            draft = DraftRecord(
                event_id=event_row.id,
                draft_type="reply",
                content=decision.content,
                risk_level=decision.risk_level.value,
                review_status="auto_approved" if verdict.allow_auto_publish else "pending",
            )
            session.add(draft)
            session.flush()
            if verdict.allow_auto_publish:
                session.add(
                    PublishJobRecord(
                        draft_id=draft.id,
                        idempotency_key=f"reply:{event.event_id}",
                        status="pending",
                    )
                )
            event_row.status = "drafted"
            session.commit()
            session.refresh(draft)

        self.memory_service.apply_updates(
            event.actor_id,
            event.event_id,
            decision.memory_updates,
        )
        return draft

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cyber_catgirl.models import EventRecord, MemoryRecord, MessageRecord


SENSITIVE_MEMORY_TERMS = {
    "身份证",
    "密码",
    "住址",
    "精确地址",
    "手机号",
    "电话号",
    "cookie",
    "token",
    "sessdata",
}


@dataclass(frozen=True)
class MemoryContext:
    recent_messages: list[str] = field(default_factory=list)
    long_term: list[str] = field(default_factory=list)


def normalize_memory(text: str) -> str:
    return " ".join(text.strip().lower().split())


class MemoryService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def get_context(
        self,
        actor_id: str,
        query: str,
        *,
        recent_limit: int = 20,
        memory_limit: int = 5,
    ) -> MemoryContext:
        with self.session_factory() as session:
            messages = session.scalars(
                select(MessageRecord)
                .where(MessageRecord.actor_id == actor_id)
                .order_by(MessageRecord.created_at.desc())
                .limit(recent_limit)
            ).all()
            memories = session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.actor_id == actor_id)
                .order_by(MemoryRecord.updated_at.desc())
                .limit(memory_limit)
            ).all()
        return MemoryContext(
            recent_messages=[row.content for row in reversed(messages)],
            long_term=[row.memory_text for row in memories],
        )

    def apply_updates(self, actor_id: str, source_event_id: str, updates: list[str]) -> int:
        with self.session_factory() as session:
            source_exists = session.scalar(
                select(EventRecord.id).where(EventRecord.event_id == source_event_id)
            )
        if source_exists is None:
            return 0

        inserted = 0
        for text in updates:
            normalized = normalize_memory(text)
            if not 5 <= len(text.strip()) <= 100:
                continue
            if any(term in normalized for term in SENSITIVE_MEMORY_TERMS):
                continue
            with self.session_factory() as session:
                session.add(
                    MemoryRecord(
                        actor_id=actor_id,
                        source_event_id=source_event_id,
                        memory_text=text.strip(),
                        normalized_text=normalized,
                    )
                )
                try:
                    session.commit()
                    inserted += 1
                except IntegrityError:
                    session.rollback()
        return inserted

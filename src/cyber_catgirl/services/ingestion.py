from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from cyber_catgirl.connectors.base import BilibiliPort
from cyber_catgirl.models import EventRecord


@dataclass(frozen=True)
class IngestionResult:
    inserted: int
    duplicates: int
    next_cursor: str | None


class IngestionService:
    def __init__(self, connector: BilibiliPort, session_factory) -> None:
        self.connector = connector
        self.session_factory = session_factory

    async def poll_once(self, cursor: str | None) -> IngestionResult:
        events, next_cursor = await self.connector.fetch_comments(cursor)
        inserted = 0
        duplicates = 0

        for event in events:
            with self.session_factory() as session:
                session.add(
                    EventRecord(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload_json=event.model_dump_json(),
                    )
                )
                try:
                    session.commit()
                    inserted += 1
                except IntegrityError:
                    session.rollback()
                    duplicates += 1

        return IngestionResult(
            inserted=inserted,
            duplicates=duplicates,
            next_cursor=next_cursor,
        )

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from cyber_catgirl.connectors.base import BilibiliPort
from cyber_catgirl.models import EventRecord


def store_unique_event(session, row: EventRecord) -> bool:
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return False
    return True


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
                was_inserted = store_unique_event(
                    session,
                    EventRecord(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        payload_json=event.model_dump_json(),
                    ),
                )
                session.commit()
                if was_inserted:
                    inserted += 1
                else:
                    duplicates += 1

        return IngestionResult(
            inserted=inserted,
            duplicates=duplicates,
            next_cursor=next_cursor,
        )

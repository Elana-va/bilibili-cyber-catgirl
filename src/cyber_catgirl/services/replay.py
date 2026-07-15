from dataclasses import dataclass

from sqlalchemy import select

from cyber_catgirl.config import RunMode
from cyber_catgirl.models import EventRecord, PublishJobRecord
from cyber_catgirl.services.ingestion import IngestionService
from cyber_catgirl.services.memory import MemoryService
from cyber_catgirl.services.publishing import Publisher
from cyber_catgirl.services.replies import ReplyService
from cyber_catgirl.services.safety import SafetyEngine


@dataclass(frozen=True)
class ReplayResult:
    events_inserted: int
    duplicates: int
    drafts_created: int
    publications_succeeded: int


async def replay_events(
    session_factory,
    connector,
    agent,
    *,
    run_mode: RunMode = RunMode.MANUAL_ONLY,
    kill_switch: bool = False,
    allowed_actor_ids: set[str] | None = None,
    comment_auto_reply_enabled: bool = False,
    write_enabled: bool = False,
) -> ReplayResult:
    """Run one deterministic ingest-to-publish cycle for fixtures or dry runs."""
    ingestion = await IngestionService(connector, session_factory).poll_once(None)
    reply_service = ReplyService(
        session_factory,
        agent,
        MemoryService(session_factory),
        SafetyEngine(
            run_mode=run_mode,
            kill_switch=kill_switch,
            allowed_actor_ids=allowed_actor_ids,
            comment_auto_reply_enabled=comment_auto_reply_enabled,
            write_enabled=write_enabled,
        ),
    )

    with session_factory() as session:
        new_event_ids = session.scalars(
            select(EventRecord.event_id)
            .where(EventRecord.status == "new")
            .order_by(EventRecord.id)
        ).all()

    for event_id in new_event_ids:
        await reply_service.process_event(event_id)

    with session_factory() as session:
        pending_job_ids = session.scalars(
            select(PublishJobRecord.id)
            .where(PublishJobRecord.status == "pending")
            .order_by(PublishJobRecord.id)
        ).all()

    publisher = Publisher(session_factory, connector)
    succeeded = 0
    for job_id in pending_job_ids:
        result = await publisher.execute(job_id)
        if result.status == "succeeded":
            succeeded += 1

    return ReplayResult(
        events_inserted=ingestion.inserted,
        duplicates=ingestion.duplicates,
        drafts_created=len(new_event_ids),
        publications_succeeded=succeeded,
    )

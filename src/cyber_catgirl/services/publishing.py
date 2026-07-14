from dataclasses import dataclass

from cyber_catgirl.connectors.base import BilibiliPort
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.schemas import InteractionEvent


TERMINAL_STATUSES = {"succeeded", "failed", "visibility_unknown", "cancelled"}


@dataclass(frozen=True)
class PublishResult:
    job_id: int
    status: str
    platform_id: str | None


class Publisher:
    def __init__(self, session_factory, connector: BilibiliPort) -> None:
        self.session_factory = session_factory
        self.connector = connector

    async def execute(self, job_id: int) -> PublishResult:
        with self.session_factory() as session:
            job = session.get(PublishJobRecord, job_id)
            if job is None:
                raise LookupError(f"publish job not found: {job_id}")
            if job.status in TERMINAL_STATUSES:
                return PublishResult(job.id, job.status, job.platform_id)
            if job.status == "executing" and job.platform_id:
                return PublishResult(job.id, "visibility_unknown", job.platform_id)
            draft = session.get(DraftRecord, job.draft_id)
            if draft is None or draft.event_id is None:
                raise LookupError("reply draft or source event is missing")
            event_row = session.get(EventRecord, draft.event_id)
            if event_row is None:
                raise LookupError("source event is missing")
            event = InteractionEvent.model_validate_json(event_row.payload_json)
            content = draft.content
            job.status = "executing"
            job.attempts += 1
            session.commit()

        try:
            platform_id = await self.connector.reply_to_comment(
                event.target_id,
                event.parent_comment_id or event.event_id.removeprefix("comment_"),
                content,
            )
            with self.session_factory() as session:
                job = session.get(PublishJobRecord, job_id)
                job.platform_id = platform_id
                session.commit()

            visible = await self.connector.verify_publication(platform_id)
            final_status = "succeeded" if visible else "visibility_unknown"
        except Exception:
            final_status = "failed"

        with self.session_factory() as session:
            job = session.get(PublishJobRecord, job_id)
            job.status = final_status
            session.commit()
            return PublishResult(job.id, job.status, job.platform_id)

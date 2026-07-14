import json
from datetime import datetime, timezone

from sqlalchemy import select

from cyber_catgirl.connectors.fake import FakeBilibiliConnector
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import AuditLogRecord, EventRecord
from cyber_catgirl.schemas import InteractionEvent
from cyber_catgirl.services.audit import AuditService
from cyber_catgirl.services.ingestion import IngestionService


def make_comment_event(event_id: str) -> InteractionEvent:
    return InteractionEvent(
        event_id=event_id,
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="dynamic",
        target_id="d1",
        platform_created_at=datetime.now(timezone.utc),
    )


async def test_polling_same_comment_twice_creates_one_event():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    connector = FakeBilibiliConnector(events=[make_comment_event("comment_1")])
    service = IngestionService(connector, session_factory)

    first = await service.poll_once(None)
    second = await service.poll_once(None)

    with session_factory() as session:
        records = session.scalars(select(EventRecord)).all()
    assert len(records) == 1
    assert first.inserted == 1
    assert second.duplicates == 1


def test_audit_redacts_credentials_recursively():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    audit = AuditService(session_factory)

    audit.record(
        "connector_error",
        "x",
        {"SESSDATA": "secret", "nested": {"authorization": "Bearer token"}, "code": -101},
    )

    with session_factory() as session:
        row = session.scalar(select(AuditLogRecord))
    assert row is not None
    details = json.loads(row.details_json)
    assert details["SESSDATA"] == "[REDACTED]"
    assert details["nested"]["authorization"] == "[REDACTED]"
    assert "secret" not in row.details_json

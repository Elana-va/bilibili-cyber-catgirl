from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import EventRecord
from cyber_catgirl.services.memory import MemoryService


def add_source_event(session_factory, event_id: str) -> None:
    with session_factory() as session:
        session.add(EventRecord(event_id=event_id, event_type="new_comment"))
        session.commit()


def test_memories_are_isolated_by_actor():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    add_source_event(session_factory, "e1")
    add_source_event(session_factory, "e2")
    service = MemoryService(session_factory)

    service.apply_updates("u1", "e1", ["用户喜欢科幻"])
    service.apply_updates("u2", "e2", ["用户喜欢音乐"])

    context = service.get_context("u1", "喜欢什么")
    assert "用户喜欢科幻" in context.long_term
    assert all("音乐" not in item for item in context.long_term)


def test_memory_update_requires_a_real_source_event():
    service = MemoryService(create_session_factory("sqlite+pysqlite:///:memory:"))

    inserted = service.apply_updates("u1", "missing", ["喜欢科幻"])

    assert inserted == 0

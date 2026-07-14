from datetime import datetime, timezone

from cyber_catgirl.connectors.fake import FakeBilibiliConnector
from cyber_catgirl.research.connector_probe import CapabilityProbe
from cyber_catgirl.research.connector_probe import save_report
from cyber_catgirl.schemas import InteractionEvent


def make_event() -> InteractionEvent:
    return InteractionEvent(
        event_id="comment_1",
        event_type="new_comment",
        actor_id="u1",
        actor_name="用户",
        content="你好",
        target_type="dynamic",
        target_id="d1",
        platform_created_at=datetime.now(timezone.utc),
    )


async def test_read_only_probe_never_calls_write_methods():
    connector = FakeBilibiliConnector(events=[make_event()])

    report = await CapabilityProbe(connector).run(read_only=True)

    assert report.comment_read is True
    assert report.events_seen == 1
    assert connector.write_calls == []


async def test_write_probe_requires_explicit_target():
    connector = FakeBilibiliConnector()

    report = await CapabilityProbe(connector).run(read_only=False)

    assert report.comment_write is False
    assert report.errors == ["write probe target is required"]
    assert connector.write_calls == []


def test_probe_report_is_saved_as_utf8_json(tmp_path):
    path = tmp_path / "report.json"

    save_report(
        path,
        {"mode": "read_only", "comment_read": True, "note": "只读测试"},
    )

    content = path.read_text(encoding="utf-8")
    assert '"comment_read": true' in content
    assert "只读测试" in content

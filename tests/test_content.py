from datetime import date, datetime

from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DailyMetricRecord, ScheduledContentRecord
from cyber_catgirl.services.content import ContentService, SchedulePolicy


class FakeReportLLM:
    async def generate_json(self, messages: list[dict], schema: dict) -> dict:
        return {
            "content": "今日有55位小伙伴来找小喵聊天，共留下83条评论喵～",
            "scene": "qa",
            "address": "partner",
            "emoticon": "",
        }


class SequenceContentLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def generate_json(self, messages, schema):
        self.calls.append((messages, schema))
        return self.outputs.pop(0)


def seed_metrics(session_factory, metric_date: date) -> None:
    with session_factory() as session:
        session.add(
            DailyMetricRecord(
                metric_date=metric_date,
                unique_users=55,
                comment_count=83,
                replied_count=60,
                review_count=5,
                failed_count=1,
            )
        )
        session.commit()


async def test_daily_report_uses_database_metrics():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    metric_date = date(2026, 7, 14)
    seed_metrics(session_factory, metric_date)
    service = ContentService(session_factory, FakeReportLLM())

    draft = await service.create_daily_report(metric_date)

    assert draft.stats_snapshot["unique_users"] == 55
    assert "55" in draft.content
    assert draft.review_status == "pending"


async def test_second_report_for_same_date_returns_existing():
    session_factory = create_session_factory("sqlite+pysqlite:///:memory:")
    metric_date = date(2026, 7, 14)
    seed_metrics(session_factory, metric_date)
    service = ContentService(session_factory, FakeReportLLM())

    first = await service.create_daily_report(metric_date)
    second = await service.create_daily_report(metric_date)

    assert first.id == second.id


def test_normal_dynamic_is_delayed_during_quiet_hours():
    policy = SchedulePolicy()

    assert policy.may_publish(hour=23, category="normal") is False
    assert policy.may_publish(hour=8, category="normal") is True


async def test_daily_report_uses_v2_prompt_and_corrects_missing_miao_once():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    metric_date = date(2026, 7, 14)
    seed_metrics(sessions, metric_date)
    llm = SequenceContentLLM(
        [
            {
                "content": "今日有55位小伙伴互动，共83条评论。",
                "scene": "qa",
                "address": "partner",
                "emoticon": "",
            },
            {
                "content": "今日有55位小伙伴互动喵，共83条评论喵～",
                "scene": "qa",
                "address": "partner",
                "emoticon": "",
            },
        ]
    )
    service = ContentService(sessions, llm)

    draft = await service.create_daily_report(metric_date)

    assert draft.review_status == "pending"
    assert draft.content.count("喵") >= 2
    assert len(llm.calls) == 2
    assert "catgirl-v2" in llm.calls[0][0][0]["content"]
    assert "persona_missing_miao" in llm.calls[1][0][0]["content"]


async def test_dynamic_second_persona_failure_is_saved_for_manual_handling():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions.begin() as session:
        session.add(
            ScheduledContentRecord(
                schedule_key="demo",
                prompt="介绍今天的更新",
                run_at=datetime(2026, 7, 16, 9, 0),
                enabled=True,
            )
        )
    llm = SequenceContentLLM(
        [
            {"content": "今天更新了", "scene": "casual", "address": "none"},
            {"content": "还是更新了", "scene": "casual", "address": "none"},
        ]
    )
    service = ContentService(sessions, llm)

    draft = await service.create_scheduled_draft(
        1,
        datetime(2026, 7, 16, 9, 0),
    )

    assert draft.review_status == "validation_failed"
    assert len(llm.calls) == 2

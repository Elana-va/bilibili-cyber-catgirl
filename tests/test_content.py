from datetime import date

from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DailyMetricRecord
from cyber_catgirl.services.content import ContentService, SchedulePolicy


class FakeReportLLM:
    async def generate_json(self, messages: list[dict], schema: dict) -> dict:
        return {"content": "今日有55位小伙伴来找小喵聊天，共留下83条评论喵～"}


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

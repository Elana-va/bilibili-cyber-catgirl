from datetime import date, timedelta

from fastapi.testclient import TestClient

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.main import create_app
from cyber_catgirl.models import DailyMetricRecord
from cyber_catgirl.services.dashboard import DashboardService


def test_analytics_uses_database_metrics():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions() as session:
        session.add(
            DailyMetricRecord(
                metric_date=date.today(),
                unique_users=55,
                comment_count=89,
                replied_count=34,
                review_count=7,
                failed_count=1,
            )
        )
        session.commit()
    client = TestClient(create_app(Settings(), session_factory=sessions))

    response = client.get("/analytics?days=7")

    assert "55" in response.text
    assert 'data-series="comment_count"' in response.text


def test_analytics_missing_day_is_marked_without_interpolation():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions() as session:
        session.add(DailyMetricRecord(metric_date=date.today(), comment_count=12))
        session.commit()

    view = DashboardService(sessions).analytics(days=7)
    missing = next(point for point in view.points if point.metric_date == date.today() - timedelta(days=1))

    assert missing.has_data is False
    assert missing.comment_count == 0


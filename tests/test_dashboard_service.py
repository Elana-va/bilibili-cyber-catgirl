from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord, EventRecord, PublishJobRecord
from cyber_catgirl.services.dashboard import DashboardService


def test_overview_counts_database_records():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions() as session:
        session.add(EventRecord(event_id="comment_1", event_type="new_comment"))
        session.add(
            DraftRecord(
                draft_type="reply",
                content="你好喵",
                risk_level="low",
                review_status="pending",
            )
        )
        session.add(PublishJobRecord(idempotency_key="reply:1", status="failed"))
        session.commit()

    view = DashboardService(sessions).overview()

    assert view.new_comments == 1
    assert view.pending_reviews == 1
    assert view.failed_jobs == 1


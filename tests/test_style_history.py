from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import DraftRecord
from cyber_catgirl.services.style_history import StyleHistoryService


def test_style_history_returns_latest_twenty_matching_drafts():
    sessions = create_session_factory("sqlite+pysqlite:///:memory:")
    with sessions.begin() as session:
        for index in range(25):
            session.add(
                DraftRecord(
                    draft_type="reply",
                    content=f"小伙伴，第{index}条回复喵 (≧▽≦)",
                    risk_level="low",
                    agent_version="catgirl-v2",
                )
            )
        session.add(
            DraftRecord(
                draft_type="dynamic",
                content="动态喵",
                risk_level="medium",
                agent_version="catgirl-v2",
            )
        )

    history = StyleHistoryService(sessions).for_draft_type("reply")

    assert len(history.contents) == 20
    assert history.contents[0].startswith("小伙伴，第24条")
    assert "动态喵" not in history.contents
    assert history.emoticons[0] == "(≧▽≦)"

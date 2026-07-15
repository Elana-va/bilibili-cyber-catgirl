from sqlalchemy import select

from cyber_catgirl.agent.persona import CATGIRL_PROFILE
from cyber_catgirl.agent.persona_validation import RecentStyleHistory
from cyber_catgirl.models import DraftRecord


class StyleHistoryService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def for_draft_type(self, draft_type: str) -> RecentStyleHistory:
        with self.session_factory() as session:
            rows = session.scalars(
                select(DraftRecord)
                .where(DraftRecord.draft_type == draft_type)
                .order_by(DraftRecord.created_at.desc(), DraftRecord.id.desc())
                .limit(20)
            ).all()
        contents = tuple(row.content for row in rows)
        return RecentStyleHistory(
            openings=tuple(content.strip()[:10] for content in contents),
            emoticons=tuple(
                emoticon
                for content in contents
                for emoticon in CATGIRL_PROFILE.emoticons
                if emoticon in content
            ),
            contents=contents,
        )

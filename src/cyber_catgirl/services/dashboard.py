import json
from datetime import date, timedelta

from sqlalchemy import func, select

from cyber_catgirl.models import (
    AuditLogRecord,
    DailyMetricRecord,
    DraftRecord,
    EventRecord,
    PublishJobRecord,
    ScheduledContentRecord,
)
from cyber_catgirl.web.view_models import (
    AnalyticsPoint,
    AnalyticsView,
    ContentPlanItem,
    DashboardOverview,
    LogFilters,
    LogItem,
    ReviewFilters,
    ReviewItem,
)


class DashboardService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def overview(self) -> DashboardOverview:
        with self.session_factory() as session:
            new_comments = session.scalar(
                select(func.count()).select_from(EventRecord).where(
                    EventRecord.event_type == "new_comment"
                )
            ) or 0
            replied = session.scalar(
                select(func.count()).select_from(PublishJobRecord).where(
                    PublishJobRecord.status == "succeeded"
                )
            ) or 0
            pending = session.scalar(
                select(func.count()).select_from(DraftRecord).where(
                    DraftRecord.review_status == "pending"
                )
            ) or 0
            failed = session.scalar(
                select(func.count()).select_from(PublishJobRecord).where(
                    PublishJobRecord.status.in_(["failed", "visibility_unknown"])
                )
            ) or 0
        return DashboardOverview(
            new_comments=new_comments,
            replied_today=replied,
            pending_reviews=pending,
            failed_jobs=failed,
            recent_reviews=self.pending_reviews(ReviewFilters())[:3],
            recent_activity=self.logs(LogFilters())[:4],
        )

    def pending_reviews(self, filters: ReviewFilters) -> list[ReviewItem]:
        statement = select(DraftRecord).where(DraftRecord.review_status == "pending")
        if filters.draft_type:
            statement = statement.where(DraftRecord.draft_type == filters.draft_type)
        if filters.risk_level:
            statement = statement.where(DraftRecord.risk_level == filters.risk_level)
        if filters.query:
            statement = statement.where(DraftRecord.content.contains(filters.query))
        statement = statement.order_by(DraftRecord.created_at.desc())
        with self.session_factory() as session:
            rows = session.scalars(statement).all()
        return [ReviewItem.model_validate(row, from_attributes=True) for row in rows]

    def content_plans(self) -> list[ContentPlanItem]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ScheduledContentRecord).order_by(ScheduledContentRecord.run_at)
            ).all()
        return [ContentPlanItem.model_validate(row, from_attributes=True) for row in rows]

    def analytics(self, days: int = 7) -> AnalyticsView:
        days = 14 if days == 14 else 7
        end = date.today()
        start = end - timedelta(days=days - 1)
        with self.session_factory() as session:
            rows = session.scalars(
                select(DailyMetricRecord).where(DailyMetricRecord.metric_date >= start)
            ).all()
        by_date = {row.metric_date: row for row in rows}
        points: list[AnalyticsPoint] = []
        for offset in range(days):
            metric_date = start + timedelta(days=offset)
            row = by_date.get(metric_date)
            points.append(
                AnalyticsPoint(
                    metric_date=metric_date,
                    unique_users=row.unique_users if row else 0,
                    comment_count=row.comment_count if row else 0,
                    replied_count=row.replied_count if row else 0,
                    review_count=row.review_count if row else 0,
                    failed_count=row.failed_count if row else 0,
                    has_data=row is not None,
                )
            )
        return AnalyticsView(days=days, points=points)

    def logs(self, filters: LogFilters) -> list[LogItem]:
        items: list[LogItem] = []
        with self.session_factory() as session:
            jobs_query = select(PublishJobRecord)
            if filters.status:
                jobs_query = jobs_query.where(PublishJobRecord.status == filters.status)
            jobs = session.scalars(jobs_query).all()
            audits_query = select(AuditLogRecord)
            if filters.action:
                audits_query = audits_query.where(AuditLogRecord.action == filters.action)
            audits = session.scalars(audits_query).all()
        items.extend(
            LogItem(
                kind="publish",
                title=f"发布任务 #{row.id}",
                status=row.status,
                detail=row.platform_id or row.idempotency_key,
                created_at=row.created_at,
            )
            for row in jobs
        )
        for row in audits:
            detail = json.loads(row.details_json)
            items.append(
                LogItem(
                    kind="audit",
                    title=row.action,
                    status="recorded",
                    detail=json.dumps(detail, ensure_ascii=False),
                    created_at=row.created_at,
                )
            )
        return sorted(items, key=lambda item: item.created_at, reverse=True)

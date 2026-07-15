import json
from datetime import date, timedelta

from sqlalchemy import case, func, select

from cyber_catgirl.models import (
    AuditLogRecord,
    DailyMetricRecord,
    DraftRecord,
    EventRecord,
    MonitoredContentRecord,
    PublishJobRecord,
    ScheduledContentRecord,
    SystemSettingRecord,
)
from cyber_catgirl.web.view_models import (
    AnalyticsPoint,
    AnalyticsView,
    ContentPlanItem,
    DashboardOverview,
    LogFilters,
    LogItem,
    MonitorConsoleView,
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
        priority_order = case(
            (EventRecord.priority == "urgent", 0),
            (EventRecord.priority == "high", 1),
            else_=2,
        )
        statement = (
            select(
                DraftRecord,
                PublishJobRecord.status,
                EventRecord,
                MonitoredContentRecord,
            )
            .outerjoin(PublishJobRecord, PublishJobRecord.draft_id == DraftRecord.id)
            .outerjoin(EventRecord, DraftRecord.event_id == EventRecord.id)
            .outerjoin(
                MonitoredContentRecord,
                EventRecord.monitored_content_id == MonitoredContentRecord.id,
            )
            .where(DraftRecord.review_status == "pending")
        )
        if filters.draft_type:
            statement = statement.where(DraftRecord.draft_type == filters.draft_type)
        if filters.risk_level:
            statement = statement.where(DraftRecord.risk_level == filters.risk_level)
        if filters.query:
            statement = statement.where(DraftRecord.content.contains(filters.query))
        statement = statement.order_by(priority_order, DraftRecord.created_at.desc())
        with self.session_factory() as session:
            rows = session.execute(statement).all()
            items = [
                self._review_item(
                    session,
                    draft,
                    publication_status,
                    event_row,
                    source,
                )
                for draft, publication_status, event_row, source in rows
            ]
        return items

    def monitor_console(self, enabled: bool) -> MonitorConsoleView:
        with self.session_factory() as session:
            content_count = session.scalar(
                select(func.count()).select_from(MonitoredContentRecord)
            ) or 0
            new_comments = session.scalar(
                select(func.count())
                .select_from(EventRecord)
                .where(EventRecord.status == "new")
            ) or 0
            failed = session.scalar(
                select(func.count())
                .select_from(EventRecord)
                .where(EventRecord.status == "generation_failed")
            ) or 0
            last_polled = session.scalar(
                select(func.max(MonitoredContentRecord.last_polled_at))
            )
            next_poll = session.scalar(
                select(func.min(MonitoredContentRecord.next_poll_at)).where(
                    MonitoredContentRecord.next_poll_at.is_not(None)
                )
            )
            settings = {
                row.setting_key: row.setting_value
                for row in session.scalars(select(SystemSettingRecord)).all()
            }
        return MonitorConsoleView(
            enabled=enabled,
            content_count=content_count,
            new_comments=new_comments,
            failed_events=failed,
            backfill_imported=int(settings.get("comment_backfill_imported", "0")),
            backfill_limit=int(settings.get("comment_backfill_limit", "500")),
            backfill_complete=settings.get("comment_backfill_complete") == "true",
            last_polled_at=last_polled,
            next_poll_at=next_poll,
            error_code=settings.get("comment_monitor_error_code"),
        )

    def _review_item(
        self, session, draft, publication_status, event_row, source
    ) -> ReviewItem:
        event = None
        if event_row is not None:
            try:
                from cyber_catgirl.schemas import InteractionEvent

                event = InteractionEvent.model_validate_json(event_row.payload_json)
            except (ValueError, TypeError):
                event = None
        return ReviewItem(
            id=draft.id,
            draft_type=draft.draft_type,
            content=draft.content,
            risk_level=draft.risk_level,
            review_status=draft.review_status,
            priority=event_row.priority if event_row else "normal",
            source_comment=event.content if event else None,
            actor_name=event.actor_name if event else None,
            source_title=source.title if source else None,
            source_url=self._source_url(source),
            thread_context=self._thread_context(session, event_row, event),
            safety_reasons=json.loads(draft.safety_reasons_json or "[]"),
            created_at=draft.created_at,
            publication_status=publication_status,
        )

    @staticmethod
    def _source_url(source) -> str | None:
        if source is None:
            return None
        if source.display_type == "video":
            return f"https://www.bilibili.com/video/av{source.comment_oid}"
        if source.platform_content_id.startswith("dynamic:"):
            return "https://t.bilibili.com/" + source.platform_content_id.split(":", 1)[1]
        return None

    @staticmethod
    def _thread_context(session, current_row, current_event) -> list[str]:
        if current_row is None or current_event is None:
            return []
        rows = session.scalars(
            select(EventRecord)
            .where(EventRecord.monitored_content_id == current_row.monitored_content_id)
            .where(EventRecord.id != current_row.id)
            .order_by(EventRecord.created_at.desc())
            .limit(20)
        ).all()
        context: list[str] = []
        from cyber_catgirl.schemas import InteractionEvent

        current_root = current_event.root_comment_id or current_event.event_id
        for row in rows:
            try:
                event = InteractionEvent.model_validate_json(row.payload_json)
            except (ValueError, TypeError):
                continue
            event_root = event.root_comment_id or event.event_id
            if event_root == current_root:
                context.append(f"{event.actor_name}：{event.content}")
        return list(reversed(context[-5:]))

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

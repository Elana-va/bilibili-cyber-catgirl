from datetime import date, datetime

from pydantic import BaseModel, Field


class ReviewFilters(BaseModel):
    draft_type: str | None = None
    risk_level: str | None = None
    query: str = ""


class ReviewItem(BaseModel):
    id: int
    draft_type: str
    content: str
    risk_level: str
    review_status: str
    priority: str = "normal"
    source_comment: str | None = None
    actor_name: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    thread_context: list[str] = Field(default_factory=list)
    safety_reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    publication_status: str | None = None


class ContentPlanItem(BaseModel):
    id: int
    schedule_key: str
    prompt: str
    category: str
    run_at: datetime
    enabled: bool


class AnalyticsPoint(BaseModel):
    metric_date: date
    unique_users: int
    comment_count: int
    replied_count: int
    review_count: int
    failed_count: int
    has_data: bool = True


class AnalyticsView(BaseModel):
    days: int
    points: list[AnalyticsPoint] = Field(default_factory=list)


class LogFilters(BaseModel):
    status: str | None = None
    action: str | None = None


class LogItem(BaseModel):
    kind: str
    title: str
    status: str
    detail: str
    created_at: datetime


class DashboardOverview(BaseModel):
    new_comments: int = 0
    replied_today: int = 0
    pending_reviews: int = 0
    failed_jobs: int = 0
    recent_reviews: list[ReviewItem] = Field(default_factory=list)
    recent_activity: list[LogItem] = Field(default_factory=list)


class MonitorConsoleView(BaseModel):
    enabled: bool = False
    content_count: int = 0
    new_comments: int = 0
    failed_events: int = 0
    backfill_imported: int = 0
    backfill_limit: int = 500
    backfill_complete: bool = False
    last_polled_at: datetime | None = None
    next_poll_at: datetime | None = None
    error_code: str | None = None

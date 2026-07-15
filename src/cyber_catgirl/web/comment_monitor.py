from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from cyber_catgirl.config import RunMode
from cyber_catgirl.models import (
    DraftRecord,
    EventRecord,
    MonitoredContentRecord,
    SystemSettingRecord,
)
from cyber_catgirl.services.audit import AuditService


class AutoReplySettingsRequest(BaseModel):
    enabled: bool
    user_daily_limit: int = Field(ge=1, le=100)
    account_hourly_limit: int = Field(ge=1, le=500)
    account_daily_limit: int = Field(ge=1, le=5000)
    min_delay_seconds: int = Field(ge=1, le=600)
    max_delay_seconds: int = Field(ge=1, le=1800)

    @model_validator(mode="after")
    def delay_order(self):
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("最大延迟必须大于或等于最小延迟")
        return self


def build_comment_monitor_router(session_factory, state, runtime) -> APIRouter:
    router = APIRouter()
    audit = AuditService(session_factory)

    def save_settings(values: dict[str, str]) -> None:
        with session_factory.begin() as session:
            for key, value in values.items():
                row = session.scalar(
                    select(SystemSettingRecord).where(
                        SystemSettingRecord.setting_key == key
                    )
                )
                if row is None:
                    session.add(
                        SystemSettingRecord(setting_key=key, setting_value=value)
                    )
                else:
                    row.setting_value = value

    @router.get("/api/comment-monitor/status")
    def monitor_status() -> dict:
        with session_factory() as session:
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
            settings_rows = session.scalars(select(SystemSettingRecord)).all()
        stored = {row.setting_key: row.setting_value for row in settings_rows}
        return {
            "enabled": state.settings.comment_monitor_enabled,
            "sync_running": bool(
                getattr(runtime, "_manual_pending", False)
                or getattr(getattr(runtime, "_cycle_lock", None), "locked", lambda: False)()
            ),
            "content_count": content_count,
            "new_comments": new_comments,
            "failed_events": failed,
            "backfill_imported": int(stored.get("comment_backfill_imported", "0")),
            "backfill_limit": state.settings.comment_backfill_limit,
            "backfill_complete": stored.get("comment_backfill_complete") == "true",
            "error_code": stored.get("comment_monitor_error_code"),
        }

    @router.post("/api/comment-monitor/start")
    def start_monitor() -> dict:
        state.settings.comment_monitor_enabled = True
        runtime.settings.comment_monitor_enabled = True
        save_settings({"comment_monitor_enabled": "true"})
        audit.record("comment_monitor_started", "comment-monitor", {"enabled": True})
        return {"enabled": True}

    @router.post("/api/comment-monitor/stop")
    def stop_monitor() -> dict:
        state.settings.comment_monitor_enabled = False
        runtime.settings.comment_monitor_enabled = False
        save_settings({"comment_monitor_enabled": "false"})
        audit.record("comment_monitor_stopped", "comment-monitor", {"enabled": False})
        return {"enabled": False}

    @router.post("/api/comment-monitor/sync", status_code=202)
    async def sync_now() -> dict:
        if not runtime.request_manual_cycle():
            raise HTTPException(status_code=409, detail="同步任务正在运行")
        audit.record("comment_monitor_sync_requested", "comment-monitor", {})
        return {"status": "accepted"}

    @router.get("/api/reply-drafts")
    def reply_drafts() -> list[dict]:
        with session_factory() as session:
            rows = session.execute(
                select(DraftRecord, EventRecord)
                .join(EventRecord, DraftRecord.event_id == EventRecord.id)
                .where(DraftRecord.draft_type == "reply")
                .order_by(DraftRecord.created_at.desc())
            ).all()
        return [
            {
                "id": draft.id,
                "content": draft.content,
                "risk_level": draft.risk_level,
                "review_status": draft.review_status,
                "priority": event.priority,
                "event_id": event.event_id,
                "created_at": draft.created_at,
            }
            for draft, event in rows
        ]

    @router.post("/api/reply-drafts/{draft_id}/regenerate")
    async def regenerate(draft_id: int) -> dict:
        with session_factory.begin() as session:
            draft = session.get(DraftRecord, draft_id)
            if draft is None or draft.draft_type != "reply":
                raise HTTPException(status_code=404, detail="reply draft not found")
            if draft.review_status != "pending" or draft.event_id is None:
                raise HTTPException(status_code=409, detail="draft cannot be regenerated")
            event = session.get(EventRecord, draft.event_id)
            if event is None:
                raise HTTPException(status_code=409, detail="source event is missing")
            event_id = event.event_id
            event.status = "new"
            session.delete(draft)
        service = getattr(runtime, "reply_service", None)
        if service is None:
            raise HTTPException(status_code=503, detail="reply generator unavailable")
        regenerated = await service.process_event(event_id)
        audit.record(
            "reply_draft_regenerated",
            str(draft_id),
            {"event_id": event_id, "new_draft_id": getattr(regenerated, "id", None)},
        )
        return {"draft_id": getattr(regenerated, "id", None), "status": "regenerated"}

    @router.get("/api/auto-reply/settings")
    def auto_reply_settings() -> dict:
        return _auto_reply_view(state.settings)

    @router.patch("/api/auto-reply/settings")
    def update_auto_reply_settings(payload: AutoReplySettingsRequest) -> dict:
        if payload.enabled and state.settings.run_mode is not RunMode.LIMITED_AUTO:
            raise HTTPException(status_code=409, detail="有限自动模式未开启")
        if payload.enabled and not state.settings.bilibili_write_enabled:
            raise HTTPException(status_code=409, detail="B站真实写入未授权")
        values = {
            "comment_auto_reply_enabled": str(payload.enabled).lower(),
            "auto_reply_user_daily_limit": str(payload.user_daily_limit),
            "auto_reply_account_hourly_limit": str(payload.account_hourly_limit),
            "auto_reply_account_daily_limit": str(payload.account_daily_limit),
            "auto_reply_min_delay_seconds": str(payload.min_delay_seconds),
            "auto_reply_max_delay_seconds": str(payload.max_delay_seconds),
        }
        save_settings(values)
        state.settings.comment_auto_reply_enabled = payload.enabled
        state.settings.auto_reply_user_daily_limit = payload.user_daily_limit
        state.settings.auto_reply_account_hourly_limit = payload.account_hourly_limit
        state.settings.auto_reply_account_daily_limit = payload.account_daily_limit
        state.settings.auto_reply_min_delay_seconds = payload.min_delay_seconds
        state.settings.auto_reply_max_delay_seconds = payload.max_delay_seconds
        _apply_runtime_settings(runtime, state.settings)
        audit.record(
            "auto_reply_settings_changed",
            "auto-reply",
            {
                "enabled": payload.enabled,
                "user_daily_limit": payload.user_daily_limit,
                "account_hourly_limit": payload.account_hourly_limit,
                "account_daily_limit": payload.account_daily_limit,
                "min_delay_seconds": payload.min_delay_seconds,
                "max_delay_seconds": payload.max_delay_seconds,
            },
        )
        return _auto_reply_view(state.settings)

    return router


def _auto_reply_view(settings) -> dict:
    return {
        "enabled": settings.comment_auto_reply_enabled,
        "user_daily_limit": settings.auto_reply_user_daily_limit,
        "account_hourly_limit": settings.auto_reply_account_hourly_limit,
        "account_daily_limit": settings.auto_reply_account_daily_limit,
        "min_delay_seconds": settings.auto_reply_min_delay_seconds,
        "max_delay_seconds": settings.auto_reply_max_delay_seconds,
        "write_enabled": settings.bilibili_write_enabled,
        "run_mode": settings.run_mode.value,
    }


def _apply_runtime_settings(runtime, settings) -> None:
    if hasattr(runtime, "apply_settings"):
        runtime.apply_settings(settings)
        return
    runtime.settings = settings
    reply_service = getattr(runtime, "reply_service", None)
    if reply_service is None:
        return
    reply_service.min_delay_seconds = settings.auto_reply_min_delay_seconds
    reply_service.max_delay_seconds = settings.auto_reply_max_delay_seconds
    safety = reply_service.safety_engine
    safety.run_mode = settings.run_mode
    safety.kill_switch = settings.kill_switch
    safety.comment_auto_reply_enabled = settings.comment_auto_reply_enabled
    safety.write_enabled = settings.bilibili_write_enabled
    safety.min_reply_interval_seconds = settings.auto_reply_min_delay_seconds
    safety.user_daily_limit = settings.auto_reply_user_daily_limit
    safety.account_hourly_limit = settings.auto_reply_account_hourly_limit
    safety.account_daily_limit = settings.auto_reply_account_daily_limit

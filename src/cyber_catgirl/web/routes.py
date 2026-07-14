from dataclasses import dataclass
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from cyber_catgirl.config import RunMode, Settings
from cyber_catgirl.models import DraftRecord, PublishJobRecord, SystemSettingRecord
from cyber_catgirl.web.pages import build_page_router


@dataclass
class RuntimeState:
    settings: Settings


class KillSwitchRequest(BaseModel):
    enabled: bool


class RunModeRequest(BaseModel):
    run_mode: RunMode


class EditDraftRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


def build_router(session_factory, state: RuntimeState) -> APIRouter:
    router = APIRouter()
    router.include_router(build_page_router(session_factory, state))

    def save_setting(key: str, value: str) -> None:
        with session_factory() as session:
            row = session.scalar(
                select(SystemSettingRecord).where(SystemSettingRecord.setting_key == key)
            )
            if row is None:
                row = SystemSettingRecord(setting_key=key, setting_value=value)
                session.add(row)
            else:
                row.setting_value = value
            session.commit()

    def approve(draft_id: int, edited_content: str | None = None) -> dict:
        if state.settings.kill_switch:
            raise HTTPException(status_code=409, detail="kill switch is enabled")
        with session_factory() as session:
            draft = session.get(DraftRecord, draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="draft not found")
            if draft.review_status != "pending":
                raise HTTPException(status_code=409, detail="draft is not pending")
            if edited_content is not None:
                draft.content = edited_content
            job = PublishJobRecord(
                draft_id=draft.id,
                idempotency_key=f"manual:{draft.draft_type}:{draft.id}",
                status="pending",
            )
            session.add(job)
            draft.review_status = "approved"
            session.commit()
            return {"draft_id": draft.id, "job_id": job.id, "status": "approved"}

    @router.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "run_mode": state.settings.run_mode.value,
            "kill_switch": state.settings.kill_switch,
        }

    @router.post("/api/system/kill-switch")
    def set_kill_switch(payload: KillSwitchRequest) -> dict:
        state.settings.kill_switch = payload.enabled
        save_setting("kill_switch", str(payload.enabled).lower())
        if payload.enabled:
            with session_factory() as session:
                jobs = session.scalars(
                    select(PublishJobRecord).where(PublishJobRecord.status == "pending")
                ).all()
                for job in jobs:
                    job.status = "cancelled"
                session.commit()
        return {"kill_switch": state.settings.kill_switch}

    @router.post("/api/system/run-mode")
    def set_run_mode(payload: RunModeRequest) -> dict:
        state.settings.run_mode = payload.run_mode
        save_setting("run_mode", payload.run_mode.value)
        return {"run_mode": state.settings.run_mode.value}

    @router.post("/api/drafts/{draft_id}/approve")
    def approve_draft(draft_id: int) -> dict:
        return approve(draft_id)

    @router.post("/api/drafts/{draft_id}/edit-and-approve")
    def edit_and_approve_draft(draft_id: int, payload: EditDraftRequest) -> dict:
        return approve(draft_id, payload.content)

    @router.post("/api/drafts/{draft_id}/reject")
    def reject_draft(draft_id: int) -> dict:
        with session_factory() as session:
            draft = session.get(DraftRecord, draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="draft not found")
            if draft.review_status != "pending":
                raise HTTPException(status_code=409, detail="draft is not pending")
            draft.review_status = "rejected"
            session.commit()
            return {"draft_id": draft.id, "status": "rejected"}

    return router

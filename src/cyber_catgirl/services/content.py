import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from cyber_catgirl.agent.persona_validation import PersonaValidator
from cyber_catgirl.agent.prompts import build_persona_system_prompt
from cyber_catgirl.models import DailyMetricRecord, DraftRecord, ScheduledContentRecord
from cyber_catgirl.schemas import AddressMode, PersonaScene
from cyber_catgirl.services.style_history import StyleHistoryService


class GeneratedContent(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    scene: PersonaScene
    address: AddressMode
    emoticon: str = Field(default="", max_length=32)


@dataclass(frozen=True)
class ContentDraft:
    id: int
    content: str
    review_status: str
    stats_snapshot: dict[str, int]


class SchedulePolicy:
    def may_publish(self, *, hour: int, category: str) -> bool:
        if category == "normal" and (hour >= 23 or hour < 8):
            return False
        return True


class ContentService:
    def __init__(self, session_factory, llm, style_history=None, validator=None) -> None:
        self.session_factory = session_factory
        self.llm = llm
        self.style_history = style_history or StyleHistoryService(session_factory)
        self.validator = validator or PersonaValidator()

    async def create_daily_report(self, metric_date: date) -> ContentDraft:
        content_key = f"daily-report:{metric_date.isoformat()}"
        with self.session_factory() as session:
            existing = session.scalar(
                select(DraftRecord).where(DraftRecord.content_key == content_key)
            )
            if existing is not None:
                return self._to_result(existing)
            metrics = session.scalar(
                select(DailyMetricRecord).where(DailyMetricRecord.metric_date == metric_date)
            )
            if metrics is None:
                raise LookupError(f"daily metrics not found: {metric_date.isoformat()}")
            snapshot = self._snapshot(metrics)

        generated, persona_reasons = await self._generate_persona_content(
            task=(
                "根据给定统计写简短B站互动日报；"
                "不得添加统计中不存在的数字；只输出JSON对象"
            ),
            draft_type="daily_report",
            user_payload=json.dumps(snapshot, ensure_ascii=False),
            scene=PersonaScene.QA,
            long_form=True,
        )
        grounded = self._numbers_are_grounded(generated.content, snapshot)
        review_status = (
            "pending" if grounded and not persona_reasons else "validation_failed"
        )

        with self.session_factory() as session:
            row = DraftRecord(
                content_key=content_key,
                draft_type="daily_report",
                content=generated.content,
                risk_level="medium",
                review_status=review_status,
                agent_version="catgirl-v2",
                stats_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                safety_reasons_json=json.dumps(persona_reasons, ensure_ascii=False),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_result(row)

    async def create_scheduled_draft(
        self, schedule_id: int, now: datetime
    ) -> ContentDraft:
        with self.session_factory() as session:
            schedule = session.get(ScheduledContentRecord, schedule_id)
            if schedule is None or not schedule.enabled:
                raise LookupError(f"active schedule not found: {schedule_id}")
            if schedule.run_at > now:
                raise ValueError("schedule is not due")
            content_key = f"schedule:{schedule.schedule_key}:{schedule.run_at.isoformat()}"
            existing = session.scalar(
                select(DraftRecord).where(DraftRecord.content_key == content_key)
            )
            if existing is not None:
                return self._to_result(existing)
            prompt = schedule.prompt

        generated, persona_reasons = await self._generate_persona_content(
            task="根据创作要求生成B站动态草稿，只输出JSON对象",
            draft_type="dynamic",
            user_payload=prompt,
            scene=PersonaScene.CASUAL,
            long_form=True,
        )
        with self.session_factory() as session:
            row = DraftRecord(
                content_key=content_key,
                draft_type="dynamic",
                content=generated.content,
                risk_level="medium",
                review_status=(
                    "pending" if not persona_reasons else "validation_failed"
                ),
                agent_version="catgirl-v2",
                safety_reasons_json=json.dumps(persona_reasons, ensure_ascii=False),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_result(row)

    async def _generate_persona_content(
        self,
        *,
        task: str,
        draft_type: str,
        user_payload: str,
        scene: PersonaScene,
        long_form: bool,
    ) -> tuple[GeneratedContent, tuple[str, ...]]:
        history = self.style_history.for_draft_type(draft_type)
        reasons: tuple[str, ...] = ()
        generated: GeneratedContent | None = None
        for _ in range(2):
            prompt = build_persona_system_prompt(
                task=task,
                scene=scene,
                history_hint=history.prompt_hint(),
                correction_reasons=reasons,
            )
            raw = await self.llm.generate_json(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_payload},
                ],
                GeneratedContent.model_json_schema(),
            )
            generated = GeneratedContent.model_validate(raw)
            result = self.validator.validate_text(
                generated.content,
                scene=scene,
                address=generated.address,
                emoticon=generated.emoticon,
                history=history,
                long_form=long_form,
            )
            reasons = result.reasons
            if generated.scene is not scene:
                reasons = (*reasons, "persona_scene_mismatch")
            reasons = tuple(dict.fromkeys(reasons))
            if not reasons:
                return generated, ()
            if result.hard_block:
                break
        if generated is None:
            raise RuntimeError("persona_generation_missing")
        return generated, reasons

    @staticmethod
    def _snapshot(metrics: DailyMetricRecord) -> dict[str, int]:
        return {
            "unique_users": metrics.unique_users,
            "comment_count": metrics.comment_count,
            "replied_count": metrics.replied_count,
            "review_count": metrics.review_count,
            "failed_count": metrics.failed_count,
        }

    @staticmethod
    def _numbers_are_grounded(content: str, snapshot: dict[str, int]) -> bool:
        allowed = {str(value) for value in snapshot.values()}
        return set(re.findall(r"\d+", content)).issubset(allowed)

    @staticmethod
    def _to_result(row: DraftRecord) -> ContentDraft:
        return ContentDraft(
            id=row.id,
            content=row.content,
            review_status=row.review_status,
            stats_snapshot=json.loads(row.stats_snapshot_json),
        )

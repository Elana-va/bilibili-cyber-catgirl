import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from cyber_catgirl.models import DailyMetricRecord, DraftRecord, ScheduledContentRecord


class GeneratedContent(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


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
    def __init__(self, session_factory, llm) -> None:
        self.session_factory = session_factory
        self.llm = llm

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

        messages = [
            {
                "role": "system",
                "content": (
                    "你是赛博猫娘小喵。根据给定统计写一条简短互动日报；"
                    "不得添加统计中不存在的数字，只输出JSON对象。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(snapshot, ensure_ascii=False),
            },
        ]
        raw = await self.llm.generate_json(messages, GeneratedContent.model_json_schema())
        generated = GeneratedContent.model_validate(raw)
        review_status = (
            "pending" if self._numbers_are_grounded(generated.content, snapshot) else "validation_failed"
        )

        with self.session_factory() as session:
            row = DraftRecord(
                content_key=content_key,
                draft_type="daily_report",
                content=generated.content,
                risk_level="medium",
                review_status=review_status,
                stats_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
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

        raw = await self.llm.generate_json(
            [
                {"role": "system", "content": "生成赛博猫娘B站动态，只输出JSON对象。"},
                {"role": "user", "content": prompt},
            ],
            GeneratedContent.model_json_schema(),
        )
        generated = GeneratedContent.model_validate(raw)
        with self.session_factory() as session:
            row = DraftRecord(
                content_key=content_key,
                draft_type="dynamic",
                content=generated.content,
                risk_level="medium",
                review_status="pending",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_result(row)

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

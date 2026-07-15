import json

from pydantic import ValidationError
from sqlalchemy import select

from cyber_catgirl.config import Settings
from cyber_catgirl.models import AuditLogRecord, SystemSettingRecord


PERSISTED_SETTING_KEYS = frozenset(
    {
        "run_mode",
        "kill_switch",
        "poll_seconds",
        "auto_reply_allowlist",
        "comment_monitor_enabled",
        "comment_auto_reply_enabled",
        "comment_backfill_days",
        "comment_backfill_limit",
        "auto_reply_user_daily_limit",
        "auto_reply_account_hourly_limit",
        "auto_reply_account_daily_limit",
        "auto_reply_min_delay_seconds",
        "auto_reply_max_delay_seconds",
    }
)


def load_runtime_settings(session_factory, base: Settings) -> Settings:
    values = base.model_dump()
    with session_factory.begin() as session:
        rows = session.scalars(
            select(SystemSettingRecord).where(
                SystemSettingRecord.setting_key.in_(PERSISTED_SETTING_KEYS)
            )
        ).all()
        for row in rows:
            candidate = dict(values)
            candidate[row.setting_key] = _normalize(row.setting_key, row.setting_value)
            try:
                validated = Settings.model_validate(candidate)
            except ValidationError as exc:
                session.add(
                    AuditLogRecord(
                        action="runtime_setting_rejected",
                        entity_id=row.setting_key,
                        details_json=json.dumps(
                            {"error": exc.errors(include_input=False)[0]["type"]},
                            separators=(",", ":"),
                        ),
                    )
                )
                continue
            values = validated.model_dump()
    return Settings.model_validate(values)


def _normalize(key: str, value: str):
    if key == "auto_reply_allowlist":
        return {item.strip() for item in value.split(",") if item.strip()}
    return value


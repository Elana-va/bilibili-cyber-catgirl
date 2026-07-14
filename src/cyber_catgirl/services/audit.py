import json
from collections.abc import Mapping
from typing import Any

from cyber_catgirl.models import AuditLogRecord


SENSITIVE_KEYS = {"cookie", "sessdata", "bili_jct", "authorization"}


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


class AuditService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def record(self, action: str, entity_id: str, details: dict[str, Any]) -> None:
        safe_details = redact(details)
        with self.session_factory() as session:
            session.add(
                AuditLogRecord(
                    action=action,
                    entity_id=entity_id,
                    details_json=json.dumps(safe_details, ensure_ascii=False, default=str),
                )
            )
            session.commit()

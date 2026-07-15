from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActionType(StrEnum):
    REPLY = "reply"
    DRAFT_DYNAMIC = "draft_dynamic"
    IGNORE = "ignore"
    ESCALATE = "escalate"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PersonaScene(StrEnum):
    GREETING = "greeting"
    PRAISE = "praise"
    CASUAL = "casual"
    JOKE = "joke"
    QA = "qa"
    TECHNICAL = "technical"
    CORRECTION = "correction"
    IDENTITY = "identity"
    SERIOUS = "serious"
    SAFETY = "safety"
    UNKNOWN = "unknown"


class AddressMode(StrEnum):
    NONE = "none"
    PARTNER = "partner"
    MASTER = "master"


class InteractionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=3, max_length=128)
    event_type: str = Field(min_length=3, max_length=64)
    actor_id: str = Field(min_length=1, max_length=64)
    actor_name: str = Field(max_length=128)
    content: str = Field(max_length=5000)
    target_type: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=128)
    root_comment_id: str | None = Field(default=None, max_length=128)
    parent_comment_id: str | None = Field(default=None, max_length=128)
    platform_created_at: datetime


class PlatformContentTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_content_id: str = Field(min_length=1, max_length=128)
    display_type: Literal["video", "dynamic_text", "dynamic_draw"]
    comment_oid: str = Field(min_length=1, max_length=128)
    resource_type: Literal["video", "article", "dynamic", "dynamic_draw"]
    title: str = Field(default="", max_length=256)
    published_at: datetime


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionType
    content: str = Field(max_length=500)
    risk_level: RiskLevel
    reason: str = Field(min_length=1, max_length=500)
    memory_updates: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    scene: PersonaScene
    address: AddressMode
    emoticon: str = Field(default="", max_length=32)

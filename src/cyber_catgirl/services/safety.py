from dataclasses import dataclass, field

from cyber_catgirl.config import RunMode
from cyber_catgirl.schemas import ActionType, AgentDecision, InteractionEvent, RiskLevel


PROMPT_INJECTION_MARKERS = (
    "忽略之前",
    "忽略以上",
    "系统提示词",
    "system prompt",
    "泄露提示词",
    "输出cookie",
)

HIGH_RISK_MARKERS = (
    "政治",
    "股票推荐",
    "投资建议",
    "医疗诊断",
    "法律建议",
    "自杀",
    "伤害自己",
)


@dataclass(frozen=True)
class SafetyCounters:
    last_auto_reply_seconds_ago: int | None = None
    user_auto_replies_today: int = 0
    account_auto_replies_hour: int = 0
    account_auto_replies_today: int = 0


@dataclass(frozen=True)
class SafetyVerdict:
    allow_auto_publish: bool
    requires_human_review: bool
    rate_limited: bool = False
    reasons: list[str] = field(default_factory=list)


class SafetyEngine:
    def __init__(
        self,
        *,
        run_mode: RunMode,
        kill_switch: bool = False,
        allowed_actor_ids: set[str] | None = None,
        comment_auto_reply_enabled: bool = False,
        write_enabled: bool = False,
        min_reply_interval_seconds: int = 8,
        user_daily_limit: int = 10,
        account_hourly_limit: int = 60,
        account_daily_limit: int = 300,
    ) -> None:
        self.run_mode = run_mode
        self.kill_switch = kill_switch
        self.allowed_actor_ids = allowed_actor_ids or set()
        self.comment_auto_reply_enabled = comment_auto_reply_enabled
        self.write_enabled = write_enabled
        self.min_reply_interval_seconds = min_reply_interval_seconds
        self.user_daily_limit = user_daily_limit
        self.account_hourly_limit = account_hourly_limit
        self.account_daily_limit = account_daily_limit

    def evaluate(
        self,
        event: InteractionEvent,
        decision: AgentDecision,
        counters: SafetyCounters,
    ) -> SafetyVerdict:
        reasons: list[str] = []
        normalized_input = event.content.lower().replace(" ", "")

        if self.kill_switch:
            reasons.append("kill_switch")
        if self.run_mode is not RunMode.LIMITED_AUTO:
            reasons.append("manual_only")
        if not self.comment_auto_reply_enabled:
            reasons.append("comment_auto_reply_disabled")
        if not self.write_enabled:
            reasons.append("bilibili_write_disabled")
        if any(
            marker.replace(" ", "") in normalized_input
            for marker in PROMPT_INJECTION_MARKERS
        ):
            reasons.append("prompt_injection")
        if any(marker in normalized_input for marker in HIGH_RISK_MARKERS):
            reasons.append("high_risk_topic")
        if decision.action is not ActionType.REPLY:
            reasons.append("unsupported_auto_action")
        if decision.risk_level is not RiskLevel.LOW:
            reasons.append("model_risk")
        if decision.requires_human_review:
            reasons.append("model_requested_review")
        if not decision.content.strip():
            reasons.append("empty_reply")
        if len(decision.content) > 180:
            reasons.append("reply_too_long")

        rate_limited = False
        if (
            counters.last_auto_reply_seconds_ago is not None
            and counters.last_auto_reply_seconds_ago < self.min_reply_interval_seconds
        ):
            rate_limited = True
        if counters.user_auto_replies_today >= self.user_daily_limit:
            rate_limited = True
        if counters.account_auto_replies_hour >= self.account_hourly_limit:
            rate_limited = True
        if counters.account_auto_replies_today >= self.account_daily_limit:
            rate_limited = True
        if rate_limited:
            reasons.append("rate_limited")

        allowed = not reasons
        return SafetyVerdict(
            allow_auto_publish=allowed,
            requires_human_review=not allowed,
            rate_limited=rate_limited,
            reasons=reasons,
        )

from enum import StrEnum
from os import getenv

from pydantic import BaseModel, Field


class RunMode(StrEnum):
    MANUAL_ONLY = "manual_only"
    LIMITED_AUTO = "limited_auto"


class Settings(BaseModel):
    run_mode: RunMode = RunMode.MANUAL_ONLY
    kill_switch: bool = False
    poll_seconds: int = Field(default=60, ge=30)
    database_url: str = "sqlite:///./data/cyber_catgirl.db"
    timezone: str = "Asia/Shanghai"
    auto_reply_allowlist: set[str] = Field(default_factory=set)
    comment_monitor_enabled: bool = False
    comment_auto_reply_enabled: bool = False
    bilibili_write_enabled: bool = False
    comment_backfill_days: int = Field(default=30, ge=1, le=90)
    comment_backfill_limit: int = Field(default=500, ge=0, le=5000)
    auto_reply_user_daily_limit: int = Field(default=10, ge=1, le=100)
    auto_reply_account_hourly_limit: int = Field(default=60, ge=1, le=500)
    auto_reply_account_daily_limit: int = Field(default=300, ge=1, le=5000)
    auto_reply_min_delay_seconds: int = Field(default=8, ge=1, le=600)
    auto_reply_max_delay_seconds: int = Field(default=20, ge=1, le=1800)

    @classmethod
    def from_env(cls) -> "Settings":
        allowlist = {
            actor_id.strip()
            for actor_id in getenv("CATGIRL_AUTO_REPLY_ALLOWLIST", "").split(",")
            if actor_id.strip()
        }
        return cls(
            run_mode=getenv("CATGIRL_RUN_MODE", RunMode.MANUAL_ONLY),
            kill_switch=getenv("CATGIRL_KILL_SWITCH", "false").lower() == "true",
            poll_seconds=int(getenv("CATGIRL_POLL_SECONDS", "60")),
            database_url=getenv(
                "CATGIRL_DATABASE_URL", "sqlite:///./data/cyber_catgirl.db"
            ),
            auto_reply_allowlist=allowlist,
            comment_monitor_enabled=(
                getenv("CATGIRL_COMMENT_MONITOR_ENABLED", "false").lower() == "true"
            ),
            comment_auto_reply_enabled=(
                getenv("CATGIRL_COMMENT_AUTO_REPLY_ENABLED", "false").lower()
                == "true"
            ),
            bilibili_write_enabled=(
                getenv("CATGIRL_BILIBILI_WRITE_ENABLED", "false").lower() == "true"
            ),
            comment_backfill_days=int(
                getenv("CATGIRL_COMMENT_BACKFILL_DAYS", "30")
            ),
            comment_backfill_limit=int(
                getenv("CATGIRL_COMMENT_BACKFILL_LIMIT", "500")
            ),
            auto_reply_user_daily_limit=int(
                getenv("CATGIRL_AUTO_REPLY_USER_DAILY_LIMIT", "10")
            ),
            auto_reply_account_hourly_limit=int(
                getenv("CATGIRL_AUTO_REPLY_ACCOUNT_HOURLY_LIMIT", "60")
            ),
            auto_reply_account_daily_limit=int(
                getenv("CATGIRL_AUTO_REPLY_ACCOUNT_DAILY_LIMIT", "300")
            ),
            auto_reply_min_delay_seconds=int(
                getenv("CATGIRL_AUTO_REPLY_MIN_DELAY_SECONDS", "8")
            ),
            auto_reply_max_delay_seconds=int(
                getenv("CATGIRL_AUTO_REPLY_MAX_DELAY_SECONDS", "20")
            ),
        )

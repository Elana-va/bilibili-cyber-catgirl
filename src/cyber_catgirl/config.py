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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            run_mode=getenv("CATGIRL_RUN_MODE", RunMode.MANUAL_ONLY),
            kill_switch=getenv("CATGIRL_KILL_SWITCH", "false").lower() == "true",
            poll_seconds=int(getenv("CATGIRL_POLL_SECONDS", "60")),
            database_url=getenv(
                "CATGIRL_DATABASE_URL", "sqlite:///./data/cyber_catgirl.db"
            ),
        )

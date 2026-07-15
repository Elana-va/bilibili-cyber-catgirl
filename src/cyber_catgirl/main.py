from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from os import getenv
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from cyber_catgirl.config import Settings
from cyber_catgirl.connectors.bilibili_login import (
    BilibiliLoginManager,
    BilibiliQrSdkAdapter,
)
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.models import (
    AuditLogRecord,
    PublishJobRecord,
    SystemSettingRecord,
)
from cyber_catgirl.security.credential_store import (
    CredentialStore,
    DeepSeekCredentialStore,
    DpapiProtector,
)
from cyber_catgirl.services.bilibili_account import (
    BilibiliAccountService,
    BilibiliIdentityProbe,
)
from cyber_catgirl.services.deepseek_connection import (
    DEFAULT_MODEL,
    DeepSeekConnectionService,
    DeepSeekModelsProbe,
)
from cyber_catgirl.services.runtime_settings import load_runtime_settings
from cyber_catgirl.services.scheduler import build_scheduler
from cyber_catgirl.web.routes import RuntimeState, build_router


def create_app(
    settings: Settings | None = None,
    *,
    session_factory=None,
    credential_store=None,
    login_manager=None,
    account_service=None,
    deepseek_service=None,
    monitor_runtime=None,
    scheduler_factory=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if session_factory is None:
        Path("data").mkdir(exist_ok=True)
        session_factory = create_session_factory(settings.database_url)
    settings = load_runtime_settings(session_factory, settings)

    if credential_store is None:
        credential_store = CredentialStore(
            Path("data/secrets/bilibili-credential.bin"), DpapiProtector()
        )
    if login_manager is None:
        login_manager = BilibiliLoginManager(credential_store, BilibiliQrSdkAdapter)
    if account_service is None:
        account_service = BilibiliAccountService(
            credential_store, BilibiliIdentityProbe()
        )

    deepseek_store = DeepSeekCredentialStore(
        Path("data/secrets/deepseek-credential.bin"), DpapiProtector()
    )
    if deepseek_service is None:
        deepseek_service = DeepSeekConnectionService(
            deepseek_store,
            DeepSeekModelsProbe(),
            env_api_key=getenv("DEEPSEEK_API_KEY"),
            env_model=getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
        )

    if monitor_runtime is None:
        monitor_runtime = _build_default_monitor_runtime(
            session_factory,
            settings,
            credential_store,
            deepseek_store,
        )
    else:
        monitor_runtime.settings = settings
    scheduler = (
        scheduler_factory(monitor_runtime)
        if scheduler_factory is not None
        else build_scheduler(monitor_runtime, settings)
    )

    @asynccontextmanager
    async def lifespan(_application):
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)

    application = FastAPI(
        title="B站赛博猫娘管理台",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.runtime = RuntimeState(
        settings=settings,
        login_manager=login_manager,
        account_service=account_service,
        deepseek_service=deepseek_service,
        monitor_runtime=monitor_runtime,
    )
    application.state.session_factory = session_factory
    application.state.monitor_runtime = monitor_runtime
    application.state.scheduler = scheduler
    application.include_router(
        build_router(
            session_factory,
            application.state.runtime,
            monitor_runtime,
        )
    )
    static_dir = Path(__file__).parent / "web" / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    return application


def _build_catgirl_agent(llm, session_factory):
    from cyber_catgirl.agent.service import CatgirlAgent
    from cyber_catgirl.services.style_history import StyleHistoryService

    return CatgirlAgent(
        llm,
        style_history=StyleHistoryService(session_factory),
    )


def _build_default_monitor_runtime(
    session_factory,
    settings,
    credential_store,
    deepseek_store,
):
    from bilibili_api import Credential

    from cyber_catgirl.connectors.bilibili_api import BilibiliApiConnector
    from cyber_catgirl.services.comment_monitor import CommentMonitorService
    from cyber_catgirl.services.content_discovery import ContentDiscoveryService
    from cyber_catgirl.services.memory import MemoryService
    from cyber_catgirl.services.monitor_runtime import MonitorRuntime
    from cyber_catgirl.services.publishing import AutoPublishGuard, Publisher
    from cyber_catgirl.services.replies import ReplyService
    from cyber_catgirl.services.safety import SafetyEngine

    try:
        bilibili_data = credential_store.load()
    except Exception:
        bilibili_data = None
    credential = None
    account_id = "0"
    if bilibili_data is not None:
        credential = Credential(
            sessdata=bilibili_data.sessdata,
            bili_jct=bilibili_data.bili_jct,
            dedeuserid=bilibili_data.dedeuserid,
            ac_time_value=bilibili_data.ac_time_value,
            buvid3=bilibili_data.buvid3,
        )
        account_id = bilibili_data.dedeuserid or "0"

    risk_control_handler = _build_risk_control_handler(session_factory, settings)
    connector = BilibiliApiConnector(
        credential=credential,
        write_enabled=settings.bilibili_write_enabled,
        on_risk_control=risk_control_handler,
    )
    llm = _CredentialBackedLlm(deepseek_store)

    reply_service = ReplyService(
        session_factory,
        _build_catgirl_agent(llm, session_factory),
        MemoryService(session_factory),
        SafetyEngine(
            run_mode=settings.run_mode,
            kill_switch=settings.kill_switch,
            allowed_actor_ids=settings.auto_reply_allowlist,
            comment_auto_reply_enabled=settings.comment_auto_reply_enabled,
            write_enabled=settings.bilibili_write_enabled,
            min_reply_interval_seconds=settings.auto_reply_min_delay_seconds,
            user_daily_limit=settings.auto_reply_user_daily_limit,
            account_hourly_limit=settings.auto_reply_account_hourly_limit,
            account_daily_limit=settings.auto_reply_account_daily_limit,
        ),
        min_delay_seconds=settings.auto_reply_min_delay_seconds,
        max_delay_seconds=settings.auto_reply_max_delay_seconds,
    )
    discovery = ContentDiscoveryService(
        session_factory,
        connector,
        account_id=account_id,
        backfill_days=settings.comment_backfill_days,
    )
    monitor = CommentMonitorService(
        session_factory,
        connector,
        account_id=account_id,
        account_name="赛博猫娘",
        backfill_limit=settings.comment_backfill_limit,
        on_pause=lambda error_code: setattr(
            settings, "comment_monitor_enabled", False
        ),
    )
    def refresh_bilibili_credential() -> None:
        try:
            latest = credential_store.load()
        except Exception:
            latest = None
        if latest is None:
            connector.credential = None
            discovery.account_id = "0"
            monitor.account_id = "0"
            return
        connector.credential = Credential(
            sessdata=latest.sessdata,
            bili_jct=latest.bili_jct,
            dedeuserid=latest.dedeuserid,
            ac_time_value=latest.ac_time_value,
            buvid3=latest.buvid3,
        )
        current_account_id = latest.dedeuserid or "0"
        discovery.account_id = current_account_id
        monitor.account_id = current_account_id

    return MonitorRuntime(
        session_factory,
        settings,
        monitor,
        reply_service,
        Publisher(
            session_factory,
            connector,
            auto_guard=AutoPublishGuard(session_factory, settings),
        ),
        content_discovery=discovery,
        prepare=refresh_bilibili_credential,
    )


def _build_risk_control_handler(session_factory, settings):
    def pause_all_writes() -> None:
        now = datetime.now(timezone.utc)
        settings.kill_switch = True
        settings.comment_monitor_enabled = False
        with session_factory.begin() as session:
            for key, value in (
                ("kill_switch", "true"),
                ("comment_monitor_enabled", "false"),
            ):
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

            queued_jobs = session.scalars(
                select(PublishJobRecord).where(
                    PublishJobRecord.status.in_(("pending", "retry_wait"))
                )
            ).all()
            for job in queued_jobs:
                job.status = "cancelled"
                job.last_error_code = "bilibili_risk_control"
                job.completed_at = now

            session.add(
                AuditLogRecord(
                    action="bilibili_risk_control_pause",
                    entity_id="system",
                    details_json=json.dumps(
                        {"cancelled_jobs": len(queued_jobs)},
                        separators=(",", ":"),
                    ),
                )
            )

    return pause_all_writes


class _CredentialBackedLlm:
    def __init__(self, store) -> None:
        self.store = store

    async def generate_json(self, messages: list[dict], schema: dict) -> dict:
        from cyber_catgirl.agent.client import DeepSeekClient

        try:
            credential = self.store.load()
        except Exception:
            credential = None
        if credential is not None:
            client = DeepSeekClient(
                credential.api_key,
                base_url=getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=credential.model,
            )
            return await client.generate_json(messages, schema)
        api_key = getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("deepseek_not_configured")
        client = DeepSeekClient(
            api_key,
            base_url=getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
        )
        return await client.generate_json(messages, schema)


app = create_app()

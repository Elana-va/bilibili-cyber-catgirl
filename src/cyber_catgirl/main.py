from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cyber_catgirl.config import Settings
from cyber_catgirl.db import create_session_factory
from cyber_catgirl.web.routes import RuntimeState, build_router


def create_app(settings: Settings | None = None, *, session_factory=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if session_factory is None:
        Path("data").mkdir(exist_ok=True)
        session_factory = create_session_factory(settings.database_url)

    application = FastAPI(title="B站赛博猫娘管理台", version="0.1.0")
    application.state.runtime = RuntimeState(settings=settings)
    application.state.session_factory = session_factory
    application.include_router(build_router(session_factory, application.state.runtime))
    static_dir = Path(__file__).parent / "web" / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    return application


app = create_app()

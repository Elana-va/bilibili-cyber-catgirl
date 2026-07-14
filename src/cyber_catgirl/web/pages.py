from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cyber_catgirl.services.dashboard import DashboardService
from cyber_catgirl.web.view_models import LogFilters, ReviewFilters


TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")


def build_page_router(session_factory, state) -> APIRouter:
    router = APIRouter()
    service = DashboardService(session_factory)

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        view = service.overview()
        return TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "overview": view,
                "current_page": "dashboard",
                "run_mode": state.settings.run_mode.value,
                "kill_switch": state.settings.kill_switch,
            },
        )

    @router.get("/reviews", response_class=HTMLResponse)
    def reviews(
        request: Request,
        draft_type: str | None = None,
        risk_level: str | None = None,
        query: str = "",
    ):
        filters = ReviewFilters(
            draft_type=draft_type or None,
            risk_level=risk_level or None,
            query=query,
        )
        return TEMPLATES.TemplateResponse(
            request,
            "reviews.html",
            {
                "reviews": service.pending_reviews(filters),
                "filters": filters,
                "current_page": "reviews",
                "run_mode": state.settings.run_mode.value,
                "kill_switch": state.settings.kill_switch,
            },
        )

    @router.get("/content", response_class=HTMLResponse)
    def content(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "content.html",
            {
                "plans": service.content_plans(),
                "current_page": "content",
                "run_mode": state.settings.run_mode.value,
                "kill_switch": state.settings.kill_switch,
            },
        )

    @router.get("/analytics", response_class=HTMLResponse)
    def analytics() -> str:
        service.analytics()
        return "<h1>互动数据</h1>"

    @router.get("/logs", response_class=HTMLResponse)
    def logs() -> str:
        service.logs(LogFilters())
        return "<h1>运行日志</h1>"

    @router.get("/settings", response_class=HTMLResponse)
    def settings() -> str:
        return f"<h1>系统设置</h1><p>{state.settings.run_mode.value}</p>"

    return router

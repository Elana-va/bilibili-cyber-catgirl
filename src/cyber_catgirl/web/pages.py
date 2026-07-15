from pathlib import Path
from os import getenv

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
    def analytics(request: Request, days: int = 7):
        view = service.analytics(days=days)
        return TEMPLATES.TemplateResponse(
            request,
            "analytics.html",
            {
                "analytics": view,
                "max_comments": max((point.comment_count for point in view.points), default=1)
                or 1,
                "current_page": "analytics",
                "run_mode": state.settings.run_mode.value,
                "kill_switch": state.settings.kill_switch,
            },
        )

    @router.get("/logs", response_class=HTMLResponse)
    def logs(request: Request, status: str | None = None, action: str | None = None):
        filters = LogFilters(status=status or None, action=action or None)
        return TEMPLATES.TemplateResponse(
            request,
            "logs.html",
            {
                "logs": service.logs(filters),
                "filters": filters,
                "current_page": "logs",
                "run_mode": state.settings.run_mode.value,
                "kill_switch": state.settings.kill_switch,
            },
        )

    @router.get("/settings", response_class=HTMLResponse)
    def settings(request: Request):
        return TEMPLATES.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": state.settings,
                "bilibili_configured": state.account_service.configured(),
                "llm_configured": bool(getenv("DEEPSEEK_API_KEY")),
                "current_page": "settings",
                "run_mode": state.settings.run_mode.value,
                "kill_switch": state.settings.kill_switch,
            },
        )

    return router

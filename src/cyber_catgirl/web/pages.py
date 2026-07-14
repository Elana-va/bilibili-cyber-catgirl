from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from cyber_catgirl.services.dashboard import DashboardService
from cyber_catgirl.web.view_models import LogFilters, ReviewFilters


def build_page_router(session_factory, state) -> APIRouter:
    router = APIRouter()
    service = DashboardService(session_factory)

    @router.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        view = service.overview()
        return f"<h1>小喵创作室</h1><p>待审核 {view.pending_reviews}</p>"

    @router.get("/reviews", response_class=HTMLResponse)
    def reviews() -> str:
        service.pending_reviews(ReviewFilters())
        return "<h1>审核中心</h1>"

    @router.get("/content", response_class=HTMLResponse)
    def content() -> str:
        service.content_plans()
        return "<h1>内容计划</h1>"

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

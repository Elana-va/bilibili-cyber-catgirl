from dataclasses import dataclass

from fastapi import APIRouter

from cyber_catgirl.config import Settings
from cyber_catgirl.web.actions import build_action_router
from cyber_catgirl.web.pages import build_page_router


@dataclass
class RuntimeState:
    settings: Settings


def build_router(session_factory, state: RuntimeState) -> APIRouter:
    router = APIRouter()
    router.include_router(build_page_router(session_factory, state))
    router.include_router(build_action_router(session_factory, state))
    return router

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cyber_catgirl.security.credential_store import (
    CredentialUnreadable,
    SecureStorageUnavailable,
)
from cyber_catgirl.services.deepseek_connection import (
    EnvironmentCredentialManaged,
    InsufficientBalance,
    InvalidApiKey,
    RateLimited,
    SelectedModelUnavailable,
)


class DeepSeekConnectRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)
    model: Literal["deepseek-v4-flash", "deepseek-v4-pro"]


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidApiKey):
        return HTTPException(401, "invalid_api_key")
    if isinstance(exc, InsufficientBalance):
        return HTTPException(402, "insufficient_balance")
    if isinstance(exc, RateLimited):
        return HTTPException(429, "rate_limited")
    if isinstance(exc, SelectedModelUnavailable):
        return HTTPException(409, "selected_model_unavailable")
    if isinstance(exc, EnvironmentCredentialManaged):
        return HTTPException(409, "environment_credential_managed")
    if isinstance(exc, SecureStorageUnavailable):
        return HTTPException(501, "secure_storage_unavailable")
    if isinstance(exc, CredentialUnreadable):
        return HTTPException(503, "credential_unreadable")
    return HTTPException(503, "deepseek_unavailable")


def build_deepseek_auth_router(service) -> APIRouter:
    router = APIRouter()

    @router.get("/api/deepseek/connection")
    def connection() -> dict:
        try:
            return asdict(service.connection_view())
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/deepseek/connection")
    async def connect(payload: DeepSeekConnectRequest) -> dict:
        try:
            return asdict(await service.connect(payload.api_key, payload.model))
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/deepseek/verify")
    async def verify() -> dict:
        try:
            return asdict(await service.verify())
        except Exception as exc:
            raise _map_error(exc) from exc

    @router.post("/api/deepseek/disconnect")
    def disconnect() -> dict:
        try:
            service.disconnect()
            return asdict(service.connection_view())
        except Exception as exc:
            raise _map_error(exc) from exc

    return router

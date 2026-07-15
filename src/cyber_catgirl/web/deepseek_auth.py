from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

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
from cyber_catgirl.services.deepseek_connection import ALLOWED_MODELS


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
    async def connect(request: Request) -> dict:
        try:
            payload = await request.json()
            api_key = payload.get("api_key") if isinstance(payload, dict) else None
            model = payload.get("model") if isinstance(payload, dict) else None
            if (
                not isinstance(api_key, str)
                or not 1 <= len(api_key) <= 512
                or model not in ALLOWED_MODELS
            ):
                raise HTTPException(422, "invalid_connection_request")
            return asdict(await service.connect(api_key, model))
        except HTTPException:
            raise
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

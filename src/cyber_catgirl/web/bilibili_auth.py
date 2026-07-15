from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from cyber_catgirl.connectors.bilibili_login import (
    LoginPersistenceFailed,
    LoginSessionNotFound,
)
from cyber_catgirl.security.credential_store import SecureStorageUnavailable
from cyber_catgirl.services.bilibili_account import (
    CredentialDeleteFailed,
    EnvironmentCredentialManaged,
)


def build_bilibili_auth_router(login_manager, account_service) -> APIRouter:
    router = APIRouter()

    @router.post("/api/bilibili/login/qr", status_code=201)
    async def create_qr_login() -> dict:
        try:
            return asdict(await login_manager.create_session())
        except SecureStorageUnavailable as exc:
            raise HTTPException(501, "secure_storage_unavailable") from exc
        except Exception as exc:
            raise HTTPException(503, "platform_unavailable") from exc

    @router.get("/api/bilibili/login/qr/{session_id}")
    async def check_qr_login(session_id: str) -> dict:
        try:
            return asdict(await login_manager.check_session(session_id))
        except LoginSessionNotFound as exc:
            raise HTTPException(404, "login_session_not_found") from exc
        except LoginPersistenceFailed as exc:
            raise HTTPException(503, "credential_persistence_failed") from exc
        except SecureStorageUnavailable as exc:
            raise HTTPException(501, "secure_storage_unavailable") from exc
        except Exception as exc:
            raise HTTPException(503, "platform_unavailable") from exc

    @router.get("/api/bilibili/connection")
    async def connection() -> dict:
        try:
            return asdict(await account_service.connection_view())
        except Exception as exc:
            raise HTTPException(503, "connection_check_failed") from exc

    @router.post("/api/bilibili/disconnect")
    async def disconnect() -> dict:
        login_manager.cancel_all()
        try:
            account_service.disconnect()
        except EnvironmentCredentialManaged as exc:
            raise HTTPException(409, "environment_credential_managed") from exc
        except CredentialDeleteFailed as exc:
            raise HTTPException(503, "credential_delete_failed") from exc
        return {"connected": False}

    return router

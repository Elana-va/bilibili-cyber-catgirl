from __future__ import annotations

import base64
import math
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol

from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

from cyber_catgirl.security.credential_store import BilibiliCredentialData


class LoginSessionNotFound(LookupError):
    """Raised when a QR login session is missing or already complete."""


class LoginPersistenceFailed(RuntimeError):
    """Raised when a completed login cannot be stored securely."""


class LoginPhase(StrEnum):
    WAITING = "waiting"
    SCANNED = "scanned"
    CONNECTED = "connected"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class LoginSessionView:
    session_id: str
    phase: LoginPhase
    qr_data_url: str | None = None
    expires_in: int = 0


class SdkQrLogin(Protocol):
    async def generate(self) -> bytes: ...

    async def check(self) -> LoginPhase: ...

    def credential_data(self) -> BilibiliCredentialData: ...


class CredentialWriter(Protocol):
    def save(self, data: BilibiliCredentialData) -> None: ...


class BilibiliQrSdkAdapter:
    def __init__(self, login: QrCodeLogin | None = None):
        self.login = login or QrCodeLogin()

    async def generate(self) -> bytes:
        await self.login.generate_qrcode()
        return self.login.get_qrcode_picture().content

    async def check(self) -> LoginPhase:
        event = await self.login.check_state()
        return {
            QrCodeLoginEvents.SCAN: LoginPhase.WAITING,
            QrCodeLoginEvents.CONF: LoginPhase.SCANNED,
            QrCodeLoginEvents.DONE: LoginPhase.CONNECTED,
            QrCodeLoginEvents.TIMEOUT: LoginPhase.EXPIRED,
        }[event]

    def credential_data(self) -> BilibiliCredentialData:
        credential = self.login.get_credential()
        return BilibiliCredentialData(
            sessdata=credential.sessdata,
            bili_jct=credential.bili_jct,
            dedeuserid=credential.dedeuserid,
            ac_time_value=credential.ac_time_value,
            buvid3=credential.buvid3,
        )


@dataclass
class _LoginSession:
    session_id: str
    sdk: SdkQrLogin
    created_at: float


class BilibiliLoginManager:
    def __init__(
        self,
        store: CredentialWriter,
        sdk_factory: Callable[[], SdkQrLogin],
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: int = 180,
    ):
        self.store = store
        self.sdk_factory = sdk_factory
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self._session: _LoginSession | None = None

    async def create_session(self) -> LoginSessionView:
        self.cancel_all()
        sdk = self.sdk_factory()
        png = await sdk.generate()
        session_id = secrets.token_urlsafe(24)
        self._session = _LoginSession(session_id, sdk, self.clock())
        encoded = base64.b64encode(png).decode("ascii")
        return LoginSessionView(
            session_id=session_id,
            phase=LoginPhase.WAITING,
            qr_data_url=f"data:image/png;base64,{encoded}",
            expires_in=self.ttl_seconds,
        )

    async def check_session(self, session_id: str) -> LoginSessionView:
        session = self._require_session(session_id)
        remaining = self.ttl_seconds - (self.clock() - session.created_at)
        if remaining <= 0:
            self._session = None
            return LoginSessionView(session_id, LoginPhase.EXPIRED, expires_in=0)

        phase = await session.sdk.check()
        if phase is LoginPhase.CONNECTED:
            try:
                self.store.save(session.sdk.credential_data())
            except Exception as exc:
                self._session = None
                raise LoginPersistenceFailed("B站登录凭证无法安全保存") from exc
            self._session = None
        elif phase in {LoginPhase.EXPIRED, LoginPhase.FAILED}:
            self._session = None

        return LoginSessionView(
            session_id=session_id,
            phase=phase,
            expires_in=max(0, math.ceil(remaining)),
        )

    def cancel_all(self) -> None:
        self._session = None

    def _require_session(self, session_id: str) -> _LoginSession:
        if self._session is None or not secrets.compare_digest(
            self._session.session_id, session_id
        ):
            raise LoginSessionNotFound("二维码登录会话不存在")
        return self._session

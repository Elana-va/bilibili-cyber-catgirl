from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Protocol

from bilibili_api import Credential, user

from cyber_catgirl.security.credential_store import BilibiliCredentialData


class EnvironmentCredentialManaged(RuntimeError):
    """Raised when credentials must be removed from the process environment."""


class CredentialDeleteFailed(RuntimeError):
    """Raised when encrypted credentials cannot be removed safely."""


@dataclass(frozen=True)
class AccountIdentity:
    uid: str
    name: str
    avatar_url: str | None


@dataclass(frozen=True)
class ConnectionView:
    connected: bool
    verification: str
    account: AccountIdentity | None = None


class CredentialReader(Protocol):
    def configured(self) -> bool: ...

    def load(self) -> BilibiliCredentialData | None: ...

    def delete(self) -> None: ...


class IdentityProbe(Protocol):
    async def fetch(self, credential: BilibiliCredentialData) -> AccountIdentity: ...


def load_credential_data(
    store: CredentialReader, environ: Mapping[str, str]
) -> BilibiliCredentialData | None:
    stored = store.load()
    if stored is not None:
        return stored
    sessdata = environ.get("BILI_SESSDATA")
    bili_jct = environ.get("BILI_JCT")
    if not sessdata or not bili_jct:
        return None
    return BilibiliCredentialData(
        sessdata=sessdata,
        bili_jct=bili_jct,
        buvid3=environ.get("BILI_BUVID3"),
    )


class BilibiliIdentityProbe:
    async def fetch(self, credential: BilibiliCredentialData) -> AccountIdentity:
        sdk_credential = Credential(
            sessdata=credential.sessdata,
            bili_jct=credential.bili_jct,
            dedeuserid=credential.dedeuserid,
            ac_time_value=credential.ac_time_value,
            buvid3=credential.buvid3,
        )
        payload = await user.get_self_info(sdk_credential)
        avatar = payload.get("face")
        account_name = payload.get("name") or payload.get("uname")
        if not account_name:
            raise KeyError("B站身份响应缺少账号名称")
        return AccountIdentity(
            uid=str(payload["mid"]),
            name=str(account_name),
            avatar_url=str(avatar) if avatar else None,
        )


class BilibiliAccountService:
    def __init__(
        self,
        store: CredentialReader,
        identity_probe: IdentityProbe,
        *,
        environ: Mapping[str, str] | None = None,
    ):
        self.store = store
        self.identity_probe = identity_probe
        self.environ = os.environ if environ is None else environ

    def configured(self) -> bool:
        return self.store.configured() or bool(
            self.environ.get("BILI_SESSDATA") and self.environ.get("BILI_JCT")
        )

    async def connection_view(self) -> ConnectionView:
        credential = load_credential_data(self.store, self.environ)
        if credential is None:
            return ConnectionView(False, "not_configured")
        try:
            account = await self.identity_probe.fetch(credential)
        except Exception:
            return ConnectionView(False, "verification_failed")
        return ConnectionView(True, "verified", account)

    def disconnect(self) -> None:
        if not self.store.configured():
            if self.environ.get("BILI_SESSDATA") and self.environ.get("BILI_JCT"):
                raise EnvironmentCredentialManaged("环境变量凭证需要从启动环境移除")
            return
        try:
            self.store.delete()
            if self.store.configured():
                raise OSError("credential file still exists")
        except Exception as exc:
            raise CredentialDeleteFailed("B站本机凭证删除失败") from exc

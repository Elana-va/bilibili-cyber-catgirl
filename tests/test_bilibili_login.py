from collections import deque

import pytest

from cyber_catgirl.connectors.bilibili_login import (
    BilibiliLoginManager,
    BilibiliQrSdkAdapter,
    LoginPhase,
    LoginSessionNotFound,
)
from bilibili_api.login_v2 import QrCodeLoginEvents
from cyber_catgirl.security.credential_store import BilibiliCredentialData


class FrozenClock:
    def __init__(self, value: float):
        self.value = value

    def __call__(self) -> float:
        return self.value


class MemoryCredentialStore:
    def __init__(self):
        self.saved = None

    def save(self, data: BilibiliCredentialData) -> None:
        self.saved = data


class FakeQrSdk:
    def __init__(self, phases=None):
        self.phases = deque(phases or [LoginPhase.WAITING])
        self.generated = False

    async def generate(self) -> bytes:
        self.generated = True
        return b"fake-png"

    async def check(self) -> LoginPhase:
        return self.phases.popleft()

    def credential_data(self) -> BilibiliCredentialData:
        return BilibiliCredentialData("sess-secret", "csrf-secret", dedeuserid="123")


class FakePicture:
    content = b"sdk-png"


class FakeCredential:
    sessdata = "sdk-sess"
    bili_jct = "sdk-csrf"
    dedeuserid = "123"
    ac_time_value = "sdk-refresh"
    buvid3 = "sdk-buvid"


class FakeSdkLogin:
    def __init__(self):
        self.generated = False

    async def generate_qrcode(self):
        self.generated = True

    def get_qrcode_picture(self):
        return FakePicture()

    async def check_state(self):
        return QrCodeLoginEvents.CONF

    def get_credential(self):
        return FakeCredential()


@pytest.mark.asyncio
async def test_sdk_adapter_maps_qr_and_allowed_credential_fields():
    login = FakeSdkLogin()
    adapter = BilibiliQrSdkAdapter(login)

    assert await adapter.generate() == b"sdk-png"
    assert await adapter.check() is LoginPhase.SCANNED
    assert adapter.credential_data() == BilibiliCredentialData(
        "sdk-sess",
        "sdk-csrf",
        dedeuserid="123",
        ac_time_value="sdk-refresh",
        buvid3="sdk-buvid",
    )


@pytest.mark.asyncio
async def test_manager_returns_qr_once_and_saves_on_success():
    sdk = FakeQrSdk(
        [LoginPhase.WAITING, LoginPhase.SCANNED, LoginPhase.CONNECTED]
    )
    store = MemoryCredentialStore()
    manager = BilibiliLoginManager(store, lambda: sdk, clock=FrozenClock(1000))

    created = await manager.create_session()
    waiting = await manager.check_session(created.session_id)
    scanned = await manager.check_session(created.session_id)
    connected = await manager.check_session(created.session_id)

    assert created.qr_data_url.startswith("data:image/png;base64,")
    assert created.expires_in == 180
    assert waiting.qr_data_url is None
    assert scanned.phase is LoginPhase.SCANNED
    assert connected.phase is LoginPhase.CONNECTED
    assert store.saved.sessdata == "sess-secret"
    with pytest.raises(LoginSessionNotFound):
        await manager.check_session(created.session_id)


@pytest.mark.asyncio
async def test_new_session_invalidates_old_session():
    sdks = iter([FakeQrSdk(), FakeQrSdk()])
    manager = BilibiliLoginManager(MemoryCredentialStore(), lambda: next(sdks))

    old = await manager.create_session()
    new = await manager.create_session()

    with pytest.raises(LoginSessionNotFound):
        await manager.check_session(old.session_id)
    assert new.session_id != old.session_id


@pytest.mark.asyncio
async def test_expired_session_is_removed_without_saving():
    clock = FrozenClock(1000)
    store = MemoryCredentialStore()
    manager = BilibiliLoginManager(store, FakeQrSdk, clock=clock)
    created = await manager.create_session()

    clock.value = 1181
    expired = await manager.check_session(created.session_id)

    assert expired.phase is LoginPhase.EXPIRED
    assert expired.expires_in == 0
    assert store.saved is None
    with pytest.raises(LoginSessionNotFound):
        await manager.check_session(created.session_id)


@pytest.mark.asyncio
async def test_cancel_all_removes_active_session():
    manager = BilibiliLoginManager(MemoryCredentialStore(), FakeQrSdk)
    created = await manager.create_session()

    manager.cancel_all()

    with pytest.raises(LoginSessionNotFound):
        await manager.check_session(created.session_id)

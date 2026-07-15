import pytest

from cyber_catgirl.security.credential_store import BilibiliCredentialData
from cyber_catgirl.services.bilibili_account import (
    AccountIdentity,
    BilibiliAccountService,
    BilibiliIdentityProbe,
    ConnectionView,
    EnvironmentCredentialManaged,
    load_credential_data,
)


SECRET = BilibiliCredentialData("sess-secret", "csrf-secret")


class FakeStore:
    def __init__(self, data=None):
        self.data = data
        self.deleted = False

    def configured(self):
        return self.data is not None

    def load(self):
        return self.data

    def delete(self):
        self.data = None
        self.deleted = True


class FakeIdentityProbe:
    async def fetch(self, credential):
        assert credential == SECRET
        return AccountIdentity("123", "测试账号", "https://i.example/avatar.jpg")


class FailingIdentityProbe:
    async def fetch(self, credential):
        raise RuntimeError("cookie=sess-secret")


@pytest.mark.asyncio
async def test_connection_view_exposes_only_public_identity():
    service = BilibiliAccountService(FakeStore(SECRET), FakeIdentityProbe(), environ={})

    view = await service.connection_view()

    assert view == ConnectionView(
        connected=True,
        verification="verified",
        account=AccountIdentity("123", "测试账号", "https://i.example/avatar.jpg"),
    )
    assert "sess-secret" not in repr(view)


def test_environment_is_used_only_when_store_is_empty():
    data = load_credential_data(
        FakeStore(None),
        {
            "BILI_SESSDATA": "env-sess",
            "BILI_JCT": "env-csrf",
            "BILI_BUVID3": "env-buvid",
        },
    )

    assert data == BilibiliCredentialData(
        "env-sess", "env-csrf", buvid3="env-buvid"
    )


def test_encrypted_store_takes_precedence_over_environment():
    assert load_credential_data(
        FakeStore(SECRET),
        {"BILI_SESSDATA": "env-sess", "BILI_JCT": "env-csrf"},
    ) == SECRET


@pytest.mark.asyncio
async def test_probe_failure_returns_fixed_public_state():
    service = BilibiliAccountService(
        FakeStore(SECRET), FailingIdentityProbe(), environ={}
    )

    view = await service.connection_view()

    assert view.connected is False
    assert view.verification == "verification_failed"
    assert view.account is None
    assert "secret" not in repr(view)


@pytest.mark.asyncio
async def test_missing_credentials_are_not_connected():
    service = BilibiliAccountService(FakeStore(), FakeIdentityProbe(), environ={})

    assert await service.connection_view() == ConnectionView(
        False, "not_configured", None
    )
    assert service.configured() is False


def test_disconnect_deletes_only_local_encrypted_credentials():
    store = FakeStore(SECRET)
    service = BilibiliAccountService(store, FakeIdentityProbe(), environ={})

    service.disconnect()

    assert store.deleted is True
    assert service.configured() is False


def test_environment_managed_credentials_cannot_be_deleted_by_web():
    service = BilibiliAccountService(
        FakeStore(),
        FakeIdentityProbe(),
        environ={"BILI_SESSDATA": "env-sess", "BILI_JCT": "env-csrf"},
    )

    with pytest.raises(EnvironmentCredentialManaged):
        service.disconnect()


@pytest.mark.asyncio
async def test_identity_probe_accepts_current_bilibili_name_field(monkeypatch):
    async def current_self_info_response(credential):
        return {
            "mid": 123,
            "name": "当前字段账号",
            "face": "https://i.example/current.jpg",
        }

    monkeypatch.setattr(
        "cyber_catgirl.services.bilibili_account.user.get_self_info",
        current_self_info_response,
    )

    identity = await BilibiliIdentityProbe().fetch(SECRET)

    assert identity == AccountIdentity(
        "123", "当前字段账号", "https://i.example/current.jpg"
    )

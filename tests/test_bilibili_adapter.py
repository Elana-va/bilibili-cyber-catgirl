import pytest

from cyber_catgirl.connectors.bilibili_api import (
    BilibiliApiConnector,
    CredentialsUnavailable,
    PlatformRiskControl,
)


class FakeSdk:
    def __init__(self):
        self.raise_next = None

    async def get_comments(self, oid, resource_type, page, credential):
        return {
            "replies": [
                {
                    "rpid": 101,
                    "ctime": 1784000000,
                    "parent": 0,
                    "member": {"mid": "u1", "uname": "用户"},
                    "content": {"message": "你好"},
                }
            ]
        }

    async def send_comment(self, text, oid, resource_type, root, credential):
        if self.raise_next:
            raise self.raise_next
        return {"rpid": 202}


class SdkError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


async def test_missing_credentials_refuses_write():
    connector = BilibiliApiConnector(oid=123, resource_type="dynamic", credential=None)

    with pytest.raises(CredentialsUnavailable):
        await connector.reply_to_comment("123", "101", "你好")


async def test_read_only_comment_fetch_normalizes_events():
    connector = BilibiliApiConnector(
        oid=123,
        resource_type="dynamic",
        credential=None,
        sdk=FakeSdk(),
    )

    events, cursor = await connector.fetch_comments(None)

    assert events[0].event_id == "comment_101"
    assert events[0].target_id == "123"
    assert cursor == "2"


async def test_risk_control_error_opens_manual_only():
    sdk = FakeSdk()
    sdk.raise_next = SdkError(-412, "risk control")
    switched = []
    connector = BilibiliApiConnector(
        oid=123,
        resource_type="dynamic",
        credential=object(),
        sdk=sdk,
        write_enabled=True,
        on_risk_control=lambda: switched.append(True),
    )

    with pytest.raises(PlatformRiskControl):
        await connector.reply_to_comment("123", "101", "你好")

    assert switched == [True]

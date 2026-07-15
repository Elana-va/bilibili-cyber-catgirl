from datetime import datetime, timezone

from cyber_catgirl.connectors.bilibili_api import BilibiliApiConnector
from cyber_catgirl.schemas import PlatformContentTarget


class DiscoverySdk:
    def __init__(self):
        self.sent = None

    async def get_videos(self, account_id, page, credential):
        assert account_id == 1801157579
        assert page == 1
        return {
            "list": {
                "vlist": [
                    {
                        "aid": 42,
                        "bvid": "BV1test",
                        "title": "测试视频",
                        "created": 1784000000,
                    }
                ]
            }
        }

    async def get_dynamics(self, account_id, offset, credential):
        assert account_id == 1801157579
        assert offset == ""
        return {
            "items": [
                {
                    "id_str": "9001",
                    "basic": {"comment_type": 12, "rid_str": "77"},
                    "modules": {
                        "module_author": {"pub_ts": 1784000100},
                        "module_dynamic": {
                            "desc": {"text": "图文动态正文"},
                            "major": {"type": "MAJOR_TYPE_DRAW"},
                        },
                    },
                }
            ],
            "has_more": False,
            "offset": "",
        }

    async def get_dynamic_info(self, dynamic_id, credential):
        raise AssertionError("complete dynamic items should not require a detail request")

    async def get_comments(self, oid, resource_type, page, credential):
        assert (oid, resource_type, page) == (42, "video", 1)
        return {
            "replies": [
                {
                    "rpid": 100,
                    "ctime": 1784000200,
                    "rcount": 1,
                    "member": {"mid": "u1", "uname": "用户A"},
                    "content": {"message": "顶级评论"},
                }
            ],
            "cursor": {"is_end": True},
        }

    async def get_sub_comments(self, oid, resource_type, root, page, credential):
        assert (oid, resource_type, root, page) == (42, "video", 100, 1)
        return {
            "replies": [
                {
                    "rpid": 102,
                    "root": 100,
                    "parent": 101,
                    "ctime": 1784000300,
                    "member": {"mid": "u2", "uname": "用户B"},
                    "content": {"message": "楼中楼"},
                }
            ],
            "page": {"num": 1, "size": 10, "count": 1},
        }

    async def send_comment(
        self, text, oid, resource_type, root, parent, credential
    ):
        self.sent = {
            "text": text,
            "oid": oid,
            "resource_type": resource_type,
            "root": root,
            "parent": parent,
        }
        return {"rpid": 202}


def video_target() -> PlatformContentTarget:
    return PlatformContentTarget(
        platform_content_id="video:42",
        display_type="video",
        comment_oid="42",
        resource_type="video",
        title="测试视频",
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )


async def test_discovers_video_then_dynamic_comment_targets_one_page_at_a_time():
    connector = BilibiliApiConnector(credential=object(), sdk=DiscoverySdk())

    videos, cursor = await connector.discover_contents("1801157579", None)
    dynamics, final_cursor = await connector.discover_contents("1801157579", cursor)

    assert [(target.display_type, target.resource_type) for target in videos] == [
        ("video", "video")
    ]
    assert [(target.display_type, target.resource_type) for target in dynamics] == [
        ("dynamic_draw", "article")
    ]
    assert videos[0].platform_content_id == "video:42"
    assert dynamics[0].comment_oid == "77"
    assert final_cursor is None


async def test_top_level_page_reports_roots_with_nested_replies():
    connector = BilibiliApiConnector(credential=object(), sdk=DiscoverySdk())

    page = await connector.fetch_comment_page(video_target(), None)

    assert page.events[0].root_comment_id == "100"
    assert page.events[0].parent_comment_id is None
    assert page.root_ids_with_replies == ("100",)
    assert page.next_cursor is None


async def test_nested_reply_preserves_root_and_direct_parent():
    connector = BilibiliApiConnector(credential=object(), sdk=DiscoverySdk())

    page = await connector.fetch_subcomment_page(video_target(), "100", None)

    assert page.events[0].root_comment_id == "100"
    assert page.events[0].parent_comment_id == "101"
    assert page.next_cursor is None


async def test_writer_passes_root_and_parent_to_sdk():
    sdk = DiscoverySdk()
    connector = BilibiliApiConnector(
        credential=object(), sdk=sdk, write_enabled=True
    )

    platform_id = await connector.reply_to_comment(
        "42", "video", "100", "101", "收到喵"
    )

    assert sdk.sent == {
        "text": "收到喵",
        "oid": 42,
        "resource_type": "video",
        "root": 100,
        "parent": 101,
    }
    assert platform_id == "comment:202"


async def test_nested_publication_verification_reads_subcomments():
    connector = BilibiliApiConnector(credential=object(), sdk=DiscoverySdk())

    visible = await connector.verify_publication(
        "comment:102", "42", "video", root_comment_id="100"
    )

    assert visible is True

from dataclasses import dataclass, field

from cyber_catgirl.connectors.base import CommentPage
from cyber_catgirl.schemas import InteractionEvent, PlatformContentTarget


@dataclass
class FakeBilibiliConnector:
    events: list[InteractionEvent] = field(default_factory=list)
    targets: list[PlatformContentTarget] = field(default_factory=list)
    next_cursor: str | None = None
    visible: bool = True
    reply_id: str = "reply_fake_1"
    dynamic_id: str = "dynamic_fake_1"
    write_calls: list[dict] = field(default_factory=list)

    async def discover_contents(
        self, account_id: str, cursor: str | None
    ) -> tuple[list[PlatformContentTarget], str | None]:
        return list(self.targets), self.next_cursor

    async def fetch_comment_page(
        self, target: PlatformContentTarget, cursor: str | None
    ) -> CommentPage:
        return CommentPage(list(self.events), self.next_cursor)

    async def fetch_subcomment_page(
        self,
        target: PlatformContentTarget,
        root_comment_id: str,
        cursor: str | None,
    ) -> CommentPage:
        nested = [event for event in self.events if event.root_comment_id == root_comment_id]
        return CommentPage(nested, self.next_cursor)

    async def fetch_comments(
        self, cursor: str | None
    ) -> tuple[list[InteractionEvent], str | None]:
        return list(self.events), self.next_cursor

    async def reply_to_comment(self, comment_oid: str, *args) -> str:
        if len(args) == 2:
            root_comment_id, text = args
            resource_type = "legacy"
            parent_comment_id = None
        elif len(args) == 4:
            resource_type, root_comment_id, parent_comment_id, text = args
        else:
            raise TypeError("reply_to_comment expects legacy 3 or threaded 5 arguments")
        self.write_calls.append(
            {
                "action": "reply",
                "target_id": comment_oid,
                "resource_type": resource_type,
                "comment_id": root_comment_id,
                "parent_comment_id": parent_comment_id,
                "text": text,
            }
        )
        return self.reply_id

    async def publish_dynamic(self, text: str, image_paths: list[str]) -> str:
        self.write_calls.append(
            {"action": "publish_dynamic", "text": text, "image_paths": image_paths}
        )
        return self.dynamic_id

    async def verify_publication(
        self,
        platform_id: str,
        comment_oid: str | None = None,
        resource_type: str | None = None,
    ) -> bool:
        return self.visible

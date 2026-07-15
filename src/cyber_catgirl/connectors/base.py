from dataclasses import dataclass
from typing import Protocol

from cyber_catgirl.schemas import InteractionEvent, PlatformContentTarget


@dataclass(frozen=True)
class CommentPage:
    events: list[InteractionEvent]
    next_cursor: str | None
    root_ids_with_replies: tuple[str, ...] = ()


class BilibiliPort(Protocol):
    async def discover_contents(
        self, account_id: str, cursor: str | None
    ) -> tuple[list[PlatformContentTarget], str | None]: ...

    async def fetch_comment_page(
        self, target: PlatformContentTarget, cursor: str | None
    ) -> CommentPage: ...

    async def fetch_subcomment_page(
        self,
        target: PlatformContentTarget,
        root_comment_id: str,
        cursor: str | None,
    ) -> CommentPage: ...

    async def fetch_comments(
        self, cursor: str | None
    ) -> tuple[list[InteractionEvent], str | None]: ...

    async def reply_to_comment(
        self,
        comment_oid: str,
        resource_type: str,
        root_comment_id: str,
        parent_comment_id: str | None,
        text: str,
    ) -> str: ...

    async def publish_dynamic(self, text: str, image_paths: list[str]) -> str: ...

    async def verify_publication(
        self,
        platform_id: str,
        comment_oid: str | None = None,
        resource_type: str | None = None,
    ) -> bool: ...

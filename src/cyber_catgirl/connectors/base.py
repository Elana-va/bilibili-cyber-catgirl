from typing import Protocol

from cyber_catgirl.schemas import InteractionEvent


class BilibiliPort(Protocol):
    async def fetch_comments(
        self, cursor: str | None
    ) -> tuple[list[InteractionEvent], str | None]: ...

    async def reply_to_comment(
        self, target_id: str, comment_id: str, text: str
    ) -> str: ...

    async def publish_dynamic(self, text: str, image_paths: list[str]) -> str: ...

    async def verify_publication(self, platform_id: str) -> bool: ...

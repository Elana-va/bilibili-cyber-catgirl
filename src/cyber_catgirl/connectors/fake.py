from dataclasses import dataclass, field

from cyber_catgirl.schemas import InteractionEvent


@dataclass
class FakeBilibiliConnector:
    events: list[InteractionEvent] = field(default_factory=list)
    next_cursor: str | None = None
    visible: bool = True
    reply_id: str = "reply_fake_1"
    dynamic_id: str = "dynamic_fake_1"
    write_calls: list[dict] = field(default_factory=list)

    async def fetch_comments(
        self, cursor: str | None
    ) -> tuple[list[InteractionEvent], str | None]:
        return list(self.events), self.next_cursor

    async def reply_to_comment(self, target_id: str, comment_id: str, text: str) -> str:
        self.write_calls.append(
            {
                "action": "reply",
                "target_id": target_id,
                "comment_id": comment_id,
                "text": text,
            }
        )
        return self.reply_id

    async def publish_dynamic(self, text: str, image_paths: list[str]) -> str:
        self.write_calls.append(
            {"action": "publish_dynamic", "text": text, "image_paths": image_paths}
        )
        return self.dynamic_id

    async def verify_publication(self, platform_id: str) -> bool:
        return self.visible

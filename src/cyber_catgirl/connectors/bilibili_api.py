from collections.abc import Callable
from datetime import datetime, timezone
from os import getenv
from pathlib import Path
from typing import Any

from cyber_catgirl.schemas import InteractionEvent


class BilibiliConnectorError(RuntimeError):
    pass


class CredentialsUnavailable(BilibiliConnectorError):
    pass


class WriteNotAuthorized(BilibiliConnectorError):
    pass


class PlatformRateLimited(BilibiliConnectorError):
    pass


class PlatformRiskControl(BilibiliConnectorError):
    pass


class PlatformUnavailable(BilibiliConnectorError):
    pass


RESOURCE_TYPES = {"video", "article", "dynamic", "dynamic_draw"}


class BilibiliSdkFacade:
    @staticmethod
    def _resource_type(name: str):
        from bilibili_api.comment import CommentResourceType

        return {
            "video": CommentResourceType.VIDEO,
            "article": CommentResourceType.ARTICLE,
            "dynamic": CommentResourceType.DYNAMIC,
            "dynamic_draw": CommentResourceType.DYNAMIC_DRAW,
        }[name]

    async def get_comments(self, oid: int, resource_type: str, page: int, credential):
        from bilibili_api import comment

        return await comment.get_comments(
            oid=oid,
            type_=self._resource_type(resource_type),
            page_index=page,
            credential=credential,
        )

    async def send_comment(
        self, text: str, oid: int, resource_type: str, root: int, credential
    ):
        from bilibili_api import comment

        return await comment.send_comment(
            text=text,
            oid=oid,
            type_=self._resource_type(resource_type),
            root=root,
            credential=credential,
        )

    async def send_dynamic(self, text: str, image_paths: list[str], credential):
        from bilibili_api import Picture, dynamic

        pictures = [Picture.from_file(str(Path(path))) for path in image_paths]
        payload = dynamic.BuildDynamic.create_by_args(text=text, pics=pictures)
        return await dynamic.send_dynamic(payload, credential=credential)

    async def verify_dynamic(self, dynamic_id: int, credential) -> bool:
        from bilibili_api import dynamic

        info = await dynamic.Dynamic(dynamic_id, credential=credential).get_info()
        return bool(info)


class BilibiliApiConnector:
    def __init__(
        self,
        *,
        oid: int,
        resource_type: str,
        credential=None,
        sdk=None,
        write_enabled: bool = False,
        on_risk_control: Callable[[], None] | None = None,
    ) -> None:
        if resource_type not in RESOURCE_TYPES:
            raise ValueError(f"unsupported resource type: {resource_type}")
        self.oid = oid
        self.resource_type = resource_type
        self.credential = credential
        self.sdk = sdk or BilibiliSdkFacade()
        self.write_enabled = write_enabled
        self.on_risk_control = on_risk_control or (lambda: None)

    @classmethod
    def from_env(
        cls,
        *,
        oid: int,
        resource_type: str,
        write_enabled: bool = False,
        on_risk_control: Callable[[], None] | None = None,
    ) -> "BilibiliApiConnector":
        from bilibili_api import Credential

        sessdata = getenv("BILI_SESSDATA")
        bili_jct = getenv("BILI_JCT")
        buvid3 = getenv("BILI_BUVID3")
        credential = None
        if sessdata and bili_jct:
            credential = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)
        return cls(
            oid=oid,
            resource_type=resource_type,
            credential=credential,
            write_enabled=write_enabled,
            on_risk_control=on_risk_control,
        )

    async def fetch_comments(
        self, cursor: str | None
    ) -> tuple[list[InteractionEvent], str | None]:
        page = int(cursor) if cursor else 1
        try:
            payload = await self.sdk.get_comments(
                self.oid,
                self.resource_type,
                page,
                self.credential,
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc

        replies = self._extract_replies(payload)
        events = [self._normalize_reply(reply) for reply in replies if reply.get("rpid")]
        return events, str(page + 1)

    async def reply_to_comment(self, target_id: str, comment_id: str, text: str) -> str:
        self._require_write_access()
        try:
            payload = await self.sdk.send_comment(
                text,
                int(target_id),
                self.resource_type,
                int(comment_id),
                self.credential,
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc
        rpid = self._extract_id(payload, ("rpid", "reply", "id"))
        return f"comment:{rpid}"

    async def publish_dynamic(self, text: str, image_paths: list[str]) -> str:
        self._require_write_access()
        for path in image_paths:
            if not Path(path).is_file():
                raise FileNotFoundError(path)
        try:
            payload = await self.sdk.send_dynamic(text, image_paths, self.credential)
        except Exception as exc:
            raise self._map_exception(exc) from exc
        dynamic_id = self._extract_id(payload, ("dynamic_id", "dyn_id", "id"))
        return f"dynamic:{dynamic_id}"

    async def verify_publication(self, platform_id: str) -> bool:
        kind, raw_id = platform_id.split(":", maxsplit=1)
        if kind == "comment":
            payload = await self.sdk.get_comments(
                self.oid,
                self.resource_type,
                1,
                self.credential,
            )
            return any(str(reply.get("rpid")) == raw_id for reply in self._extract_replies(payload))
        if kind == "dynamic":
            return await self.sdk.verify_dynamic(int(raw_id), self.credential)
        return False

    def _require_write_access(self) -> None:
        if self.credential is None:
            raise CredentialsUnavailable("B站写操作需要登录凭证")
        if not self.write_enabled:
            raise WriteNotAuthorized("真实写入闸门未开启")

    def _normalize_reply(self, reply: dict[str, Any]) -> InteractionEvent:
        member = reply.get("member") or {}
        content = reply.get("content") or {}
        timestamp = int(reply.get("ctime") or 0)
        return InteractionEvent(
            event_id=f"comment_{reply['rpid']}",
            event_type="new_comment",
            actor_id=str(member.get("mid") or "unknown"),
            actor_name=str(member.get("uname") or "未知用户"),
            content=str(content.get("message") or ""),
            target_type=self.resource_type,
            target_id=str(self.oid),
            parent_comment_id=(str(reply["parent"]) if reply.get("parent") else None),
            platform_created_at=datetime.fromtimestamp(timestamp, tz=timezone.utc),
        )

    @staticmethod
    def _extract_replies(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(payload.get("replies"), list):
            return payload["replies"]
        data = payload.get("data") or {}
        if isinstance(data.get("replies"), list):
            return data["replies"]
        return []

    @classmethod
    def _extract_id(cls, payload: Any, keys: tuple[str, ...]) -> int:
        if isinstance(payload, dict):
            for key in keys:
                if key in payload and str(payload[key]).isdigit():
                    return int(payload[key])
            for value in payload.values():
                try:
                    return cls._extract_id(value, keys)
                except ValueError:
                    continue
        raise ValueError("platform response did not contain a publication id")

    def _map_exception(self, exc: Exception) -> BilibiliConnectorError:
        code = getattr(exc, "code", None)
        if code in {-509, 429}:
            return PlatformRateLimited("B站请求频率受限")
        if code in {-412, 412, -352, -403, -102}:
            self.on_risk_control()
            return PlatformRiskControl("B站返回账号或风控异常，已要求切换人工模式")
        return PlatformUnavailable("B站接口暂不可用")

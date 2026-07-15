from collections.abc import Callable
from datetime import datetime, timezone
from os import getenv
from pathlib import Path
from typing import Any

from cyber_catgirl.connectors.base import CommentPage
from cyber_catgirl.schemas import InteractionEvent, PlatformContentTarget


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
COMMENT_TYPE_NAMES = {1: "video", 11: "dynamic_draw", 12: "article", 17: "dynamic"}


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

    async def get_videos(self, account_id: int, page: int, credential):
        from bilibili_api import user

        return await user.User(account_id, credential=credential).get_videos(pn=page, ps=30)

    async def get_dynamics(self, account_id: int, offset: str, credential):
        from bilibili_api import user

        return await user.User(account_id, credential=credential).get_dynamics_new(offset=offset)

    async def get_dynamic_info(self, dynamic_id: int, credential):
        from bilibili_api import dynamic

        return await dynamic.Dynamic(dynamic_id, credential=credential).get_info()

    async def get_comments(self, oid: int, resource_type: str, page: int, credential):
        from bilibili_api import comment

        return await comment.get_comments(
            oid=oid,
            type_=self._resource_type(resource_type),
            page_index=page,
            credential=credential,
        )

    async def get_sub_comments(
        self,
        oid: int,
        resource_type: str,
        root: int,
        page: int,
        credential,
    ):
        from bilibili_api import comment

        reply = comment.Comment(
            oid=oid,
            type_=self._resource_type(resource_type),
            rpid=root,
            credential=credential,
        )
        return await reply.get_sub_comments(page_index=page, page_size=20)

    async def send_comment(
        self,
        text: str,
        oid: int,
        resource_type: str,
        root: int,
        parent: int | None,
        credential,
    ):
        from bilibili_api import comment

        return await comment.send_comment(
            text=text,
            oid=oid,
            type_=self._resource_type(resource_type),
            root=root,
            parent=parent,
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
        oid: int | None = None,
        resource_type: str | None = None,
        credential=None,
        sdk=None,
        write_enabled: bool = False,
        on_risk_control: Callable[[], None] | None = None,
    ) -> None:
        if resource_type is not None and resource_type not in RESOURCE_TYPES:
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
        oid: int | None = None,
        resource_type: str | None = None,
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

    async def discover_contents(
        self, account_id: str, cursor: str | None
    ) -> tuple[list[PlatformContentTarget], str | None]:
        source, value = self._parse_discovery_cursor(cursor)
        try:
            if source == "video":
                page = int(value)
                payload = await self.sdk.get_videos(int(account_id), page, self.credential)
                videos = self._extract_videos(payload)
                targets = [self._normalize_video(item) for item in videos]
                next_cursor = f"video:{page + 1}" if len(videos) >= 30 else "dynamic:"
                return targets, next_cursor

            payload = await self.sdk.get_dynamics(int(account_id), value, self.credential)
            targets: list[PlatformContentTarget] = []
            for item in self._extract_dynamics(payload):
                candidate = item
                if not self._dynamic_has_comment_target(candidate):
                    dynamic_id = self._dynamic_id(candidate)
                    candidate = await self.sdk.get_dynamic_info(dynamic_id, self.credential)
                target = self._normalize_dynamic(candidate)
                if target is not None:
                    targets.append(target)
            next_offset = str(payload.get("offset") or "")
            next_cursor = (
                f"dynamic:{next_offset}"
                if bool(payload.get("has_more")) and next_offset
                else None
            )
            return targets, next_cursor
        except Exception as exc:
            raise self._map_exception(exc) from exc

    async def fetch_comment_page(
        self, target: PlatformContentTarget, cursor: str | None
    ) -> CommentPage:
        page = int(cursor) if cursor else 1
        try:
            payload = await self.sdk.get_comments(
                int(target.comment_oid), target.resource_type, page, self.credential
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc
        replies = self._extract_replies(payload)
        events = [self._normalize_reply(reply, target) for reply in replies if reply.get("rpid")]
        roots = tuple(
            str(reply["rpid"])
            for reply in replies
            if reply.get("rpid") and self._reply_has_children(reply)
        )
        return CommentPage(events, self._next_comment_cursor(payload, page, replies), roots)

    async def fetch_subcomment_page(
        self,
        target: PlatformContentTarget,
        root_comment_id: str,
        cursor: str | None,
    ) -> CommentPage:
        page = int(cursor) if cursor else 1
        try:
            payload = await self.sdk.get_sub_comments(
                int(target.comment_oid),
                target.resource_type,
                int(root_comment_id),
                page,
                self.credential,
            )
        except Exception as exc:
            raise self._map_exception(exc) from exc
        replies = self._extract_replies(payload)
        events = [
            self._normalize_reply(reply, target, root_override=root_comment_id)
            for reply in replies
            if reply.get("rpid")
        ]
        return CommentPage(events, self._next_comment_cursor(payload, page, replies))

    async def fetch_comments(
        self, cursor: str | None
    ) -> tuple[list[InteractionEvent], str | None]:
        if self.oid is None or self.resource_type is None:
            raise ValueError("legacy fetch_comments requires a bound oid and resource type")
        target = PlatformContentTarget(
            platform_content_id=f"legacy:{self.resource_type}:{self.oid}",
            display_type="video" if self.resource_type == "video" else "dynamic_text",
            comment_oid=str(self.oid),
            resource_type=self.resource_type,
            published_at=datetime.now(timezone.utc),
        )
        result = await self.fetch_comment_page(target, cursor)
        return result.events, result.next_cursor

    async def reply_to_comment(self, comment_oid: str, *args) -> str:
        self._require_write_access()
        if len(args) == 2:
            if self.resource_type is None:
                raise ValueError("legacy reply requires a bound resource type")
            root_comment_id, text = args
            resource_type = self.resource_type
            parent_comment_id = None
        elif len(args) == 4:
            resource_type, root_comment_id, parent_comment_id, text = args
        else:
            raise TypeError("reply_to_comment expects legacy 3 or threaded 5 arguments")
        try:
            payload = await self.sdk.send_comment(
                str(text),
                int(comment_oid),
                str(resource_type),
                int(root_comment_id),
                int(parent_comment_id) if parent_comment_id else None,
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

    async def verify_publication(
        self,
        platform_id: str,
        comment_oid: str | None = None,
        resource_type: str | None = None,
    ) -> bool:
        kind, raw_id = platform_id.split(":", maxsplit=1)
        if kind == "comment":
            oid = comment_oid or (str(self.oid) if self.oid is not None else None)
            type_name = resource_type or self.resource_type
            if oid is None or type_name is None:
                return False
            payload = await self.sdk.get_comments(int(oid), type_name, 1, self.credential)
            return any(
                str(reply.get("rpid")) == raw_id for reply in self._extract_replies(payload)
            )
        if kind == "dynamic":
            return await self.sdk.verify_dynamic(int(raw_id), self.credential)
        return False

    def _require_write_access(self) -> None:
        if self.credential is None:
            raise CredentialsUnavailable("B站写操作需要登录凭证")
        if not self.write_enabled:
            raise WriteNotAuthorized("真实写入闸门未开启")

    @staticmethod
    def _parse_discovery_cursor(cursor: str | None) -> tuple[str, str]:
        if cursor is None:
            return "video", "1"
        source, separator, value = cursor.partition(":")
        if not separator or source not in {"video", "dynamic"}:
            raise ValueError("invalid content discovery cursor")
        return source, value

    @staticmethod
    def _extract_videos(payload: dict[str, Any]) -> list[dict[str, Any]]:
        listing = payload.get("list") or {}
        videos = listing.get("vlist") or payload.get("videos") or []
        return videos if isinstance(videos, list) else []

    @staticmethod
    def _extract_dynamics(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items") or []
        return items if isinstance(items, list) else []

    @staticmethod
    def _dynamic_id(item: dict[str, Any]) -> int:
        raw = item.get("id_str") or item.get("id")
        if not str(raw).isdigit():
            raise ValueError("dynamic item did not contain an id")
        return int(raw)

    @staticmethod
    def _dynamic_has_comment_target(item: dict[str, Any]) -> bool:
        candidate = item.get("item") if isinstance(item.get("item"), dict) else item
        basic = candidate.get("basic") or {}
        return bool(basic.get("comment_type") and basic.get("rid_str"))

    @staticmethod
    def _normalize_video(item: dict[str, Any]) -> PlatformContentTarget:
        aid = item.get("aid")
        if not str(aid).isdigit():
            raise ValueError("video item did not contain an aid")
        return PlatformContentTarget(
            platform_content_id=f"video:{aid}",
            display_type="video",
            comment_oid=str(aid),
            resource_type="video",
            title=str(item.get("title") or "")[:256],
            published_at=BilibiliApiConnector._timestamp(
                item.get("created") or item.get("pubdate")
            ),
        )

    @staticmethod
    def _normalize_dynamic(item: dict[str, Any]) -> PlatformContentTarget | None:
        candidate = item.get("item") if isinstance(item.get("item"), dict) else item
        basic = candidate.get("basic") or {}
        comment_type = int(basic.get("comment_type") or 0)
        resource_type = COMMENT_TYPE_NAMES.get(comment_type)
        comment_oid = basic.get("rid_str")
        if resource_type is None or not str(comment_oid).isdigit():
            return None
        modules = candidate.get("modules") or {}
        author = modules.get("module_author") or {}
        dynamic_module = modules.get("module_dynamic") or {}
        description = dynamic_module.get("desc") or {}
        major = dynamic_module.get("major") or {}
        major_type = str(major.get("type") or "").casefold()
        display_type = "dynamic_draw" if "draw" in major_type else "dynamic_text"
        dynamic_id = BilibiliApiConnector._dynamic_id(candidate)
        return PlatformContentTarget(
            platform_content_id=f"dynamic:{dynamic_id}",
            display_type=display_type,
            comment_oid=str(comment_oid),
            resource_type=resource_type,
            title=str(description.get("text") or candidate.get("title") or "")[:256],
            published_at=BilibiliApiConnector._timestamp(
                author.get("pub_ts") or candidate.get("pub_ts")
            ),
        )

    @staticmethod
    def _timestamp(raw: Any) -> datetime:
        value = int(raw or 0)
        return datetime.fromtimestamp(value, tz=timezone.utc)

    @staticmethod
    def _extract_replies(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(payload.get("replies"), list):
            return payload["replies"]
        data = payload.get("data") or {}
        if isinstance(data.get("replies"), list):
            return data["replies"]
        return []

    @staticmethod
    def _reply_has_children(reply: dict[str, Any]) -> bool:
        return bool(reply.get("rcount") or reply.get("count") or reply.get("replies"))

    @staticmethod
    def _next_comment_cursor(
        payload: dict[str, Any], page: int, replies: list[dict[str, Any]]
    ) -> str | None:
        cursor = payload.get("cursor") or (payload.get("data") or {}).get("cursor") or {}
        if cursor.get("is_end") is True:
            return None
        page_info = payload.get("page") or (payload.get("data") or {}).get("page") or {}
        if page_info:
            number = int(page_info.get("num") or page)
            size = int(page_info.get("size") or len(replies) or 1)
            count = int(page_info.get("count") or len(replies))
            return str(page + 1) if number * size < count else None
        return str(page + 1) if replies else None

    @staticmethod
    def _normalize_reply(
        reply: dict[str, Any],
        target: PlatformContentTarget,
        root_override: str | None = None,
    ) -> InteractionEvent:
        member = reply.get("member") or {}
        content = reply.get("content") or {}
        rpid = str(reply["rpid"])
        root = root_override or str(reply.get("root") or rpid)
        parent = str(reply["parent"]) if root_override and reply.get("parent") else None
        return InteractionEvent(
            event_id=f"comment_{rpid}",
            event_type="new_comment",
            actor_id=str(member.get("mid") or "unknown"),
            actor_name=str(member.get("uname") or "未知用户"),
            content=str(content.get("message") or ""),
            target_type=target.resource_type,
            target_id=target.comment_oid,
            root_comment_id=root,
            parent_comment_id=parent,
            platform_created_at=BilibiliApiConnector._timestamp(reply.get("ctime")),
        )

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
        if isinstance(exc, BilibiliConnectorError):
            return exc
        code = getattr(exc, "code", None)
        if code in {-509, 429}:
            return PlatformRateLimited("B站请求频率受限")
        if code in {-412, 412, -352, -403, -102}:
            self.on_risk_control()
            return PlatformRiskControl("B站返回账号或风控异常，已要求切换人工模式")
        return PlatformUnavailable("B站接口暂不可用")

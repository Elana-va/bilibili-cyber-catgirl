import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cyber_catgirl.connectors.base import BilibiliPort
from cyber_catgirl.connectors.bilibili_api import (
    BilibiliApiConnector,
    BilibiliConnectorError,
)


class ProbeReport(BaseModel):
    comment_read: bool = False
    comment_write: bool = False
    events_seen: int = 0
    errors: list[str] = Field(default_factory=list)


class CapabilityProbe:
    def __init__(self, connector: BilibiliPort) -> None:
        self.connector = connector

    async def run(
        self,
        *,
        read_only: bool = True,
        write_target: tuple[str, str] | None = None,
    ) -> ProbeReport:
        report = ProbeReport()
        events, _ = await self.connector.fetch_comments(None)
        report.comment_read = True
        report.events_seen = len(events)

        if read_only:
            return report
        if write_target is None:
            report.errors.append("write probe target is required")
            return report

        target_id, comment_id = write_target
        platform_id = await self.connector.reply_to_comment(
            target_id,
            comment_id,
            "[AI测试] B站赛博猫娘连接器单次能力探针",
        )
        report.comment_write = await self.connector.verify_publication(platform_id)
        return report


def save_report(path: Path, report: BaseModel | dict[str, Any]) -> None:
    payload = report.model_dump(mode="json") if isinstance(report, BaseModel) else report
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def _run_read_only_probe(args: argparse.Namespace) -> int:
    connector = BilibiliApiConnector.from_env(
        oid=args.oid,
        resource_type=args.resource_type,
        write_enabled=False,
    )
    try:
        report = await CapabilityProbe(connector).run(read_only=True)
        payload = {
            "mode": "read_only",
            "oid": args.oid,
            "resource_type": args.resource_type,
            **report.model_dump(mode="json"),
        }
        exit_code = 0
    except BilibiliConnectorError as exc:
        payload = {
            "mode": "read_only",
            "oid": args.oid,
            "resource_type": args.resource_type,
            "comment_read": False,
            "comment_write": False,
            "events_seen": 0,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
        exit_code = 1
    save_report(args.report, payload)
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="B站连接器只读能力探针")
    parser.add_argument("--oid", type=int, required=True, help="目标内容 oid")
    parser.add_argument(
        "--resource-type",
        choices=("video", "article", "dynamic", "dynamic_draw"),
        required=True,
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="确认本次探针不执行任何写操作",
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.read_only:
        parser.error("当前命令行探针只允许 --read-only 模式")
    raise SystemExit(asyncio.run(_run_read_only_probe(args)))


if __name__ == "__main__":
    main()

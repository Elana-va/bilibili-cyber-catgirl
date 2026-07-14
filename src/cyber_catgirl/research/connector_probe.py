from pydantic import BaseModel, Field

from cyber_catgirl.connectors.base import BilibiliPort


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

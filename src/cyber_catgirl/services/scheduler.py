from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


def register_jobs(
    scheduler: AsyncIOScheduler,
    *,
    poll_comments,
    scan_content,
    create_daily_report,
) -> None:
    scheduler.add_job(
        poll_comments,
        IntervalTrigger(seconds=60),
        id="poll-comments",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        scan_content,
        IntervalTrigger(minutes=1),
        id="scan-content",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        create_daily_report,
        CronTrigger(hour=21, minute=30, timezone="Asia/Shanghai"),
        id="daily-report",
        replace_existing=True,
        max_instances=1,
    )

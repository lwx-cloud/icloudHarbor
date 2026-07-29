from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.background import (  # type: ignore[import-untyped]
    BackgroundScheduler,
)
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import (  # type: ignore[import-untyped]
    IntervalTrigger,
)

from icloudharbor.config.models import AppConfig, ScheduleConfig
from icloudharbor.config.validation import parse_duration


class SchedulerService:
    def __init__(self, config: AppConfig, sync_callback: Callable[[str], object]) -> None:
        self.config = config
        self.sync_callback = sync_callback
        self.scheduler = BackgroundScheduler(
            timezone=config.runtime.timezone,
            job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600},
        )

    def configure(self) -> None:
        for account in self.config.accounts:
            if not account.enabled:
                continue
            schedule = account.sync.schedule
            if schedule:
                trigger: CronTrigger | IntervalTrigger
                if isinstance(schedule, str):
                    trigger = CronTrigger.from_crontab(
                        schedule,
                        timezone=self.config.runtime.timezone,
                    )
                elif isinstance(schedule, ScheduleConfig) and schedule.cron:
                    trigger = CronTrigger.from_crontab(
                        schedule.cron,
                        timezone=self.config.runtime.timezone,
                    )
                else:
                    assert isinstance(schedule, ScheduleConfig) and schedule.interval
                    duration = parse_duration(schedule.interval)
                    trigger = IntervalTrigger(
                        seconds=duration.total_seconds(),
                        timezone=self.config.runtime.timezone,
                    )
                self.scheduler.add_job(
                    self.sync_callback,
                    trigger=trigger,
                    args=[account.id],
                    id=f"sync:{account.id}",
                    replace_existing=True,
                )
            if account.sync.run_on_start:
                self.scheduler.add_job(
                    self.sync_callback,
                    args=[account.id],
                    id=f"sync-on-start:{account.id}",
                )

    def start(self) -> None:
        if not self.scheduler.get_jobs():
            self.configure()
        self.scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

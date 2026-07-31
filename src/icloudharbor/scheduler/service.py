from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
        self._configured = False
        self._active_accounts: set[str] = set()
        self._queued_accounts: set[str] = set()
        self._guard = threading.Lock()
        self.scheduler = BackgroundScheduler(
            timezone=config.runtime.timezone,
            job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600},
        )

    def configure(self) -> None:
        now = datetime.now(ZoneInfo(self.config.runtime.timezone))
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
                    start_date = None
                    if account.sync.run_on_start or account.sync.download_delay:
                        start_date = now + timedelta(minutes=account.sync.download_delay) + duration
                    trigger = IntervalTrigger(
                        seconds=duration.total_seconds(),
                        start_date=start_date,
                        timezone=self.config.runtime.timezone,
                    )
                self.scheduler.add_job(
                    self._execute,
                    trigger=trigger,
                    args=[account.id],
                    id=f"sync:{account.id}",
                    replace_existing=True,
                )
            if account.sync.run_on_start:
                run_at = now + timedelta(minutes=account.sync.download_delay)
                self.scheduler.add_job(
                    self._execute,
                    trigger="date",
                    run_date=run_at,
                    args=[account.id],
                    id=f"sync-on-start:{account.id}",
                    replace_existing=True,
                )
        self._configured = True

    def start(self) -> None:
        if not self._configured:
            self.configure()
        self.scheduler.start()

    def trigger_now(self, account_id: str) -> bool:
        account = self.config.account(account_id)
        if not account.enabled:
            return False
        with self._guard:
            if account_id in self._active_accounts or account_id in self._queued_accounts:
                return False
            self._queued_accounts.add(account_id)
        try:
            self.scheduler.add_job(
                self._execute,
                trigger="date",
                run_date=datetime.now(ZoneInfo(self.config.runtime.timezone)),
                args=[account_id],
                id=f"sync-now:{account_id}",
                replace_existing=True,
            )
        except Exception:
            with self._guard:
                self._queued_accounts.discard(account_id)
            raise
        return True

    def _execute(self, account_id: str) -> object | None:
        with self._guard:
            self._queued_accounts.discard(account_id)
            if account_id in self._active_accounts:
                return None
            self._active_accounts.add(account_id)
        try:
            return self.sync_callback(account_id)
        finally:
            with self._guard:
                self._active_accounts.discard(account_id)

    def shutdown(self, wait: bool = True) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

    def next_run_times(self) -> list[tuple[str, datetime]]:
        return [
            (job.id, job.next_run_time)
            for job in self.scheduler.get_jobs()
            if job.next_run_time is not None
        ]

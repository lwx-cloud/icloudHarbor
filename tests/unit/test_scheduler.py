from __future__ import annotations

from icloudharbor.config.models import AppConfig
from icloudharbor.scheduler.service import SchedulerService


def test_run_on_start_does_not_require_recurring_schedule(app_config: AppConfig) -> None:
    account = app_config.accounts[0]
    account.sync.schedule = None
    account.sync.run_on_start = True
    scheduler = SchedulerService(app_config, lambda _: None)

    scheduler.configure()

    assert [job.id for job in scheduler.scheduler.get_jobs()] == ["sync-on-start:personal"]

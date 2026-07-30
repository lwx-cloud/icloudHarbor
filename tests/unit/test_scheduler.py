from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from icloudharbor.config.models import AppConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.database.session import Database
from icloudharbor.protocol.exceptions import HarborError
from icloudharbor.scheduler.locks import LockCoordinator
from icloudharbor.scheduler.service import SchedulerService


def test_run_on_start_does_not_require_recurring_schedule(app_config: AppConfig) -> None:
    account = app_config.accounts[0]
    account.sync.schedule = None
    account.sync.run_on_start = True
    scheduler = SchedulerService(app_config, lambda _: None)

    scheduler.configure()

    assert [job.id for job in scheduler.scheduler.get_jobs()] == ["sync-on-start:personal"]


def test_run_on_start_honors_download_delay(app_config: AppConfig) -> None:
    account = app_config.accounts[0]
    account.sync.schedule = None
    account.sync.run_on_start = True
    account.sync.download_delay = 15
    scheduler = SchedulerService(app_config, lambda _: None)

    scheduler.configure()

    job = scheduler.scheduler.get_job("sync-on-start:personal")
    assert job is not None
    assert (
        job.trigger.run_date - datetime.now(job.trigger.run_date.tzinfo)
    ).total_seconds() >= 14 * 60


def test_interval_first_run_honors_download_delay_without_run_on_start(
    app_config: AppConfig,
) -> None:
    account = app_config.accounts[0]
    account.sync.schedule = {"interval": "12h"}
    account.sync.run_on_start = False
    account.sync.download_delay = 15
    scheduler = SchedulerService(app_config, lambda _: None)

    scheduler.configure()

    job = scheduler.scheduler.get_job("sync:personal")
    assert job is not None
    assert job.trigger.start_date is not None
    seconds_until_first_run = (
        job.trigger.start_date - datetime.now(job.trigger.start_date.tzinfo)
    ).total_seconds()
    assert seconds_until_first_run >= (12 * 60 + 14) * 60


def test_file_lock_owner_recovers_orphaned_database_lease(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    database = Database(app_config.runtime.database)
    database.initialize()
    repository = StateRepository(database)
    name = "sync:personal"
    assert repository.acquire_lock(name, "interrupted-container", timedelta(hours=12))
    coordinator = LockCoordinator(tmp_path / "locks", repository)

    with coordinator.acquire(name):
        assert repository.acquire_lock(name, "must-not-acquire", timedelta(hours=12)) is False

    assert repository.acquire_lock(name, "next-run", timedelta(hours=12)) is True
    repository.release_lock(name, "next-run")


def test_live_file_lock_prevents_database_lease_recovery(
    app_config: AppConfig,
    tmp_path: Path,
) -> None:
    database = Database(app_config.runtime.database)
    database.initialize()
    repository = StateRepository(database)
    lock_directory = tmp_path / "locks"
    first = LockCoordinator(lock_directory, repository)
    second = LockCoordinator(lock_directory, repository)
    name = "sync:personal"

    with (
        first.acquire(name),
        pytest.raises(HarborError, match="文件锁已被占用"),
        second.acquire(name),
    ):
        pytest.fail("活跃文件锁不能被第二个协调器接管")

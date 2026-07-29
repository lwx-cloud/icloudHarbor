"""Process, file, and SQLite lock coordination."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from filelock import FileLock, Timeout

from icloudharbor.database.repository import StateRepository
from icloudharbor.protocol.exceptions import ErrorCode, HarborError


class LockCoordinator:
    def __init__(self, lock_directory: Path, repository: StateRepository) -> None:
        self.lock_directory = lock_directory
        self.lock_directory.mkdir(parents=True, exist_ok=True)
        self.repository = repository
        self._process_locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @contextmanager
    def acquire(self, name: str, ttl: timedelta = timedelta(hours=12)) -> Iterator[None]:
        safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
        with self._guard:
            process_lock = self._process_locks.setdefault(safe_name, threading.Lock())
        if not process_lock.acquire(blocking=False):
            raise HarborError("相同账号和图库的同步已在运行", ErrorCode.ALREADY_RUNNING)
        file_lock = FileLock(self.lock_directory / f"{safe_name}.lock")
        owner = f"{uuid.uuid4()}:{threading.get_ident()}"
        db_acquired = False
        try:
            try:
                file_lock.acquire(timeout=0)
            except Timeout as exc:
                raise HarborError("同步文件锁已被占用", ErrorCode.ALREADY_RUNNING) from exc
            db_acquired = self.repository.acquire_lock(name, owner, ttl)
            if not db_acquired:
                raise HarborError("同步数据库锁已被占用", ErrorCode.ALREADY_RUNNING)
            yield
        finally:
            if db_acquired:
                self.repository.release_lock(name, owner)
            if file_lock.is_locked:
                file_lock.release()
            process_lock.release()

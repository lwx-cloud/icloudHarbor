from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from icloudharbor.config.models import AppConfig
from icloudharbor.database.session import Database


@dataclass(slots=True, frozen=True)
class HealthResult:
    ok: bool
    status: str
    checks: dict[str, str]


class HealthService:
    def __init__(self, config: AppConfig, database: Database) -> None:
        self.config = config
        self.database = database

    def liveness(self) -> HealthResult:
        return HealthResult(True, "READY", {"process": "ok"})

    def readiness(self) -> HealthResult:
        checks: dict[str, str] = {}
        try:
            checks["database"] = self.database.check()
        except Exception as exc:
            checks["database"] = f"error:{type(exc).__name__}"
        temp_path = self.config.runtime.temp_path
        if not temp_path.is_dir():
            checks["temp_path"] = "missing"
        elif not os.access(temp_path, os.W_OK):
            checks["temp_path"] = "not_writable"
        else:
            checks["temp_path"] = "ok"
        for account in (item for item in self.config.accounts if item.enabled):
            destination = account.destination.path
            key = f"destination:{account.id}"
            if not destination.is_dir():
                checks[key] = "missing"
            elif not (destination / account.destination.mounted_marker).is_file():
                checks[key] = "marker_missing"
            elif not os.access(destination, os.W_OK):
                checks[key] = "not_writable"
            elif shutil.disk_usage(destination).free < account.destination.minimum_free_space:
                checks[key] = "storage_low"
            else:
                checks[key] = "ok"
        ok = all(value in {"ok"} for value in checks.values())
        return HealthResult(ok, "READY" if ok else "DEGRADED", checks)

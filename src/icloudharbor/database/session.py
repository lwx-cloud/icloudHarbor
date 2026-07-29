"""SQLite engine setup with the safety pragmas required by the design."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from icloudharbor.database.models import Base


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+pysqlite:///{path.as_posix()}"
        self.engine: Engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )
        event.listen(self.engine, "connect", self._set_pragmas)
        self.sessions = sessionmaker(self.engine, class_=Session, expire_on_commit=False)

    @staticmethod
    def _set_pragmas(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def check(self) -> str:
        with self.sessions() as session:
            result = session.execute(text("PRAGMA integrity_check")).scalar_one()
        return str(result)

    def dispose(self) -> None:
        self.engine.dispose()

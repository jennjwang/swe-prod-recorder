from __future__ import annotations

import pathlib
from typing import Optional

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    observer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_ts: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Observation(id={self.id}, observer={self.observer_name}, "
            f"event_ts={self.event_ts})>")


async def init_db(
    db_path: str = "gum.db",
    db_directory: Optional[str] = None,
):
    """Create the SQLite file and ORM tables (first run only)."""
    if db_directory:
        path = pathlib.Path(db_directory).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        db_path = str(path / db_path)

    engine: AsyncEngine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
        connect_args={
            "timeout": 30,
            "isolation_level": None,
        },
        poolclass=None,
    )

    async with engine.begin() as conn:
        await conn.execute(sql_text("PRAGMA journal_mode=WAL"))
        await conn.execute(sql_text("PRAGMA busy_timeout=30000"))

        await conn.run_sync(Base.metadata.create_all)

        # Ensure legacy databases pick up the new event_ts column
        result = await conn.execute(sql_text("PRAGMA table_info(observations)"))
        column_names = {row[1] for row in result.fetchall()}
        if "event_ts" not in column_names:
            await conn.execute(
                sql_text("ALTER TABLE observations ADD COLUMN event_ts REAL")
            )

    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return engine, Session

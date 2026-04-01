import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from swe_prod_recorder.gum import gum
from swe_prod_recorder.observers.observer import Observer
from swe_prod_recorder.schemas import Update


class _OneShotObserver(Observer):
    async def _worker(self) -> None:
        await self.update_queue.put(
            Update(content="hello", content_type="input_text", event_ts=123.0)
        )
        while True:
            await asyncio.sleep(0.1)


class GumSqlitePersistenceTests(unittest.TestCase):
    def test_exit_checkpoints_wal(self) -> None:
        async def exercise() -> tuple[int, int]:
            with tempfile.TemporaryDirectory() as data_directory:
                observer = _OneShotObserver(name="test")
                async with gum(
                    "tester",
                    observer,
                    data_directory=data_directory,
                    checkpoint_db_on_exit=True,
                ):
                    await asyncio.sleep(0.2)

                db_path = Path(data_directory) / "actions.db"
                wal_path = Path(data_directory) / "actions.db-wal"
                with sqlite3.connect(db_path) as conn:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM observations"
                    ).fetchone()[0]

                wal_size = wal_path.stat().st_size if wal_path.exists() else 0
                return count, wal_size

        count, wal_size = asyncio.run(exercise())
        self.assertEqual(count, 1)
        self.assertEqual(wal_size, 0)


if __name__ == "__main__":
    unittest.main()

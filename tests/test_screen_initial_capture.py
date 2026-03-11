import asyncio
import tempfile
import unittest
from types import TracebackType
from unittest.mock import patch

from swe_prod_recorder.observers.screen import Screen, _RawFrame


class _FakeMSS:
    def __init__(self) -> None:
        self.monitors: list[dict[str, int]] = []

    def __enter__(self):
        self.monitors = [
            {"left": 0, "top": 0, "width": 3840, "height": 2160},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class ScreenInitialCaptureTests(unittest.TestCase):
    def test_initial_capture_saves_all_tracked_regions(self):
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as screenshots_dir:
                with patch("swe_prod_recorder.observers.screen.mss.mss", _FakeMSS):
                    screen = Screen(
                        record_all_screens=True,
                        screenshots_dir=screenshots_dir,
                    )

                screen._tracked_windows = [
                    {"region": {"left": 0, "top": 0, "width": 100, "height": 50}},
                    {"region": {"left": 100, "top": 0, "width": 100, "height": 50}},
                ]
                screen.update_queue = asyncio.Queue()

                async def fake_update_regions() -> bool:
                    return True

                async def fake_run_in_thread(func, *args, **kwargs):
                    return func(*args, **kwargs)

                saved_tags: list[str] = []

                async def fake_save_frame(
                    frame,
                    monitor_rect,
                    x,
                    y,
                    tag: str,
                    highlight: bool = True,
                    box_color: str = "red",
                    box_width: int = 10,
                    event_ts: float | None = None,
                ) -> str:
                    saved_tags.append(tag)
                    return tag

                def fake_grab_screenshot(mss_rect):
                    return _RawFrame(width=100, height=50, rgb=b"")

                screen._update_tracked_regions = fake_update_regions
                screen._run_in_thread = fake_run_in_thread
                screen._grab_screenshot = fake_grab_screenshot
                screen._save_frame = fake_save_frame

                await screen._capture_initial_state(123.0)

                self.assertEqual(
                    saved_tags,
                    ["system_start_win1", "system_start_win2"],
                )
                update = await screen.update_queue.get()
                self.assertEqual(
                    update.content,
                    "system_session_start(status=captured(2/2))",
                )

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()

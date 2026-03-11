import asyncio
import tempfile
import unittest
from types import TracebackType
from unittest.mock import patch
from types import SimpleNamespace

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


class ScreenWaylandKeyCaptureTests(unittest.TestCase):
    def test_wayland_key_capture_saves_all_tracked_regions(self):
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

                async def fake_update_activity_time() -> None:
                    return None

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
                screen._update_activity_time = fake_update_activity_time
                screen._grab_screenshot = fake_grab_screenshot
                screen._save_frame = fake_save_frame

                await screen._capture_wayland_key_event("a", 123.0)

                self.assertEqual(
                    saved_tags,
                    ["key_press(a)_win1", "key_press(a)_win2"],
                )
                update = await screen.update_queue.get()
                self.assertEqual(update.content, "key_press(a)")

        asyncio.run(exercise())

    def test_wayland_helper_line_dispatches_key(self):
        with tempfile.TemporaryDirectory() as screenshots_dir:
            with patch("swe_prod_recorder.observers.screen.mss.mss", _FakeMSS):
                screen = Screen(
                    record_all_screens=True,
                    screenshots_dir=screenshots_dir,
                )

            captured_keys: list[str] = []
            screen._safe_schedule_wayland_native_key = captured_keys.append

            screen._handle_wayland_native_key_helper_line("READY\t/dev/input/event3")
            screen._handle_wayland_native_key_helper_line("KEY\ta")

            self.assertTrue(screen._wayland_native_keyboard_enabled)
            self.assertEqual(captured_keys, ["a"])

    def test_wayland_helper_preflight_requests_sudo(self):
        with tempfile.TemporaryDirectory() as screenshots_dir:
            with patch("swe_prod_recorder.observers.screen.mss.mss", _FakeMSS):
                screen = Screen(
                    record_all_screens=True,
                    screenshots_dir=screenshots_dir,
                )

            screen._is_wayland = True

            with patch.object(
                screen,
                "_get_wayland_evdev_keyboard_paths",
                return_value=[],
            ):
                with patch("swe_prod_recorder.observers.screen.os.geteuid", return_value=1000):
                    with patch(
                        "swe_prod_recorder.observers.screen.subprocess.run",
                        return_value=SimpleNamespace(returncode=0),
                    ) as run_mock:
                        self.assertTrue(screen.preflight_wayland_keyboard_helper())

            run_mock.assert_called_once_with(["sudo", "-v"], check=False)
            self.assertTrue(screen._wayland_keyboard_helper_preflight_attempted)
            self.assertTrue(screen._wayland_keyboard_helper_preflight_succeeded)

    def test_wayland_key_capture_ignores_events_after_shutdown(self):
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as screenshots_dir:
                with patch("swe_prod_recorder.observers.screen.mss.mss", _FakeMSS):
                    screen = Screen(
                        record_all_screens=True,
                        screenshots_dir=screenshots_dir,
                    )

                screen._tracked_windows = [
                    {"region": {"left": 0, "top": 0, "width": 100, "height": 50}},
                ]
                screen.update_queue = asyncio.Queue()
                screen._running = False

                await screen._capture_wayland_key_event("a", 123.0)

                self.assertTrue(screen.update_queue.empty())

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()

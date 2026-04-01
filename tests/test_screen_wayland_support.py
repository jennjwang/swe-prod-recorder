import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from swe_prod_recorder.observers.screen import Screen, _RawFrame


def _build_wayland_screen(screenshots_dir: str) -> Screen:
    with patch.dict(
        "swe_prod_recorder.observers.screen.os.environ",
        {"WAYLAND_DISPLAY": "wayland-0"},
        clear=False,
    ):
        with patch(
            "swe_prod_recorder.observers.screen._get_monitor_regions",
            return_value=[{"left": 0, "top": 0, "width": 100, "height": 50}],
        ):
            return Screen(record_all_screens=True, screenshots_dir=screenshots_dir)


def _write_stream_snapshot(stream_dir: str, *, sequence: int, color: tuple[int, int, int]) -> None:
    import os

    os.makedirs(stream_dir, exist_ok=True)
    frame_path = f"{stream_dir}/frame-{sequence:06d}.jpg"
    Image.new("RGB", (20, 10), color=color).save(frame_path, "JPEG")
    with open(f"{stream_dir}/latest.json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "sequence": sequence,
                "path": frame_path,
                "ts": 123.0,
            },
            handle,
        )


class ScreenWaylandSupportTests(unittest.TestCase):
    def test_wayland_pointer_position_uses_cached_polling_state(self) -> None:
        with tempfile.TemporaryDirectory() as screenshots_dir:
            screen = _build_wayland_screen(screenshots_dir)
            screen._set_wayland_pointer_position(123, 456)
            self.assertEqual(screen._get_pointer_position(), (123.0, 456.0))

    def test_wayland_helpers_become_ready_after_capture_and_input(self) -> None:
        with tempfile.TemporaryDirectory() as screenshots_dir:
            screen = _build_wayland_screen(screenshots_dir)

            screen._handle_wayland_input_helper_line("READY\t/dev/input/event1")
            self.assertFalse(screen._listeners_started)

            screen._handle_wayland_capture_helper_line(
                'READY\t{"streams":[{"node_id":51,"dir":"/tmp/stream-1","region":{"left":0,"top":0,"width":100,"height":50}}]}'
            )

            self.assertTrue(screen._listeners_started)
            self.assertEqual(screen._tracked_windows[0]["region"], {"left": 0, "top": 0, "width": 100, "height": 50})

    def test_wayland_preflight_requests_sudo_when_input_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as screenshots_dir:
            screen = _build_wayland_screen(screenshots_dir)

            with patch.object(screen, "_get_wayland_evdev_keyboard_paths", return_value=[]):
                with patch.object(screen, "_get_wayland_evdev_mouse_paths", return_value=[]):
                    with patch(
                        "swe_prod_recorder.observers.screen.os.geteuid",
                        return_value=1000,
                    ):
                        with patch(
                            "swe_prod_recorder.observers.screen.subprocess.run",
                            return_value=SimpleNamespace(returncode=0),
                        ) as run_mock:
                            self.assertTrue(screen.preflight_wayland_input_helper())

        run_mock.assert_called_once_with(["sudo", "-v"], check=False)

    def test_wayland_snapshot_loader_reads_latest_frame(self) -> None:
        with tempfile.TemporaryDirectory() as screenshots_dir:
            screen = _build_wayland_screen(screenshots_dir)
            stream_dir = f"{screenshots_dir}/stream-1"
            _write_stream_snapshot(stream_dir, sequence=3, color=(0, 255, 0))

            frame = screen._read_wayland_stream_snapshot(
                {"dir": stream_dir, "region": {"left": 0, "top": 0, "width": 20, "height": 10}},
            )

            image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb)
            self.assertEqual(frame.sequence, 3)
            self.assertGreater(image.getpixel((5, 5))[1], 200)

    def test_wayland_grab_screenshot_uses_matching_stream(self) -> None:
        with tempfile.TemporaryDirectory() as screenshots_dir:
            screen = _build_wayland_screen(screenshots_dir)
            left_dir = f"{screenshots_dir}/left"
            right_dir = f"{screenshots_dir}/right"
            _write_stream_snapshot(left_dir, sequence=1, color=(255, 0, 0))
            _write_stream_snapshot(right_dir, sequence=2, color=(0, 255, 0))
            screen._wayland_capture_streams = [
                {
                    "dir": left_dir,
                    "node_id": 10,
                    "region": {"left": 0, "top": 0, "width": 100, "height": 50},
                },
                {
                    "dir": right_dir,
                    "node_id": 11,
                    "region": {"left": 100, "top": 0, "width": 100, "height": 50},
                },
            ]

            frame = screen._grab_screenshot({"left": 120, "top": 0, "width": 80, "height": 50})
            image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb)
            self.assertEqual(frame.sequence, 2)
            self.assertGreater(image.getpixel((5, 5))[1], 200)

    def test_wayland_key_capture_saves_all_regions(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as screenshots_dir:
                screen = _build_wayland_screen(screenshots_dir)
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

                def fake_grab_screenshot(*_args, **_kwargs):
                    return _RawFrame(width=100, height=50, rgb=bytes([0, 0, 0] * 5000), sequence=7)

                screen._update_tracked_regions = fake_update_regions
                screen._run_in_thread = fake_run_in_thread
                screen._grab_screenshot = fake_grab_screenshot
                screen._save_frame = fake_save_frame

                await screen._capture_wayland_key_event("a", 123.0)

                self.assertEqual(saved_tags, ["key_press(a)_win1", "key_press(a)_win2"])
                update = await screen.update_queue.get()
                self.assertEqual(update.content, "key_press(a)")

        asyncio.run(exercise())

    def test_wayland_mouse_capture_saves_before_and_after_for_all_regions(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as screenshots_dir:
                screen = _build_wayland_screen(screenshots_dir)
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

                sequence = 0

                def fake_grab_screenshot(*_args, **_kwargs):
                    nonlocal sequence
                    sequence += 1
                    return _RawFrame(
                        width=100,
                        height=50,
                        rgb=bytes([0, 0, 0] * 5000),
                        sequence=sequence,
                    )

                screen._set_wayland_pointer_position(20, 10)
                screen._update_tracked_regions = fake_update_regions
                screen._run_in_thread = fake_run_in_thread
                screen._grab_screenshot = fake_grab_screenshot
                screen._save_frame = fake_save_frame

                await screen._capture_wayland_pointer_event(action="click_left", event_ts=123.0)

                self.assertEqual(
                    saved_tags,
                    [
                        "click_left(20.0, 10.0)_before_win1",
                        "click_left(20.0, 10.0)_after_win1",
                        "click_left(20.0, 10.0)_before_win2",
                        "click_left(20.0, 10.0)_after_win2",
                    ],
                )
                update = await screen.update_queue.get()
                self.assertEqual(update.content, "click_left(20.0, 10.0)")

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()

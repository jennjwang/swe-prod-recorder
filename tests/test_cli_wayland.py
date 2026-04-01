import unittest
from types import SimpleNamespace
from unittest.mock import patch

from swe_prod_recorder import cli


class CliWaylandTests(unittest.TestCase):
    def test_wayland_root_run_exits_early(self) -> None:
        args = SimpleNamespace(
            upload_to_gdrive=False,
            record_all_screens=True,
            inactivity_timeout=45,
            debug=False,
            pr=1,
        )

        with patch("swe_prod_recorder.cli.parse_args", return_value=args):
            with patch("swe_prod_recorder.cli.platform.system", return_value="Linux"):
                with patch("swe_prod_recorder.cli.os.geteuid", return_value=0):
                    with patch.dict(
                        "swe_prod_recorder.cli.os.environ",
                        {"WAYLAND_DISPLAY": "wayland-0"},
                        clear=False,
                    ):
                        with self.assertRaises(SystemExit) as exc:
                            cli.main()

        self.assertEqual(exc.exception.code, 1)

    def test_wayland_sudo_preflight_happens_before_confirmation(self) -> None:
        args = SimpleNamespace(
            upload_to_gdrive=False,
            record_all_screens=True,
            inactivity_timeout=45,
            debug=False,
            pr=1,
        )
        fake_screen = SimpleNamespace()
        calls: list[str] = []

        def needs_helper() -> bool:
            calls.append("needs_helper")
            return True

        def preflight() -> bool:
            calls.append("preflight")
            return True

        def fake_input(prompt: str) -> str:
            calls.append("input")
            raise SystemExit(0)

        fake_screen.needs_wayland_input_helper = needs_helper
        fake_screen.preflight_wayland_input_helper = preflight
        fake_screen.poll_wayland_cursor_position = lambda: calls.append("poll")
        fake_screen.stop_listeners_sync = lambda: None

        with patch("swe_prod_recorder.cli.parse_args", return_value=args):
            with patch("swe_prod_recorder.cli.platform.system", return_value="Linux"):
                with patch("swe_prod_recorder.cli.os.geteuid", return_value=1000):
                    with patch.dict(
                        "swe_prod_recorder.cli.os.environ",
                        {"WAYLAND_DISPLAY": "wayland-0"},
                        clear=False,
                    ):
                        with patch(
                            "swe_prod_recorder.cli.Screen",
                            return_value=fake_screen,
                        ):
                            with patch("builtins.input", side_effect=fake_input):
                                with self.assertRaises(SystemExit):
                                    cli.main()

        self.assertLess(calls.index("preflight"), calls.index("input"))
        self.assertLess(calls.index("poll"), calls.index("input"))


if __name__ == "__main__":
    unittest.main()

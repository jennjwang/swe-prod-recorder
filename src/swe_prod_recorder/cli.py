import argparse
import asyncio
import os
import platform
import signal
import sys
import threading

# Fix pynput's AXIsProcessTrusted threading issue on macOS
# pynput's MouseListener tries to lazily import AXIsProcessTrusted in a background thread,
# which fails due to pyobjc's lazy import not being thread-safe. We pre-load it here on the
# main thread before any listeners start.
if platform.system() == "Darwin":
    try:
        from ApplicationServices import AXIsProcessTrusted as _AXIsProcessTrusted
        from pynput._util import darwin

        # Force the lazy load now on main thread
        if hasattr(darwin, "HIServices") and hasattr(
            darwin.HIServices,
            "AXIsProcessTrusted",
        ):
            _ = darwin.HIServices.AXIsProcessTrusted()
        elif hasattr(darwin, "HIServices"):
            darwin.HIServices.AXIsProcessTrusted = _AXIsProcessTrusted
    except Exception as e:
        print(f"Warning: Could not pre-load AXIsProcessTrusted: {e}")

from .gum import gum
from .observers import Screen


def parse_args():
    parser = argparse.ArgumentParser(
        description="SWE Productivity Recorder - Screen activity recorder for software engineer productivity research"
    )

    # Essential options
    parser.add_argument(
        "--upload-to-gdrive",
        action="store_true",
        help="Upload screenshots to Google Drive and delete local copies",
    )
    parser.add_argument(
        "--record-all-screens",
        "--all",
        dest="record_all_screens",
        action="store_true",
        default=True,
        help="Record all monitors/screens (no window selection needed). Enabled by default.",
    )
    parser.add_argument(
        "--window",
        dest="record_all_screens",
        action="store_false",
        help="Use interactive window selection instead of recording all screens.",
    )
    parser.add_argument(
        "--inactivity-timeout",
        type=float,
        default=45,
        help="Stop recording after N minutes of inactivity (default: 45)",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug logging",
    )

    parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to organize screen recording data under data/pr_{pr} (use issue number if PRs are not available yet, or 0 for onboarding)",
    )

    return parser.parse_args()


async def _async_main(
    screen_observer,
    stop_event,
    data_directory,
    checkpoint_db_on_exit=False,
):
    """Run async event loop in background thread.

    This manages the database, observer workers, and update processing.
    """
    user_name = "anonymous"  # Default user name

    try:
        async with gum(
            user_name,
            screen_observer,
            data_directory=data_directory,
            checkpoint_db_on_exit=checkpoint_db_on_exit,
        ):
            # Wait for stop signal
            while not stop_event.is_set():
                if not screen_observer._running:
                    stop_event.set()
                    break
                await asyncio.sleep(0.1)
    except Exception as e:
        print(f"Error in async loop: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main entry point.

    Architecture:
    - Main thread: Runs pynput listeners (macOS-safe for TIS APIs)
    - Background thread: Runs asyncio event loop (database, observers, updates)

    This architecture ensures pynput's keyboard listener (which calls macOS TIS
    APIs) runs on the main thread, avoiding dispatch queue assertion failures.
    """
    args = parse_args()

    # Window selection is not supported with multiple monitors — force --all
    if not args.record_all_screens:
        import mss

        with mss.mss() as sct:
            num_monitors = (
                len(sct.monitors) - 1
            )  # monitors[0] is the virtual combined monitor
        if num_monitors > 1:
            print(
                f"\n⚠️  Multiple monitors detected ({num_monitors}). "
                "Window selection is not supported with multiple monitors."
            )
            print("Falling back to --all (recording all screens).")
            input("\nPress Enter to continue...")
            args.record_all_screens = True

    current_platform = platform.system()
    is_macos = current_platform == "Darwin"
    is_linux = current_platform == "Linux"
    is_wayland = is_linux and (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )

    if is_wayland and os.geteuid() == 0:
        print("Run `swe-prod-recorder` as your user, not as root, on Wayland.")
        print("The recorder will request sudo only for /dev/input if needed.")
        sys.exit(1)

    # Default to --all on Linux
    if is_linux and not args.record_all_screens:
        args.record_all_screens = True

    if args.upload_to_gdrive:
        try:
            from .auth.google_drive import (
                USE_GDRIVE,
                initialize_google_drive,
                _generate_client_secrets_from_env,
            )
        except ImportError as exc:
            print(f"Google Drive upload requested but PyDrive is not available: {exc}")
            sys.exit(1)

        if not USE_GDRIVE:
            print("Google Drive upload requested but PyDrive is not installed.")
            sys.exit(1)

        # Try to auto-generate client_secrets.json from .env if it doesn't exist
        secrets_path = os.path.abspath("config/.google_auth/client_secrets.json")
        if not os.path.exists(secrets_path):
            print("client_secrets.json not found, attempting to generate from .env...")
            if _generate_client_secrets_from_env():
                print("✅ Generated client_secrets.json from .env")
            else:
                print(f"❌ Could not generate client_secrets.json")
                print("\nPlease either:")
                print("  1. Create a .env file with GOOGLE_CLIENT_ID, GOOGLE_PROJECT_ID, and GOOGLE_CLIENT_SECRET")
                print("     (See config/.env.example for template)")
                print("  2. Or place client_secrets.json manually in config/.google_auth/ directory")
                sys.exit(1)

        # Authenticate with Google Drive (will use cached credentials if available)
        print("\nAuthenticating with Google Drive...")
        try:
            initialize_google_drive("config/.google_auth/client_secrets.json")
            print("✅ Google Drive authentication successful")
        except Exception as exc:
            print(f"❌ Google Drive authentication failed: {exc}")
            sys.exit(1)

    data_directory = f"data/pr_{args.pr}"
    screenshots_dir = f"{data_directory}/screenshots"
    screen_observer = Screen(
        upload_to_gdrive=args.upload_to_gdrive,
        record_all_screens=args.record_all_screens,
        inactivity_timeout=args.inactivity_timeout * 60,
        debug=args.debug,
        start_listeners_on_main_thread=is_macos,
        screenshots_dir=screenshots_dir,
    )
    if is_wayland:
        screen_observer.poll_wayland_cursor_position()

    # Display user warning and instructions
    print("\n" + "=" * 70)
    print("⚠️  BEFORE YOU BEGIN RECORDING")
    print("=" * 70)
    print("\nPlease make sure your workspace is clean and contains only")
    print("study-related materials.")
    print("\nClose all personal tabs, folders, and unrelated applications.")

    if args.record_all_screens:
        print("\nALL monitors/screens will be recorded — everything on screen")
        print("will be captured.")
    else:
        print("\nOnly the window you select will be recorded — activity outside")
        print("it will be ignored.")

    print("\nYou can pause or stop recording at any time using Ctrl + C")
    print("in the terminal.")
    print(
        f"\nRecording will automatically stop after {args.inactivity_timeout} minutes"
    )
    print("of inactivity.")
    print("\nWhen finished, review your recording and delete anything you")
    print("don't want to share.")
    print("\n" + "=" * 70)

    if is_wayland and screen_observer.needs_wayland_input_helper():
        print("\nWayland input capture may need temporary sudo access to /dev/input.")
        if not screen_observer.preflight_wayland_input_helper():
            print("Wayland input helper authorization was not completed.")
            sys.exit(1)

    try:
        input("\nPress Enter to confirm and start recording...")
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        sys.exit(130)
    # print("\nStarting recording...\n")

    print(f"\n📁 Data will be saved to: {data_directory}/")

    # Coordination between main and background threads
    stop_event = threading.Event()

    # Launch asyncio event loop in background thread
    async_thread = threading.Thread(
        target=lambda: asyncio.run(
            _async_main(
                screen_observer,
                stop_event,
                data_directory,
                checkpoint_db_on_exit=is_wayland,
            )
        ),
        daemon=True,
        name="AsyncIOThread",
    )
    async_thread.start()

    # Give async loop time to initialize
    import time
    time.sleep(0.5)

    # Set up Ctrl+C handler
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
        stop_event.set()
        screen_observer.stop_listeners_sync()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        if is_macos:
            # Run pynput listeners on main thread (blocks until stopped)
            screen_observer.run_listeners_on_main_thread()
        else:
            import time

            while async_thread.is_alive() and not stop_event.is_set():
                if is_wayland:
                    screen_observer.poll_wayland_cursor_position()
                time.sleep(0.1)

        # Clean shutdown
        stop_event.set()
        screen_observer.stop_listeners_sync()
        async_thread.join(timeout=5)

    except KeyboardInterrupt:
        print("\n\nShutting down...")
        stop_event.set()
        screen_observer.stop_listeners_sync()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        stop_event.set()
        screen_observer.stop_listeners_sync()

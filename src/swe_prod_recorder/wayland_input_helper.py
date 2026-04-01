import glob
import os
import select
import sys

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
except Exception as exc:  # pragma: no cover - import depends on runtime env
    print(f"ERROR\tfailed to import evdev: {exc}", flush=True)
    raise SystemExit(1)


def _normalize_evdev_keycode(keycode) -> str | None:
    if isinstance(keycode, list):
        keycode = keycode[0]
    if not isinstance(keycode, str) or not keycode.startswith("KEY_"):
        return None
    return keycode[4:].lower()


def _emit(line: str) -> bool:
    try:
        print(line, flush=True)
        return True
    except BrokenPipeError:
        return False


def _open_keyboards() -> list[InputDevice]:
    devices: list[InputDevice] = []
    for path in list_devices():
        device = InputDevice(path)
        keys = set(device.capabilities().get(ecodes.EV_KEY, []))
        if ecodes.KEY_A in keys and ecodes.BTN_LEFT not in keys:
            devices.append(device)
        else:
            device.close()
    return devices


def _open_mice() -> list[InputDevice]:
    devices: list[InputDevice] = []
    candidate_paths = list(list_devices()) + glob.glob("/dev/input/by-path/*event-mouse")
    seen_paths: set[str] = set()
    for path in candidate_paths:
        device = None
        try:
            real_path = os.path.realpath(path)
            if real_path in seen_paths:
                continue
            seen_paths.add(real_path)

            device = InputDevice(real_path)
            capabilities = device.capabilities(absinfo=False)
            keys = set(capabilities.get(ecodes.EV_KEY, []))
            rels = set(capabilities.get(ecodes.EV_REL, []))
            abss = set(capabilities.get(ecodes.EV_ABS, []))
            if (
                ecodes.BTN_LEFT in keys
                or ecodes.BTN_RIGHT in keys
                or ecodes.BTN_MIDDLE in keys
                or ecodes.BTN_SIDE in keys
                or ecodes.REL_X in rels
                or ecodes.REL_Y in rels
                or ecodes.REL_WHEEL in rels
                or ecodes.REL_HWHEEL in rels
                or ecodes.ABS_X in abss
                or ecodes.ABS_Y in abss
            ):
                devices.append(device)
                device = None
        except Exception:
            pass
        finally:
            if device is not None:
                device.close()
    return devices


def main() -> int:
    keyboard_devices = _open_keyboards()
    mouse_devices = _open_mice()
    devices = keyboard_devices + mouse_devices
    if not devices:
        _emit("ERROR\tno input devices")
        return 1

    if not _emit("READY\t" + ",".join(device.path for device in devices)):
        return 0

    button_map = {
        ecodes.BTN_LEFT: "click_left",
        ecodes.BTN_RIGHT: "click_right",
        ecodes.BTN_MIDDLE: "click_middle",
        ecodes.BTN_SIDE: "click_back",
    }

    try:
        while True:
            readable, _, _ = select.select(devices, [], [], 0.5)
            for device in readable:
                for event in device.read():
                    if device in keyboard_devices:
                        if event.type != ecodes.EV_KEY or event.value != 1:
                            continue
                        key_name = _normalize_evdev_keycode(categorize(event).keycode)
                        if key_name is not None:
                            if not _emit(f"KEY\t{key_name}"):
                                return 0
                    elif device in mouse_devices:
                        if event.type == ecodes.EV_KEY and event.code in button_map:
                            phase = (
                                "down"
                                if event.value == 1
                                else "up"
                                if event.value == 0
                                else None
                            )
                            if phase is not None:
                                if not _emit(
                                    f"CLICK\t{button_map[event.code]}\t{phase}"
                                ):
                                    return 0
                        elif event.type == ecodes.EV_REL:
                            if event.code == ecodes.REL_WHEEL and event.value:
                                if not _emit(f"SCROLL\t0.0\t{float(event.value)}"):
                                    return 0
                            elif event.code == ecodes.REL_HWHEEL and event.value:
                                if not _emit(f"SCROLL\t{float(event.value)}\t0.0"):
                                    return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for device in devices:
            device.close()


if __name__ == "__main__":
    raise SystemExit(main())

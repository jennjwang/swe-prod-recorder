import select
import sys

from evdev import InputDevice, categorize, ecodes, list_devices


def _normalize_evdev_keycode(keycode) -> str | None:
    if isinstance(keycode, list):
        keycode = keycode[0]
    if not isinstance(keycode, str) or not keycode.startswith("KEY_"):
        return None
    return keycode[4:].lower()


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


def main() -> int:
    devices = _open_keyboards()
    if not devices:
        print("ERROR\tno keyboard devices", flush=True)
        return 1

    print("READY\t" + ",".join(device.path for device in devices), flush=True)

    try:
        while True:
            readable, _, _ = select.select(devices, [], [], 0.5)
            for device in readable:
                for event in device.read():
                    if event.type != ecodes.EV_KEY or event.value != 1:
                        continue
                    key_name = _normalize_evdev_keycode(categorize(event).keycode)
                    if key_name is not None:
                        print(f"KEY\t{key_name}", flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        for device in devices:
            device.close()


if __name__ == "__main__":
    raise SystemExit(main())

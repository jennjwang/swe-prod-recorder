#!/usr/bin/python3

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

import dbus
from dbus.mainloop.glib import DBusGMainLoop

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst


class WaylandScreenCastHelper:
    REQUEST_IFACE = "org.freedesktop.portal.Request"
    SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
    SESSION_IFACE = "org.freedesktop.portal.Session"

    def __init__(self, *, output_dir: str, fps: int) -> None:
        DBusGMainLoop(set_as_default=True)
        Gst.init(None)

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fps = max(1, int(fps))

        self.bus = dbus.SessionBus()
        self.portal = self.bus.get_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        self.loop = GLib.MainLoop()
        self.sender_name = re.sub(r"\.", "_", self.bus.get_unique_name()[1:])
        self.request_token_counter = 0
        self.session_token_counter = 0
        self.session_handle: str | None = None
        self.stream_states: list[dict] = []
        self.pipelines: list[Gst.Pipeline] = []

    def _emit(self, kind: str, payload: str) -> None:
        print(f"{kind}\t{payload}", flush=True)

    def _new_request_path(self) -> tuple[str, str]:
        self.request_token_counter += 1
        token = f"u{self.request_token_counter}"
        path = (
            f"/org/freedesktop/portal/desktop/request/{self.sender_name}/{token}"
        )
        return path, token

    def _new_session_path(self) -> tuple[str, str]:
        self.session_token_counter += 1
        token = f"u{self.session_token_counter}"
        path = (
            f"/org/freedesktop/portal/desktop/session/{self.sender_name}/{token}"
        )
        return path, token

    def _screen_cast_call(self, method, callback, *args, options: dict | None = None) -> None:
        request_path, request_token = self._new_request_path()
        self.bus.add_signal_receiver(
            callback,
            "Response",
            self.REQUEST_IFACE,
            "org.freedesktop.portal.Desktop",
            request_path,
        )

        request_options = dbus.Dictionary(signature="sv")
        for key, value in (options or {}).items():
            request_options[key] = value
        request_options["handle_token"] = request_token

        method(
            *(args + (request_options,)),
            dbus_interface=self.SCREENCAST_IFACE,
        )

    def _write_stream_frame(self, stream_state: dict, jpeg_bytes: bytes) -> None:
        stream_dir = Path(stream_state["dir"])
        stream_dir.mkdir(parents=True, exist_ok=True)

        sequence = stream_state["sequence"] + 1
        stream_state["sequence"] = sequence
        frame_path = stream_dir / f"frame-{sequence:06d}.jpg"
        temp_path = frame_path.with_suffix(".tmp")

        temp_path.write_bytes(jpeg_bytes)
        os.replace(temp_path, frame_path)

        stream_state["paths"].append(frame_path)
        while len(stream_state["paths"]) > 4:
            old_path = stream_state["paths"].pop(0)
            try:
                old_path.unlink()
            except FileNotFoundError:
                pass

        meta_path = stream_dir / "latest.json"
        meta_tmp_path = stream_dir / "latest.json.tmp"
        meta_tmp_path.write_text(
            json.dumps(
                {
                    "sequence": sequence,
                    "path": str(frame_path),
                    "ts": time.time(),
                }
            ),
            encoding="utf-8",
        )
        os.replace(meta_tmp_path, meta_path)

    def _on_gst_message(self, _bus, message, stream_state: dict) -> None:
        if message.type == Gst.MessageType.EOS:
            self._emit(
                "ERROR",
                f"stream {stream_state['node_id']} ended unexpectedly",
            )
            self.terminate()
            return

        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            details = debug or str(err)
            self._emit(
                "ERROR",
                f"stream {stream_state['node_id']} failed: {details}",
            )
            self.terminate()

    def _on_new_sample(self, sink, stream_state: dict):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR

        buffer = sample.get_buffer()
        ok, mapped = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR

        try:
            self._write_stream_frame(stream_state, bytes(mapped.data))
        finally:
            buffer.unmap(mapped)

        return Gst.FlowReturn.OK

    def _start_stream_pipeline(self, stream_state: dict) -> None:
        fd = self.portal.OpenPipeWireRemote(
            self.session_handle,
            dbus.Dictionary(signature="sv"),
            dbus_interface=self.SCREENCAST_IFACE,
        ).take()

        pipeline = Gst.parse_launch(
            " ! ".join(
                [
                    (
                        "pipewiresrc "
                        f"fd={fd} "
                        f"path={stream_state['node_id']} "
                        "client-name=swe-prod-recorder "
                        "keepalive-time=1000 "
                        "always-copy=true"
                    ),
                    "queue leaky=downstream max-size-buffers=2",
                    "videoconvert",
                    "videorate",
                    f"video/x-raw,framerate={self.fps}/1",
                    "jpegenc quality=80",
                    "appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false",
                ]
            )
        )

        sink = pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample, stream_state)

        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_gst_message, stream_state)

        pipeline.set_state(Gst.State.PLAYING)
        self.pipelines.append(pipeline)

    def _close_session(self) -> None:
        if not self.session_handle:
            return

        try:
            session = self.bus.get_object(
                "org.freedesktop.portal.Desktop",
                self.session_handle,
            )
            session.Close(dbus_interface=self.SESSION_IFACE)
        except Exception:
            pass
        finally:
            self.session_handle = None

    def terminate(self, *_args) -> None:
        for pipeline in self.pipelines:
            try:
                pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        self.pipelines.clear()
        self._close_session()
        if self.loop.is_running():
            self.loop.quit()

    def _on_create_session_response(self, response, results) -> None:
        if response != 0:
            self._emit("ERROR", f"create session failed: {response}")
            self.terminate()
            return

        self.session_handle = str(results["session_handle"])
        self._screen_cast_call(
            self.portal.SelectSources,
            self._on_select_sources_response,
            self.session_handle,
            options={
                "multiple": dbus.Boolean(True),
                "types": dbus.UInt32(1),
                "cursor_mode": dbus.UInt32(2),
            },
        )

    def _on_select_sources_response(self, response, _results) -> None:
        if response != 0:
            self._emit("ERROR", f"select sources failed: {response}")
            self.terminate()
            return

        self._screen_cast_call(
            self.portal.Start,
            self._on_start_response,
            self.session_handle,
            "",
        )

    def _on_start_response(self, response, results) -> None:
        if response != 0:
            self._emit("ERROR", f"start screencast failed: {response}")
            self.terminate()
            return

        streams = list(results.get("streams", []))
        if not streams:
            self._emit("ERROR", "portal returned no screencast streams")
            self.terminate()
            return

        ready_payload = []
        for index, (node_id, properties) in enumerate(streams, start=1):
            position = tuple(properties.get("position", (0, 0)))
            size = tuple(properties.get("size", (0, 0)))
            stream_dir = self.output_dir / f"stream-{index}"
            region = {
                "left": int(position[0]),
                "top": int(position[1]),
                "width": int(size[0]),
                "height": int(size[1]),
            }
            stream_state = {
                "node_id": int(node_id),
                "dir": str(stream_dir),
                "region": region,
                "sequence": 0,
                "paths": [],
            }
            self.stream_states.append(stream_state)
            self._start_stream_pipeline(stream_state)
            ready_payload.append(
                {
                    "node_id": stream_state["node_id"],
                    "dir": stream_state["dir"],
                    "region": stream_state["region"],
                }
            )

        self._emit("READY", json.dumps({"streams": ready_payload}))

    def run(self) -> int:
        session_path, session_token = self._new_session_path()
        self._screen_cast_call(
            self.portal.CreateSession,
            self._on_create_session_response,
            options={"session_handle_token": session_token},
        )

        signal.signal(signal.SIGINT, self.terminate)
        signal.signal(signal.SIGTERM, self.terminate)

        try:
            self.loop.run()
            return 0
        finally:
            self.terminate()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fps", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    helper = WaylandScreenCastHelper(output_dir=args.output_dir, fps=args.fps)
    return helper.run()


if __name__ == "__main__":
    raise SystemExit(main())

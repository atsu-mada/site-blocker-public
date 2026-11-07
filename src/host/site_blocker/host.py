"""Native Messaging host for the Site Blocker extension.

Chrome starts this process when the extension connects. It sends the extension the site list from the list
file and the off/on state from state.json, and writes the extension's status reports to status.json for
`blockctl`. It never opens a network port.
"""

from __future__ import annotations

import json
import logging
import struct
import sys
import threading
import time
from typing import Any, BinaryIO

from . import common

POLL_SECONDS = 2.0
PING_SECONDS = 15.0
MAX_MESSAGE_BYTES = 1024 * 1024


class Host:
    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self.reader = reader
        self.writer = writer
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.last_sent: str | None = None

    def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        with self.lock:
            self.writer.write(struct.pack("<I", len(data)) + data)
            self.writer.flush()

    def read(self) -> dict[str, Any] | None:
        header = self.reader.read(4)
        if len(header) < 4:
            return None
        (size,) = struct.unpack("<I", header)
        if size > MAX_MESSAGE_BYTES:
            raise ValueError(f"message too large: {size}")
        body = self.reader.read(size)
        if len(body) < size:
            return None
        message = json.loads(body.decode("utf-8"))
        return message if isinstance(message, dict) else {}

    def config(self) -> dict[str, Any]:
        listed = common.load_list()
        state = common.read_state()
        return {"type": "config", "sites": listed["sites"], "listUpdatedAt": listed.get("updated_at_ms"),
                "listErrors": listed["errors"], "offUntil": int(state.get("off_until") or 0)}

    def send_config(self, force: bool = False) -> None:
        message = self.config()
        key = json.dumps(message, sort_keys=True)
        if force or key != self.last_sent:
            self.send(message)
            self.last_sent = key

    def handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "status":
            common.write_json(common.status_path(), {**message, "received_at_ms": common.now_ms()})
        elif kind == "pause":
            until = int(message.get("until") or 0)
            limit = common.now_ms() + common.CLI_MAX_MINUTES * 60_000
            # The user's own pause from the extension is one more lease; it never shortens another one.
            common.hold_off(common.USER_HOLDER, min(until, limit), str(message.get("by") or "extension"))
            self.send_config(force=True)
        elif kind == "resume":
            # The extension's "turn back on now" button is the user's decision and ends every lease.
            common.release_all(str(message.get("by") or "extension"))
            self.send_config(force=True)

    def read_loop(self) -> None:
        try:
            while not self.closed.is_set():
                message = self.read()
                if message is None:
                    break
                self.handle(message)
        except Exception:  # noqa: BLE001 - a broken pipe or bad message ends the host; Chrome restarts it
            logging.exception("read loop stopped")
        finally:
            self.closed.set()

    def run(self) -> None:
        threading.Thread(target=self.read_loop, daemon=True).start()
        self.send_config(force=True)
        last_ping = time.monotonic()
        while not self.closed.wait(POLL_SECONDS):
            try:
                self.send_config()
                if time.monotonic() - last_ping >= PING_SECONDS:
                    self.send({"type": "ping"})
                    last_ping = time.monotonic()
            except (BrokenPipeError, OSError):
                break


def main() -> int:
    log_path = common.state_dir() / "host.log"
    if log_path.exists() and log_path.stat().st_size > 512 * 1024:
        log_path.replace(log_path.with_suffix(".log.1"))
    logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("host started (args %s)", sys.argv[1:])
    Host(sys.stdin.buffer, sys.stdout.buffer).run()
    logging.info("host stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

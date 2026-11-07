"""blockctl: turn Site Blocker off for a while, back on, or read its real state.

    blockctl status            # what Chrome actually enforces now, and who holds it off
    blockctl off [--for 20m]   # off for 20 minutes (default), at most 60; it turns itself back on
    blockctl on                # end this session's pause; blocking returns when no other pause is left
    blockctl on --all          # back on now, ending every pause (the user's decision)

Each session holds its own pause (its holder is the Claude Code or Codex session id, or --holder).
`on` ends only that pause, so a scheduled run is not cut short by another session finishing first.

Every command prints one JSON object. `off` and `on` wait until the extension reports the change
(rule count 0 for off, the full list for on) and exit 0 only then. When other pauses are still
running, `on` exits 0 at once with `still_off_for` listing them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any

from . import common

WAIT_SECONDS = 20.0


def parse_minutes(text: str) -> int:
    match = re.fullmatch(r"\s*(\d+)\s*(m|min|h)?\s*", text.lower())
    if not match:
        raise argparse.ArgumentTypeError(f"duration like 20m or 1h: {text!r}")
    minutes = int(match.group(1)) * (60 if match.group(2) == "h" else 1)
    if not 1 <= minutes <= common.CLI_MAX_MINUTES:
        raise argparse.ArgumentTypeError(f"between 1 and {common.CLI_MAX_MINUTES} minutes")
    return minutes


def snapshot() -> dict[str, Any]:
    status = common.read_json(common.status_path(), {})
    state = common.read_state()
    now = common.now_ms()
    received = int(status.get("received_at_ms") or 0)
    off_until = int(state.get("off_until") or 0)
    leases = common.live_leases(state, now)
    return {
        "connected": bool(received) and now - received < common.CONNECTED_WITHIN_SECONDS * 1000,
        "enabled": status.get("enabled"),
        "active_rules": status.get("activeRules"),
        "expected_rules": status.get("expectedRules"),
        "requested_off_until": off_until if off_until > now else 0,
        "requested_off_until_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(off_until / 1000)) if off_until > now else None,
        "holders": {k: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v / 1000)) for k, v in sorted(leases.items())},
        "status_age_seconds": round((now - received) / 1000, 1) if received else None,
        "list_errors": status.get("listErrors") or [],
        "host_error": status.get("hostError"),
        "_received_at_ms": received,
    }


def wait_for(predicate, since_ms: int) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_SECONDS
    snap = snapshot()
    while time.monotonic() < deadline:
        snap = snapshot()
        if snap["_received_at_ms"] > since_ms and predicate(snap):
            return {**snap, "ok": True}
        time.sleep(0.5)
    return {**snap, "ok": False, "reason": "the extension did not confirm the change (Chrome closed, or the extension is not connected)"}


def emit(result: dict[str, Any]) -> int:
    result = {k: v for k, v in result.items() if not k.startswith("_")}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok", True) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blockctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    off = sub.add_parser("off")
    off.add_argument("--for", dest="minutes", type=parse_minutes, default=common.CLI_DEFAULT_MINUTES)
    off.add_argument("--no-wait", action="store_true")
    off.add_argument("--holder", default=None, help="who holds this pause (default: the session id)")
    on = sub.add_parser("on")
    on.add_argument("--no-wait", action="store_true")
    on.add_argument("--holder", default=None, help="whose pause to end (default: the session id)")
    on.add_argument("--all", action="store_true", help="end every pause and block now")
    args = parser.parse_args(argv)

    if args.command == "status":
        snap = snapshot()
        snap["ok"] = bool(snap["connected"]) and (
            snap["enabled"] is False or (snap["active_rules"] or 0) == (snap["expected_rules"] or -1))
        code = emit(snap)
        return code if snap["connected"] else 3

    started = common.now_ms()
    if args.command == "off":
        until = started + args.minutes * 60_000
        common.hold_off(args.holder or common.default_holder(), until, "blockctl")
        if args.no_wait:
            return emit({**snapshot(), "ok": True, "requested": "off"})
        already = snapshot()
        if already["connected"] and already["enabled"] is False and already["active_rules"] == 0:
            # Another session already holds blocking off; Chrome has nothing new to report.
            return emit({**already, "ok": True})
        return emit(wait_for(lambda s: s["enabled"] is False and s["active_rules"] == 0, started))

    if args.all:
        common.release_all("blockctl --all")
    else:
        state = common.release(args.holder or common.default_holder(), "blockctl")
        others = common.live_leases(state)
        if others:
            # Someone else still needs blocking off; leave it off and say who.
            return emit({**snapshot(), "ok": True, "requested": "on", "still_off_for": sorted(others)})
    if args.no_wait:
        return emit({**snapshot(), "ok": True, "requested": "on"})
    return emit(wait_for(lambda s: s["enabled"] is True and (s["active_rules"] or 0) > 0
                         and s["active_rules"] == s["expected_rules"], started))


if __name__ == "__main__":
    raise SystemExit(main())

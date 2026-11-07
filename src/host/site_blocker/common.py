"""Shared paths, list parsing, and state files for the Site Blocker native host and `blockctl`."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

HOST_NAME = "local.site_blocker.host"
DEFAULT_LIST = "~/.config/site-blocker/sites.md"
# The list sits under a heading 「Blocked sites」 or 「ブロックするサイト」 (a leading "> " is allowed, as in an
# Obsidian callout). A file without that heading is read as a whole.
LIST_HEADING = re.compile(r"^(>\s*)?#{1,6}\s*(blocked sites|ブロックするサイト)\s*$", re.IGNORECASE)
HEADING = re.compile(r"^(>\s*)?#")
# Same entry grammar as core.js: "example.com", "*.example.com", or "example.com/path".
ENTRY = re.compile(r"^(\*\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(/[^\s?#]*)?$")
MAX_ENTRIES = 1000
CLI_DEFAULT_MINUTES = 20
CLI_MAX_MINUTES = 60
CONNECTED_WITHIN_SECONDS = 45


def state_dir() -> Path:
    path = Path(setting("SITE_BLOCKER_STATE_DIR") or "~/.local/state/site-blocker").expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def env_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "site-blocker" / "env"


def setting(name: str) -> str | None:
    """A variable from the environment, else from the env file install.py writes (Chrome passes no shell variables)."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        lines = env_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    found = [line.split("=", 1)[1].strip() for line in lines if line.startswith(f"{name}=")]
    return found[-1] if found and found[-1] else None


def list_note_path() -> Path:
    """The block list: $SITE_BLOCKER_LIST, the env file's SITE_BLOCKER_LIST, or ~/.config/site-blocker/sites.md."""
    return Path(setting("SITE_BLOCKER_LIST") or DEFAULT_LIST).expanduser()


def normalize_entry(raw: str) -> str | None:
    text = raw.strip().strip("`").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    match = ENTRY.match(text)
    if not match:
        return None
    return (match.group(1) or "") + match.group(2) + (match.group(3) or "").rstrip("/")


def parse_note(text: str) -> tuple[list[str], list[str]]:
    """Read the bullet lines under the list heading until the next heading (or every bullet when there is no heading).

    A line is `- <site>`, optionally followed by a space and a memo in parentheses or after `#`.
    """
    lines = text.splitlines()
    has_heading = any(LIST_HEADING.match(line) for line in lines)
    sites: list[str] = []
    errors: list[str] = []
    inside = not has_heading
    for number, line in enumerate(lines, 1):
        if has_heading and LIST_HEADING.match(line):
            inside = True
            continue
        if has_heading and inside and HEADING.match(line):
            break
        if not inside or not line.startswith("- "):
            continue
        token = re.split(r"\s+|（|\(|#", line[2:].strip(), maxsplit=1)[0]
        entry = normalize_entry(token)
        if entry is None:
            errors.append(f"line {number} is not a site: {line[:80]}")
        elif entry not in sites:
            sites.append(entry)
    return sites[:MAX_ENTRIES], errors


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(handle.name, path)


def state_path() -> Path:
    return state_dir() / "state.json"


def status_path() -> Path:
    return state_dir() / "status.json"


def cache_path() -> Path:
    return state_dir() / "list-cache.json"


def read_state() -> dict[str, Any]:
    state = read_json(state_path(), {})
    return state if isinstance(state, dict) else {}


def write_state(off_until_ms: int, by: str, leases: dict[str, int] | None = None) -> dict[str, Any]:
    state = {"off_until": int(off_until_ms), "by": by, "updated_at_ms": now_ms(), "leases": leases or {}}
    write_json(state_path(), state)
    return state


# Several sessions may need blocking off at the same time (a scheduled inbox run and a manual Chrome task).
# Each one holds its own lease; blocking comes back only when no lease is left (or the last one expires).
HOLDER_ENV = ("SITE_BLOCKER_HOLDER", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID")
USER_HOLDER = "user"


def default_holder() -> str:
    for name in HOLDER_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            return value[:120]
    return "default"


@contextmanager
def state_lock():
    lock = state_dir() / "state.lock"
    with open(lock, "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def live_leases(state: dict[str, Any], now: int | None = None) -> dict[str, int]:
    now = now_ms() if now is None else now
    raw = state.get("leases")
    leases = {str(k): int(v) for k, v in raw.items() if isinstance(v, (int, float))} if isinstance(raw, dict) else {}
    if not raw and int(state.get("off_until") or 0) > now:
        # A pause written before leases existed is kept under its writer's name.
        leases = {str(state.get("by") or "legacy"): int(state["off_until"])}
    return {k: v for k, v in leases.items() if v > now}


def hold_off(holder: str, until_ms: int, by: str) -> dict[str, Any]:
    """Add or replace one holder's lease; blocking stays off until the latest live lease ends."""
    with state_lock():
        leases = live_leases(read_state())
        leases[holder] = int(until_ms)
        return write_state(max(leases.values()), by, leases)


def release(holder: str, by: str) -> dict[str, Any]:
    """End one holder's lease; other holders' leases keep blocking off."""
    with state_lock():
        leases = live_leases(read_state())
        leases.pop(holder, None)
        return write_state(max(leases.values(), default=0), by, leases)


def release_all(by: str) -> dict[str, Any]:
    with state_lock():
        return write_state(0, by, {})


def now_ms() -> int:
    return int(time.time() * 1000)


def load_list() -> dict[str, Any]:
    """The current list, falling back to the last good one when the note is missing, broken, or empty."""
    cached = read_json(cache_path(), {})
    try:
        note = list_note_path()
        text = note.read_text(encoding="utf-8")
        sites, errors = parse_note(text)
        mtime_ms = int(note.stat().st_mtime * 1000)
    except OSError as error:
        return {"sites": cached.get("sites", []), "updated_at_ms": cached.get("updated_at_ms"),
                "errors": [f"cannot read the list file: {error}"]}
    if not sites:
        return {"sites": cached.get("sites", []), "updated_at_ms": cached.get("updated_at_ms"),
                "errors": errors + ["the list is empty; keeping the last good list"]}
    if cached.get("sites") != sites:
        write_json(cache_path(), {"sites": sites, "updated_at_ms": mtime_ms})
    return {"sites": sites, "updated_at_ms": mtime_ms, "errors": errors}

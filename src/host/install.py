"""Register the Site Blocker native messaging host with Chrome and put blockctl on PATH.

    python3 src/host/install.py --extension-id <id from chrome://extensions> [--browser chrome] [--dry-run]

It writes three things:
  - the native messaging manifest for the chosen browser (it allows only the given extension id),
  - ~/.config/site-blocker/env with the Python to use and the list file (Chrome starts the host without your
    shell's variables, so both the host and blockctl read them from here),
  - ~/.local/bin/blockctl as a link to src/host/bin/blockctl.
It also creates the list file from config/sites.example.md when it does not exist yet.
Run it again after moving the repository, because Chrome keeps the launcher's absolute path.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from site_blocker import common  # noqa: E402

HOME = Path.home()
HOST_DIRS = {
    "darwin": {
        "chrome": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
        "chrome-beta": "Library/Application Support/Google/Chrome Beta/NativeMessagingHosts",
        "chromium": "Library/Application Support/Chromium/NativeMessagingHosts",
        "brave": "Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "edge": "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
    },
    "linux": {
        "chrome": ".config/google-chrome/NativeMessagingHosts",
        "chrome-beta": ".config/google-chrome-beta/NativeMessagingHosts",
        "chromium": ".config/chromium/NativeMessagingHosts",
        "brave": ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
        "edge": ".config/microsoft-edge/NativeMessagingHosts",
    },
}
EXTENSION_ID = re.compile(r"^[a-p]{32}$")


def main() -> int:
    platform = "darwin" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else None
    if platform is None:
        print("only macOS and Linux are supported", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extension-id", required=True, help="the 32-letter id chrome://extensions shows")
    parser.add_argument("--browser", choices=sorted(HOST_DIRS[platform]), default="chrome")
    parser.add_argument("--hosts-dir", type=Path, help="write the manifest here instead (for example a test profile)")
    parser.add_argument("--list", type=Path, default=Path(common.DEFAULT_LIST).expanduser(), help="the block list file")
    parser.add_argument("--python", default=sys.executable, help="the Python that runs the host (default: this one)")
    parser.add_argument("--bin-dir", type=Path, default=HOME / ".local/bin")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not EXTENSION_ID.match(args.extension_id):
        print(f"not an extension id: {args.extension_id!r}", file=sys.stderr)
        return 1

    launcher = HERE / "bin" / "site-blocker-host"
    hosts_dir = args.hosts_dir.expanduser() if args.hosts_dir else HOME / HOST_DIRS[platform][args.browser]
    target = hosts_dir / f"{common.HOST_NAME}.json"
    env_file = common.env_file()
    list_file = args.list.expanduser().resolve()
    link = args.bin_dir.expanduser() / "blockctl"
    manifest = {
        "name": common.HOST_NAME,
        "description": "Site Blocker: the block list file and the blockctl off/on state.",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{args.extension_id}/"],
    }
    print(json.dumps({"manifest": str(target), "launcher": str(launcher), "env": str(env_file),
                      "list": str(list_file), "python": args.python, "blockctl": str(link),
                      "dry_run": args.dry_run}, indent=2))
    if args.dry_run:
        return 0

    hosts_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    # Plain KEY=value lines (no quoting); a variable set in the environment wins over this file.
    env_file.write_text(f"SITE_BLOCKER_PYTHON={args.python}\nSITE_BLOCKER_LIST={list_file}\n", encoding="utf-8")
    if not list_file.exists():
        list_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "config" / "sites.example.md", list_file)
        print(f"created {list_file} from config/sites.example.md; edit it to choose your sites")
    for script in (launcher, HERE / "bin" / "blockctl"):
        script.chmod(script.stat().st_mode | 0o111)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or not link.exists():
        link.unlink(missing_ok=True)
        link.symlink_to(HERE / "bin" / "blockctl")
    else:
        print(f"{link} exists and is not a link; left as it is", file=sys.stderr)
        return 1
    print("done: reload the extension in chrome://extensions so it connects to the host")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

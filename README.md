# Site Blocker

A small Chrome extension that blocks the sites in a plain Markdown list, plus a `blockctl` command and an agent skill so that **Claude Code** or **Codex** can turn blocking off for a task and back on when it ends – without clicking anything in the browser.

- **Every off has a deadline.** Blocking turns itself back on when the time runs out, even if a script or an agent stops halfway.
- **Turning it off by hand takes a moment.** The toolbar popup and the control page wait 10 seconds before a pause starts (cancel with "やめる" or Esc), and allow at most 30 minutes.
- **`blockctl` checks what Chrome really does.** The extension reports how many blocking rules Chrome holds, and `blockctl off` / `on` exit 0 only after that count confirms the change.
- **Several sessions can share it.** Each agent session holds its own pause; one session turning blocking back on does not cut another session's work short.
- **Nothing leaves your machine.** The extension talks to a local program through Chrome's native messaging; no network port is opened and nothing is sent anywhere.

日本語の説明は [docs/README.ja.md](docs/README.ja.md) にあります。The extension's screens are in Japanese.

## Requirements

- macOS or Linux, with Google Chrome 120 or later (Chromium, Brave, and Edge should work too; only Chrome on macOS has been tested).
- Python 3.9 or later (the `python3` that ships with macOS is enough). No packages are needed.
- For the skill: Claude Code or Codex.
- Optional: Node.js 18+ to run the extension tests, Pillow to rebuild the icons.

## Install

### 1. Get the code

```bash
git clone https://github.com/atsu-mada/site-blocker-public.git
cd site-blocker-public
```

Keep the folder where it is after installing: Chrome stores the absolute path of the host program. If you move it, run step 3 again.

### 2. Load the extension

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose the `src/extension` folder.
3. Copy the extension's **ID** (32 letters, shown on its card). Chrome derives it from the folder path, so it stays the same as long as the folder does not move.

Until the host is installed, the extension blocks the short fallback list in `src/extension/default-sites.json`.

### 3. Install the host and `blockctl`

```bash
python3 src/host/install.py --extension-id <the ID you copied>
```

This writes:

| What | Where |
| --- | --- |
| Native messaging manifest (allows only your extension ID) | `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/local.site_blocker.host.json` on macOS, `~/.config/google-chrome/NativeMessagingHosts/` on Linux |
| Settings for the host (the Python to use, the list file) | `~/.config/site-blocker/env` |
| Your block list, copied from `config/sites.example.md` if it does not exist | `~/.config/site-blocker/sites.md` |
| `blockctl` | `~/.local/bin/blockctl` (a link into this repository) |

Options: `--browser chromium|brave|edge|chrome-beta`, `--list <path>` for another list file (for example a note in your Obsidian vault), `--python <path>`, `--bin-dir <dir>`, `--hosts-dir <dir>` (for a test profile), and `--dry-run` to only print what it would write. Make sure `~/.local/bin` is on your `PATH`.

Then go back to `chrome://extensions` and click the reload button on the Site Blocker card, so the extension connects to the host.

### 4. Check it

```bash
blockctl status
```

You should see `"connected": true`, `"enabled": true`, and `active_rules` equal to `expected_rules`. Open one of the listed sites: it should show the yellow STOP page.

### 5. Install the skill (optional)

Link the skill folder into your client's skills directory, then start a new session.

**Claude Code**

```bash
ln -s "$PWD/src/skills/site-blocker-operator" ~/.claude/skills/site-blocker-operator
```

Call it with `/site-blocker-operator`, or let other tasks use it when they need blocked sites.

**Codex**

```bash
ln -s "$PWD/src/skills/site-blocker-operator" ~/.codex/skills/site-blocker-operator
```

Use the skills folder your Codex version reads (`~/.codex/skills` or `~/.agents/skills`). Call it with `$site-blocker-operator`.

Your client may ask for permission the first time it runs `blockctl`. If you want Chrome tasks to include `off` and `on` without asking each time, say so in your own `CLAUDE.md` or `AGENTS.md`.

## Use

### The block list

Edit `~/.config/site-blocker/sites.md` (or the file you passed with `--list`). The host reads it every 2 seconds and sends changes to the extension. Only bullet lines under a heading named **Blocked sites** (or **ブロックするサイト**) are read, up to the next heading; a file without that heading is read as a whole. A leading `> ` is allowed, so the list can sit inside an Obsidian callout.

| Line | Blocks |
| --- | --- |
| `- example.com` | `example.com` and `www.example.com` |
| `- *.example.com` | `example.com` and every subdomain |
| `- example.com/path` | only that path (and below) on that host |

Text after a space, `#`, or `(` is a memo. Lines that cannot be read are skipped and shown in `list_errors`. If the file is missing or empty, the last good list stays in force.

### From the shell or an agent

```bash
blockctl status            # what Chrome enforces now, and who holds it off
blockctl off --for 20m     # off for 20 minutes (default), at most 60; it turns itself back on
blockctl on                # end this session's pause
blockctl on --all          # back on now, ending every pause
```

Each command prints one JSON line. Exit codes: `0` confirmed, `2` not confirmed within 20 seconds (Chrome closed, or the extension is not connected), `3` (`status` only) not connected. The pause holder is the Claude Code or Codex session ID taken from the environment; set `--holder <name>` or `SITE_BLOCKER_HOLDER` in your own scripts.

A pause requested while Chrome is closed takes effect the next time Chrome starts and the host connects.

### By hand

- Click the toolbar icon (vermilion while blocking, grey while off), choose 10, 20, or 30 minutes, and press the button. The pause starts after a 10-second countdown.
- Type `sb` in the address bar and press Enter to open the full-window control page; `sb 10` preselects 10 minutes. You can also bookmark `chrome-extension://<your extension ID>/control.html`.
- "今すぐオンに戻す" turns blocking back on at once and ends every pause.
- The block page has only "← 戻る" (back) and "タブを閉じる" (close the tab); there is deliberately no way to unblock from it, and web pages cannot open the control page.

## How it works

1. When the extension starts, Chrome starts the host (`src/host/bin/site-blocker-host`) and talks to it over stdin/stdout.
2. The host checks the list file and the pause state (`~/.local/state/site-blocker/state.json`) every 2 seconds and sends them to the extension when they change. It asks for a status report every 15 seconds.
3. The extension turns the list into `declarativeNetRequest` dynamic rules that redirect top-level page loads to its block page. While paused it removes all rules and sets a `chrome.alarms` alarm for the deadline.
4. The extension reports the number of rules Chrome actually holds; the host writes it to `status.json`, and `blockctl` waits for that number.
5. As a safety net for pages a service worker serves without a network request, `webNavigation.onCommitted` also checks each navigation against the list.

Runtime files live in `~/.local/state/site-blocker/` (`state.json`, `status.json`, `list-cache.json`, `host.log`); set `SITE_BLOCKER_STATE_DIR` to move them (in the environment or in `~/.config/site-blocker/env`).

## Known limits

- It is a self-control tool, not a security boundary: anyone at the keyboard can disable the extension in `chrome://extensions`.
- Only top-level page loads are blocked; embedded frames and requests from other sites are not.
- Incognito windows are not blocked unless you allow the extension there ("Allow in Incognito").
- Each Chrome profile needs the extension loaded separately. All profiles share one host, one list, and one pause state.
- Windows is not supported (the host uses `fcntl` and a shell launcher).
- The extension is loaded unpacked in developer mode; it is not on the Chrome Web Store.

## Development

```bash
python3 -m unittest discover -s src/test -p 'test_*.py'   # host and blockctl, with a fake extension
node --test src/test/site-blocker.test.mjs                # list rules, manifest, pages
python3 src/tools/build_icons.py                          # rebuild icons (needs Pillow)
```

## Layout

```
src/extension/                  Chrome extension (Manifest V3)
src/host/bin/                   blockctl and the native host launcher
src/host/site_blocker/          host, blockctl, list parsing, pause state (Python)
src/host/install.py             registers the host and links blockctl
src/skills/site-blocker-operator/  agent skill (SKILL.md, agents/openai.yaml for Codex)
src/test/                       tests
src/tools/build_icons.py        toolbar icon generator
config/sites.example.md         example block list
docs/README.ja.md               Japanese guide
```

## License

[MIT](LICENSE)

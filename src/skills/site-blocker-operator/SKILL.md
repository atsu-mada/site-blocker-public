---
name: site-blocker-operator
description: Switch the Site Blocker Chrome extension with its `blockctl` command - `off` before Chrome work on blocked sites and `on` when it ends, `status` to read what Chrome enforces, and `guard` for a periodic check that blocking is on. Use when a task is about to open blocked sites in the user's Chrome, when a Site Blocker block page appears, for a scheduled guard check, or when the user asks to pause, restore, or check blocking. No browser clicks; never edits the block list or the extension.
---

# Site Blocker Operator

- Claude Code invocation: `/site-blocker-operator`
- Codex invocation: `$site-blocker-operator`

Four actions, all through the `blockctl` command: `off` and `on` bracket a task's Chrome work, `status` reads the real state, and `guard` is a periodic check that blocking is on. Other skills and tasks that open blocked sites reference this skill instead of describing their own steps.

## The blocker

- The **Site Blocker** extension (Manifest V3) blocks the sites in the user's list file (by default `~/.config/site-blocker/sites.md`). A local native messaging host passes the list and the off/on state between the file system and Chrome. Setup is in the repository's README.
- A blocked tab shows the extension's block page, `chrome-extension://<extension id>/blocked.html#<original URL>`. Browser tools cannot read or script that page; an error such as "Cannot access a chrome-extension:// URL" is how a blocked tab shows up.
- Every off has a deadline: the extension turns itself back on when it passes, even if a run stops halfway.
- Each session holds its own off. The holder is the Claude Code or Codex session id, read from the environment (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, `CODEX_SESSION_ID`, or `SITE_BLOCKER_HOLDER`), so a scheduled run and a manual Chrome task can overlap: `on` ends only the caller's own off, and blocking returns when no off is left or the latest deadline passes.

## Command

```bash
blockctl status            # what Chrome enforces now, and which sessions hold it off
blockctl off --for 20m     # off for N minutes (1-60, default 20); a second off resets this session's deadline
blockctl on                # end this session's off; blocking returns when no other session holds it off
```

`blockctl` is on `PATH` (the installer links `~/.local/bin/blockctl`). Each call prints one JSON line (`connected`, `enabled`, `active_rules`, `expected_rules`, `requested_off_until_local`, `holders`, `list_errors`, `host_error`, `ok`; `on` adds `still_off_for` when other sessions still hold it off). `blockctl on --all` ends every session's off at once; use it only when the user asks for blocking back now. `--holder <name>` replaces the session id when a script outside a session calls `blockctl`.

| Exit | Meaning |
| --- | --- |
| 0 | Confirmed by the extension: `off` → `enabled: false`, `active_rules: 0`; `on` → `enabled: true`, `active_rules == expected_rules`, or, with `still_off_for`, the caller's own off ended while other sessions keep blocking off |
| 2 | Not confirmed within 20 seconds (Chrome closed, extension not connected) |
| 3 | `status` only: not connected |

Run it with the shell tool, not through the browser. Never edit the state files (`~/.local/state/site-blocker/`), the block list, or the extension's files to change blocking; only `blockctl` does that.

## Action: off

1. Choose the duration: the expected length of the Chrome work plus about 5 minutes, at most 60 (`--for 30m`). Default 20.
2. Run `blockctl off --for <N>m`. Exit 0 → return `off` with `requested_off_until_local`. If `status` already showed `enabled: false` with a deadline later than the planned work, return `already off` without a call.
3. Exit 2 → run `blockctl status` once. If Chrome is not running, the caller may start its Chrome work first and call `off` again once Chrome is up; otherwise return `failed` with both JSON lines.
4. Work that runs past the deadline: run `blockctl off --for <N>m` again before the deadline (it resets it). This is a renewal, not a second `off` in the caller contract.

## Action: on

Run it when the Chrome work ends, whether that work succeeded, failed, or was cancelled, and whatever `off` returned.

1. Run `blockctl on`. Exit 0 → return `on`; with `still_off_for`, return `on (still off for <names>)`: the caller's part is done, and blocking returns when those sessions end or their deadlines pass.
2. Exit 2 → run `blockctl status` once; `enabled: true` with matching rule counts → `on`. Otherwise return `failed` with the JSON lines; the deadline still turns blocking back on by itself, so report the time from `requested_off_until_local`.

The end state is always on once every session has ended its off, even when blocking was off before the caller started. Never run `blockctl on --all` to force it in a caller's run.

## Caller contract

- Order: `off` → the Chrome work → `on`, each once per run (renewals in off step 4 excepted). Put both results in the run's final report.
- `off` returned `failed`: the caller decides whether to continue with the sites it can still open; it must still call `on` at the end.
- The client's permission check refuses `blockctl off`: return `failed` with the reason `refused by the client's permission check`. Do not retry it and do not reach the blocker another way (editing state files, the extension's pages, another browser). Only the user can turn blocking off then (the toolbar button or the extension's control page, with its 10-second wait); say so in the report.
- Whether a request for Chrome work also covers `off` and `on` without asking is the user's decision; record it in the user's own instructions (for example `CLAUDE.md` or `AGENTS.md`). It removes the need to ask; it does not override the client's permission check.
- A block page appears after `off` succeeded: run `blockctl status`. If it reads on, the deadline passed or the user ended every off (`on --all` or the extension's button); in a run the user asked for, call `off` once more; in an unattended run, skip that site and report it as blocked.
- `on` returned `failed`: report it as an unfinished restore with the deadline time.

## Action: guard

For a scheduled check (a Claude Code scheduled task, a Codex automation, cron) or a one-time check the user asks for. It never runs `blockctl off`.

1. Log file: `${SITE_BLOCKER_GUARD_LOG:-$HOME/.local/state/site-blocker/guard.log}`. Append a timestamped `started` record with a unique run ID; if the append fails, stop.
2. Run `blockctl status` and classify:

| Reading | Result | Action |
| --- | --- | --- |
| `connected: true`, `enabled: true`, `active_rules == expected_rules` (> 0) | `on` | none |
| `connected: true`, `enabled: false`, `requested_off_until_local` set | `off by request until <time>` (name the `holders`) | none: a caller or the user is working; the deadline turns it back on |
| `connected: true`, `enabled: false`, no deadline; or `enabled: true` with fewer rules than expected | `off unexpectedly` | run `blockctl on` once, then `blockctl status` again; success only when the second read is `on` |
| exit 3 / `connected: false` | `not connected` | none; Chrome is closed or the extension is not loaded: a failure to report, not success |

3. Note `list_errors` and `host_error` in the record when they are not empty (the list file has lines the host could not read).
4. Append one timestamped terminal record with the run ID: `success` for `on`, `off by request`, or a confirmed `on` after the correction (say whether `blockctl on` ran); `failure` for `not connected` or a correction that did not confirm. An unmatched `started` record is an interruption, not success. Report the observed result without claiming more than the JSON shows.

## Success definition

- `off`: `blockctl` exit 0 with `enabled: false` and `active_rules: 0`.
- `on`: `blockctl` exit 0 (or a following `status`) with `enabled: true` and `active_rules == expected_rules`, or exit 0 with `still_off_for` naming the other sessions.
- `guard`: a terminal record with the run ID that says what `status` showed and whether `blockctl on` ran.
- No block-list entry, extension file, state file, or other setting was changed by hand.

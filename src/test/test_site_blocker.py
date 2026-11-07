from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
from site_blocker import cli, common, host  # noqa: E402

NOTE = """# My block list

> [!note]
> - example.com is not read here

## Blocked sites

- linkedin.com
- https://www.Example.org/ (memo)
- `x.com`
- mail.google.com/chat # Google Chat
- *.slack.com
- not a site
- linkedin.com

## Notes

- reddit.com
"""


class ParseTest(unittest.TestCase):
    def test_reads_only_the_list_section_and_normalizes(self):
        sites, errors = common.parse_note(NOTE)
        self.assertEqual(sites, ["linkedin.com", "example.org", "x.com", "mail.google.com/chat", "*.slack.com"])
        self.assertEqual(len(errors), 1)
        self.assertIn("not a site", errors[0])

    def test_a_file_without_the_heading_is_read_whole(self):
        sites, errors = common.parse_note("- linkedin.com\n- x.com\n")
        self.assertEqual(sites, ["linkedin.com", "x.com"])
        self.assertEqual(errors, [])

    def test_japanese_heading_and_callout_style(self):
        sites, _ = common.parse_note("> ## ブロックするサイト\n\n- x.com\n\n> ## メモ\n\n- reddit.com\n")
        self.assertEqual(sites, ["x.com"])


class EnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.note = self.tmp / "sites.md"
        self.note.write_text(NOTE, encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"SITE_BLOCKER_LIST": str(self.note),
                                                "SITE_BLOCKER_STATE_DIR": str(self.tmp / "state"),
                                                "XDG_CONFIG_HOME": str(self.tmp / "config")})
        self.env.start()

    def tearDown(self):
        self.env.stop()


class ListTest(EnvTest):
    def test_path_comes_from_the_environment_then_the_env_file(self):
        self.assertEqual(common.list_note_path(), self.note)
        other = self.tmp / "other.md"
        env_file = common.env_file()
        env_file.parent.mkdir(parents=True)
        env_file.write_text(f"SITE_BLOCKER_PYTHON=/usr/bin/python3\nSITE_BLOCKER_LIST={other}\n", encoding="utf-8")
        self.assertEqual(common.list_note_path(), self.note)
        with mock.patch.dict(os.environ, {"SITE_BLOCKER_LIST": ""}):
            self.assertEqual(common.list_note_path(), other)

    def test_empty_or_missing_note_keeps_the_last_good_list(self):
        first = common.load_list()
        self.assertEqual(len(first["sites"]), 5)
        self.note.write_text("## Blocked sites\n\n", encoding="utf-8")
        second = common.load_list()
        self.assertEqual(second["sites"], first["sites"])
        self.assertTrue(any("last good" in e for e in second["errors"]))
        self.note.unlink()
        third = common.load_list()
        self.assertEqual(third["sites"], first["sites"])


class FakeExtension:
    """Talks to Host over pipes like Chrome does, and answers every config with a status report."""

    def __init__(self):
        to_host_r, self.to_host_w = os.pipe()
        self.from_host_r, from_host_w = os.pipe()
        self.host = host.Host(os.fdopen(to_host_r, "rb"), os.fdopen(from_host_w, "wb"))
        self.reader = os.fdopen(self.from_host_r, "rb")
        self.writer = os.fdopen(self.to_host_w, "wb")
        self.configs: list[dict] = []
        threading.Thread(target=self.host.run, daemon=True).start()
        threading.Thread(target=self.loop, daemon=True).start()

    def send(self, message):
        data = json.dumps(message).encode()
        self.writer.write(struct.pack("<I", len(data)) + data)
        self.writer.flush()

    def loop(self):
        while True:
            header = self.reader.read(4)
            if len(header) < 4:
                return
            message = json.loads(self.reader.read(struct.unpack("<I", header)[0]))
            if message["type"] == "config":
                self.configs.append(message)
                off = message["offUntil"] > common.now_ms()
                n = len(message["sites"])
                self.send({"type": "status", "enabled": not off, "activeRules": 0 if off else n, "expectedRules": n,
                           "listErrors": message["listErrors"]})

    def close(self):
        self.writer.close()
        self.host.closed.set()


class HostAndCliTest(EnvTest):
    def setUp(self):
        super().setUp()
        self.patch = mock.patch.multiple(host, POLL_SECONDS=0.1)
        self.patch.start()
        self.ext = FakeExtension()

    def tearDown(self):
        self.ext.close()
        self.patch.stop()
        super().tearDown()

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(args))
        return code, json.loads(out.getvalue())

    def test_first_config_carries_the_note_list(self):
        deadline = time.time() + 3
        while not self.ext.configs and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.ext.configs[0]["sites"][0], "linkedin.com")
        self.assertEqual(self.ext.configs[0]["offUntil"], 0)

    def test_off_and_on_wait_for_the_extension(self):
        time.sleep(0.3)
        code, result = self.run_cli("off", "--for", "15m")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["active_rules"], 0)
        self.assertFalse(result["enabled"])
        self.assertGreater(result["requested_off_until"], common.now_ms() + 14 * 60_000)
        code, result = self.run_cli("on")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["active_rules"], 5)
        code, result = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertTrue(result["connected"])

    def test_one_session_turning_on_keeps_another_sessions_pause(self):
        time.sleep(0.3)
        code, _ = self.run_cli("off", "--for", "60m", "--holder", "inbox-run")
        self.assertEqual(code, 0)
        code, _ = self.run_cli("off", "--for", "25m", "--holder", "amazon")
        self.assertEqual(code, 0)
        code, result = self.run_cli("on", "--holder", "amazon")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["still_off_for"], ["inbox-run"])
        time.sleep(0.4)
        code, result = self.run_cli("status")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["active_rules"], 0)
        self.assertEqual(list(result["holders"]), ["inbox-run"])
        self.assertGreater(result["requested_off_until"], common.now_ms() + 59 * 60_000)
        code, result = self.run_cli("on", "--holder", "inbox-run")
        self.assertEqual(code, 0, result)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["active_rules"], 5)
        self.assertEqual(result["holders"], {})

    def test_a_shorter_pause_does_not_shorten_a_longer_one(self):
        time.sleep(0.3)
        self.run_cli("off", "--for", "60m", "--holder", "a")
        self.run_cli("off", "--for", "5m", "--holder", "b")
        self.assertGreater(common.read_state()["off_until"], common.now_ms() + 59 * 60_000)

    def test_on_all_and_the_extension_button_end_every_pause(self):
        time.sleep(0.3)
        self.run_cli("off", "--for", "30m", "--holder", "a")
        self.run_cli("off", "--for", "30m", "--holder", "b")
        code, result = self.run_cli("on", "--all")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["active_rules"], 5)
        self.run_cli("off", "--for", "30m", "--holder", "a")
        self.ext.send({"type": "resume", "by": "popup-resume"})
        time.sleep(0.5)
        self.assertEqual(common.read_state()["off_until"], 0)
        self.assertEqual(common.live_leases(common.read_state()), {})

    def test_a_pause_written_before_leases_is_still_honored(self):
        until = common.now_ms() + 10 * 60_000
        common.write_json(common.state_path(), {"off_until": until, "by": "blockctl", "updated_at_ms": common.now_ms()})
        state = common.release("someone-else", "blockctl")
        self.assertEqual(state["off_until"], until)

    def test_note_edit_is_sent_again(self):
        time.sleep(0.3)
        self.note.write_text(NOTE.replace("- *.slack.com", "- *.slack.com\n- reddit.com"), encoding="utf-8")
        deadline = time.time() + 3
        while time.time() < deadline and "reddit.com" not in self.ext.configs[-1]["sites"]:
            time.sleep(0.05)
        self.assertIn("reddit.com", self.ext.configs[-1]["sites"])

    def test_popup_pause_is_capped_and_saved(self):
        time.sleep(0.3)
        self.ext.send({"type": "pause", "until": common.now_ms() + 5 * 3_600_000, "by": "popup-pause"})
        time.sleep(0.5)
        state = common.read_state()
        self.assertLessEqual(state["off_until"], common.now_ms() + common.CLI_MAX_MINUTES * 60_000 + 1000)
        self.assertEqual(state["by"], "popup-pause")


class CliOfflineTest(EnvTest):
    def test_off_without_chrome_fails_and_status_is_not_connected(self):
        out = io.StringIO()
        with mock.patch.object(cli, "WAIT_SECONDS", 0.5), redirect_stdout(out):
            code = cli.main(["off"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out.getvalue())["ok"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["status"]), 3)

    def test_duration_limits(self):
        self.assertEqual(cli.parse_minutes("1h"), 60)
        self.assertEqual(cli.parse_minutes("20"), 20)
        for bad in ("0", "61m", "2h", "soon"):
            with self.assertRaises(Exception):
                cli.parse_minutes(bad)


if __name__ == "__main__":
    unittest.main()

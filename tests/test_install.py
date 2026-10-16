"""install/uninstall edit ~/.claude/settings.json: they must never lose anyone else's hooks."""
import contextlib
import io
import json
import os
import plistlib
import stat
import sys
import unittest
from unittest import mock

from helpers import Sandbox

OTHER = {"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/other.sh"}]}


class TestMerge(Sandbox):
    def test_merge_into_empty(self):
        d = self.m.merge_hooks({}, "/x/claude-bardo hook")
        for ev in ("SessionStart", "SessionEnd"):
            self.assertEqual(d["hooks"][ev], [{"hooks": [{"type": "command", "command": "/x/claude-bardo hook", "timeout": 10}]}])

    def test_merge_keeps_others_and_is_idempotent(self):
        base = {"model": "opus", "hooks": {"SessionEnd": [json.loads(json.dumps(OTHER))], "Stop": [OTHER]}}
        once = self.m.merge_hooks(json.loads(json.dumps(base)), "/x/claude-bardo hook")
        twice = self.m.merge_hooks(json.loads(json.dumps(once)), "/x/claude-bardo hook")
        self.assertEqual(once, twice)
        self.assertEqual(once["hooks"]["SessionEnd"][0], OTHER)
        self.assertEqual(once["hooks"]["Stop"], [OTHER])
        self.assertEqual(once["model"], "opus")

    def test_merge_repoints_a_moved_binary(self):
        d = self.m.merge_hooks({}, "/old/claude-bardo hook")
        d = self.m.merge_hooks(d, "/new/claude-bardo hook")
        self.assertEqual(len(d["hooks"]["SessionStart"]), 1)
        self.assertEqual(d["hooks"]["SessionStart"][0]["hooks"][0]["command"], "/new/claude-bardo hook")

    def test_merge_refuses_odd_shapes(self):
        with self.assertRaises(ValueError):
            self.m.merge_hooks({"hooks": []}, "x hook")
        with self.assertRaises(ValueError):
            self.m.merge_hooks({"hooks": {"SessionStart": {}}}, "x hook")

    def test_remove_only_ours(self):
        d = self.m.merge_hooks({"hooks": {"SessionEnd": [json.loads(json.dumps(OTHER))]}}, "/x/claude-bardo hook")
        d = self.m.remove_hooks(d)
        self.assertEqual(d, {"hooks": {"SessionEnd": [OTHER]}})
        self.assertEqual(self.m.remove_hooks(self.m.merge_hooks({}, "/x/claude-bardo hook")), {})

    def test_is_our_hook(self):
        self.assertTrue(self.m.is_our_hook("/Users/a/.local/bin/claude-bardo hook"))
        self.assertTrue(self.m.is_our_hook("'/Users/a b/claude-bardo' hook"))
        self.assertFalse(self.m.is_our_hook("/x/claude-sessions hook"))
        self.assertFalse(self.m.is_our_hook("/x/claude-bardo list"))
        self.assertFalse(self.m.is_our_hook("unbalanced 'quote"))


class TestInstallCommand(Sandbox):
    def settings(self):
        with open(os.path.join(self.claude_dir, "settings.json")) as f:
            return f.read()

    def test_install_twice_then_uninstall(self):
        path = os.path.join(self.claude_dir, "settings.json")
        with open(path, "w") as f:
            json.dump({"hooks": {"SessionEnd": [OTHER]}}, f, indent=2)
        bindir = os.path.join(self.tmp, "bin")
        p = self.run_tool("install", "--bin-dir", bindir)
        self.assertEqual(p.returncode, 0, p.stderr)
        dest = os.path.join(bindir, "claude-bardo")
        self.assertEqual(stat.S_IMODE(os.stat(dest).st_mode), 0o755)
        page = os.path.join(self.tmp, "share", "man", "man1", "claude-bardo.1")
        self.assertTrue(os.path.isfile(page))
        first = self.settings()
        self.assertIn(dest + " hook", first)
        self.assertIn("other.sh", first)
        self.assertTrue(any(n.startswith("settings.json.bak-") for n in os.listdir(self.claude_dir)))
        self.assertEqual(self.run_tool("install", "--bin-dir", bindir).returncode, 0)
        self.assertEqual(self.settings(), first)                      # idempotent: byte-identical
        p = self.run_tool("uninstall", "--bin-dir", bindir, "--purge")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(page))
        self.assertEqual(json.loads(self.settings()), {"hooks": {"SessionEnd": [OTHER]}})
        self.assertFalse(os.path.exists(self.state))

    def test_install_refuses_broken_settings(self):
        path = os.path.join(self.claude_dir, "settings.json")
        with open(path, "w") as f:
            f.write("{ not json")
        p = self.run_tool("install", "--bin-dir", os.path.join(self.tmp, "bin"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.settings(), "{ not json")

    def test_dry_run_changes_nothing(self):
        extra = ["--launchd"] if sys.platform == "darwin" else []      # login agents are macOS-only
        p = self.run_tool("install", "--bin-dir", os.path.join(self.tmp, "bin"), "--dry-run", *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("SessionStart", p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.claude_dir, "settings.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "bin")))

    def test_launchd_plist(self):
        pl = plistlib.loads(self.m.launchd_plist("/u/.local/bin/claude-bardo").encode())
        self.assertEqual(pl["Label"], "claude-bardo.autorestore")
        self.assertEqual(pl["ProgramArguments"], ["/u/.local/bin/claude-bardo", "autorestore"])
        self.assertEqual(pl["Umask"], 0o077)
        self.assertIn("/u/.local/bin", pl["EnvironmentVariables"]["PATH"])
        self.assertEqual(pl["EnvironmentVariables"]["CLAUDE_BARDO_DIR"], self.state)


class TestDoctor(Sandbox):
    def doctor(self, version):
        """doctor's output with `claude --version` faked to print `version`."""
        fake = os.path.join(self.tmp, "claude")
        real_which, real_run = self.m.shutil.which, self.m.run
        self.m.run = lambda cmd, **kw: version if cmd == [fake, "--version"] else real_run(cmd, **kw)
        out = io.StringIO()
        with mock.patch.object(self.m.shutil, "which", lambda n: fake if n == "claude" else real_which(n)), \
                contextlib.redirect_stdout(out):
            self.m.cmd_doctor(None)
        return out.getvalue()

    def test_newer_than_verified_compares_numbers(self):
        newer, v = self.m.newer_than_verified, self.m.FLAGS_VERIFIED_ON
        *head, last = v.split(".")
        self.assertTrue(newer(".".join(head + ["1" + "0" * len(last)]) + " (Claude Code)"))   # newer as numbers, older as text
        self.assertTrue(newer("99.0.0 (Claude Code)"))
        self.assertFalse(newer(v + " (Claude Code)"))
        self.assertFalse(newer("0.0.1 (Claude Code)"))
        self.assertFalse(newer(""))
        self.assertFalse(newer("not a version"))

    def test_doctor_points_a_newer_claude_at_the_update(self):
        out = self.doctor("99.0.0 (Claude Code)")
        self.assertIn("newer than the flag tables", out)
        self.assertIn("https://github.com/multiplyco/claude-bardo#update", out)

    def test_doctor_is_quiet_about_an_older_or_equal_claude(self):
        for v in ("0.0.1 (Claude Code)", self.m.FLAGS_VERIFIED_ON + " (Claude Code)"):
            self.assertNotIn("flag tables", self.doctor(v))


if __name__ == "__main__":
    unittest.main()

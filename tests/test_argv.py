"""The flag replay policy: what a relaunch replays, what it never replays, and why."""
import json
import os
import unittest

from helpers import Sandbox, uuid

SELECTORS = {"--resume", "-r", "--session-id", "--name", "-n", "--continue", "-c", "--fork-session",
             "--print", "-p", "--worktree", "-w", "--tmux", "--desktop", "--bg", "--background"}
BYPASS = {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "bypassPermissions"}

CASES = [  # (argv without argv[0], exact, expected)
    (["--model", "opus", "fix the bug", "--chrome"], True, ["--model", "opus", "--chrome"]),
    (["--effort", "xhigh", "--", "--model", "x"], True, ["--effort", "xhigh"]),
    (["--resume", uuid(1), "--model", "opus"], True, ["--model", "opus"]),
    (["-r", "--model", "opus"], True, ["--model", "opus"]),
    (["--resume=" + uuid(1), "--chrome"], True, ["--chrome"]),
    (["--session-id", uuid(1), "-n", "name", "--name=x", "--chrome"], True, ["--chrome"]),
    (["-c", "--fork-session", "-p", "--print", "--bg", "--desktop", "--chrome"], True, ["--chrome"]),
    (["-w", "feature", "--tmux", "--model", "opus"], True, ["--model", "opus"]),
    (["--worktree", "--tmux=classic", "--chrome"], True, ["--chrome"]),
    (["--permission-mode", "auto", "--effort", "high"], True, ["--permission-mode", "auto", "--effort", "high"]),
    (["--permission-mode", "auto", "--effort", "high"], False, ["--permission-mode", "auto", "--effort", "high"]),
    (["--model", ""], True, []),
    (["--model"], True, []),
    (["--add-dir", "/a", "/b", "--chrome"], True, ["--add-dir", "/a", "/b", "--chrome"]),
    (["--add-dir", "/a", "fix", "it"], False, ["--add-dir", "/a"]),
    (["--debug", "api", "--chrome"], True, ["--debug", "api", "--chrome"]),
    (["--debug", "fix", "it"], False, ["--debug"]),
    (["--model", "opus", "fix", "the", "bug"], False, ["--model", "opus"]),
    (["--append-system-prompt", "be", "terse", "--model", "opus"], False, []),
    (["--append-system-prompt", "terse", "--model", "opus"], False, ["--append-system-prompt", "terse", "--model", "opus"]),
    (["--append-system-prompt", "be terse", "--model", "opus"], True, ["--append-system-prompt", "be terse", "--model", "opus"]),
    (["--settings", '{"a":', "1}", "--chrome"], False, []),
    (["--model=opus", "--effort=low"], False, ["--model=opus", "--effort=low"]),
    (["--brand-new-flag", "value", "--chrome"], True, ["--chrome"]),
    (["--brand-new=1", "--chrome"], True, ["--chrome"]),
    (["--plugin-dir", "/p/a", "/looks/like/a/path", "--chrome"], True, ["--plugin-dir", "/p/a", "--chrome"]),
]


class TestSanitize(Sandbox):
    def test_table(self):
        for argv, exact, want in CASES:
            with self.subTest(argv=argv, exact=exact):
                self.assertEqual(self.m.sanitize_argv(list(argv), exact=exact), want)

    def test_invariants(self):
        for argv, exact, _ in CASES:
            out = self.m.sanitize_argv(list(argv), exact=exact)
            with self.subTest(argv=argv):
                self.assertFalse({t.split("=", 1)[0] for t in out} & SELECTORS, "a selector was replayed")
                self.assertFalse(set(out) & BYPASS, "a bypass was replayed")
                it = iter(argv)   # output is a subsequence of the input: nothing invented, order kept
                self.assertTrue(all(tok in it for tok in out), "output is not a subsequence of the input")
                self.assertEqual(self.m.sanitize_argv(list(out), exact=exact), out, "not idempotent")

    def test_bypass_dropped_by_default_in_both_modes(self):
        for argv in (["--dangerously-skip-permissions"], ["--allow-dangerously-skip-permissions"],
                     ["--permission-mode", "bypassPermissions"], ["--permission-mode=bypassPermissions"],
                     ["--settings", json.dumps({"permissions": {"defaultMode": "bypassPermissions"}})]):
            for exact in (True, False):
                with self.subTest(argv=argv, exact=exact):
                    dropped = []
                    self.assertEqual(self.m.sanitize_argv(list(argv) + ["--chrome"], exact=exact, dropped=dropped), ["--chrome"])
                    self.assertEqual([why for _, why in dropped], ["bypass"])

    def test_bypass_settings_file(self):
        p = os.path.join(self.tmp, "yolo.json")
        with open(p, "w") as f:
            json.dump({"permissions": {"defaultMode": "bypassPermissions"}}, f)
        self.assertEqual(self.m.sanitize_argv(["--settings", p, "--chrome"]), ["--chrome"])
        safe = os.path.join(self.tmp, "safe.json")
        with open(safe, "w") as f:
            json.dump({"model": "opus"}, f)
        self.assertEqual(self.m.sanitize_argv(["--settings", safe]), ["--settings", safe])

    def test_keep_bypass_only_from_exact_argv(self):
        argv = ["--dangerously-skip-permissions", "--permission-mode", "bypassPermissions"]
        self.assertEqual(self.m.sanitize_argv(list(argv), exact=True, keep_bypass=True), argv)
        self.assertEqual(self.m.sanitize_argv(list(argv), exact=False, keep_bypass=True), [])

    def test_unknown_flags_reported_and_optionally_kept(self):
        dropped = []
        self.assertEqual(self.m.sanitize_argv(["--new", "--chrome"], dropped=dropped), ["--chrome"])
        self.assertEqual(dropped, [("--new", "unknown")])
        self.assertEqual(self.m.sanitize_argv(["--new", "prompt", "--new2=x"], keep_unknown=True), ["--new", "--new2"])

    def test_non_string_tokens_stop_parsing(self):
        self.assertEqual(self.m.sanitize_argv(["--chrome", 7, "--verbose"]), ["--chrome"])


class TestRecord(Sandbox):
    def test_never_stores_the_prompt(self):
        argv = ["claude", "--model", "opus", "here is my token sk-123", "--chrome", "--", "more secret"]
        self.assertEqual(self.m.record_argv(argv, True), ["claude", "--model", "opus", "--chrome"])

    def test_keeps_bypass_and_unknown_for_the_policy(self):
        argv = ["claude", "--dangerously-skip-permissions", "--future", "prompt"]
        self.assertEqual(self.m.record_argv(argv, True), ["claude", "--dangerously-skip-permissions", "--future"])

    def test_strips_node_interpreter(self):
        argv = ["node", "/opt/lib/node_modules/@anthropic-ai/claude-code/cli.js", "--model", "opus", "prompt"]
        self.assertEqual(self.m.record_argv(argv, True), [argv[1], "--model", "opus"])
        self.assertTrue(self.m.is_claude_argv(argv))
        self.assertFalse(self.m.is_claude_argv(["python3", "/x/tool.py"]))


class TestBuildCommand(Sandbox):
    def mk(self, **start):
        s = self.m.Session.__new__(self.m.Session)
        s.id, s.start = uuid(9), dict({"argv": ["claude"], "argv_exact": True}, **start)
        return s

    def test_resume_is_last_and_flags_replayed(self):
        cmd = self.m.build_command(self.mk(argv=["claude", "--model", "opus", "prompt"]))
        self.assertEqual(cmd, ["claude", "--model", "opus", "--resume", uuid(9)])

    def test_bypass_needs_keep_bypass(self):
        s = self.mk(argv=["claude", "--dangerously-skip-permissions"])
        self.assertNotIn("--dangerously-skip-permissions", self.m.build_command(s))
        self.assertIn("--dangerously-skip-permissions", self.m.build_command(s, keep_bypass=True))
        self.assertEqual(s.__class__.bypass.fget(s), ["--dangerously-skip-permissions"])

    def test_fork(self):
        cmd = self.m.build_command(self.mk(argv=["claude", "--model", "opus"]), fork=True)
        self.assertEqual(cmd, ["claude", "--model", "opus", "--resume", uuid(9), "--fork-session"])
        self.assertNotIn("--fork-session", self.m.build_command(self.mk()))

    def test_caffeinate(self):
        self.assertEqual(self.m.build_command(self.mk(caffeinate=["-s", "-i"]))[:4], ["caffeinate", "-s", "-i", "--"])
        for bad in (["-t", "300"], ["; rm -rf ~"], "-i", [3]):
            with self.subTest(caffeinate=bad):
                self.assertEqual(self.m.build_command(self.mk(caffeinate=bad))[0], "claude")

    def test_claude_path(self):
        os.makedirs(os.path.join(self.tmp, "bin"))
        exe = os.path.join(self.tmp, "bin", "claude")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        self.assertEqual(self.m.build_command(self.mk(claude_path=exe))[0], exe)
        self.assertEqual(self.m.build_command(self.mk(claude_path="/nope/claude"))[0], "claude")
        self.assertEqual(self.m.build_command(self.mk(claude_path="relative/claude"))[0], "claude")


if __name__ == "__main__":
    unittest.main()

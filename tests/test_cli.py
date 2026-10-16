"""The command line, end to end in a sandbox: help, list, restore --dry-run, forget,
resume, prune, exit codes, and the picker's id mapping."""
import contextlib
import datetime
import io
import json
import os
import shutil
import stat
import sys
import unittest

from helpers import Sandbox, uuid


class TestCli(Sandbox):
    def crashed(self, n, argv=None, name=None):
        cwd = self.workdir("p{}".format(n))
        self.transcript(uuid(n), cwd, [{"type": "custom-title", "customTitle": name}] if name else [])
        self.start(uuid(n), cwd, argv=argv or ["claude", "--model", "opus"])
        self.end(uuid(n), "other")
        return cwd

    def test_help(self):
        p = self.run_tool("--help")
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("SUPPRESS", p.stdout)
        self.assertNotIn("_launch", p.stdout)
        self.assertIn("restore", p.stdout)
        self.assertEqual(self.run_tool("--version").stdout.split()[0], "claude-bardo")

    def test_list_and_json(self):
        self.crashed(1, name="alpha")
        p = self.run_tool()
        self.assertEqual(p.returncode, 0)
        self.assertIn("alpha", p.stdout)
        self.assertIn("interrupted", p.stdout)
        rows = [json.loads(l) for l in self.run_tool("list", "--json").stdout.splitlines()]
        mine = [r for r in rows if r["id"] == uuid(1)]
        self.assertEqual(mine[0]["status"], "interrupted")
        self.assertEqual(mine[0]["command"], ["claude", "--model", "opus", "--resume", uuid(1)])

    @unittest.skipUnless(sys.platform == "darwin", "window mode is macOS-only")
    def test_restore_dry_run_windows(self):
        cwd = self.crashed(1, argv=["claude", "--dangerously-skip-permissions", "--effort", "high"])
        p = self.run_tool("restore", uuid(1)[:13], "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("open -na Ghostty", p.stdout)
        self.assertIn("claude --effort high --resume " + uuid(1), p.stdout)
        self.assertNotIn("--dangerously-skip-permissions", p.stdout)
        self.assertIn(cwd, p.stdout)
        p = self.run_tool("restore", uuid(1)[:13], "--dry-run", "--keep-bypass")
        self.assertIn("--dangerously-skip-permissions", p.stdout)
        p = self.run_tool("restore", uuid(1)[:13], "--dry-run", "--terminal", "iterm")
        self.assertIn("osascript", p.stdout)

    @unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
    def test_restore_dry_run_tmux(self):
        self.crashed(1, argv=["claude", "--dangerously-skip-permissions", "--effort", "high"], name="#(touch /tmp/pwned)")
        p = self.run_tool("restore", uuid(1)[:13], "--dry-run", "--tmux", "--no-attach")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("tmux new-session", p.stdout)
        self.assertNotIn(" -c ", p.stdout)
        self.assertIn("##(touch", p.stdout)                  # the name cannot run as a tmux format
        self.assertIn("CLAUDE_BARDO_DIR=", p.stdout)         # the window gets our registry, not the default
        self.assertNotIn("--dangerously-skip-permissions", p.stdout)

    def test_fork_rehearses_live_sessions_only(self):
        cwd = self.workdir("live")
        self.transcript(uuid(7), cwd)
        me = os.getpid()
        with open(os.path.join(self.claude_dir, "sessions", "{}.json".format(me)), "w") as f:
            json.dump({"pid": me, "sessionId": uuid(7), "cwd": cwd, "procStart": self.m.ps("lstart", me)}, f)
        self.start(uuid(7), cwd, argv=["claude", "--model", "opus"])
        self.crashed(1)
        tmpl = {"CLAUDE_BARDO_LAUNCHER": "myterm -e {cmd}"}           # no tmux or macOS needed
        p = self.run_tool("restore", "--fork", "--all", "--dry-run", env=tmpl)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(uuid(7), p.stdout)
        self.assertNotIn(uuid(1), p.stdout)                     # dead sessions are restored, not forked
        self.assertIn("--fork", p.stdout)
        p = self.run_tool("restore", uuid(7), "--dry-run", env=tmpl)
        self.assertEqual(p.returncode, 1)                       # a live session is never restored twice

    def test_exit_codes(self):
        self.assertEqual(self.run_tool("restore", "--all", "--tmux").returncode, 3)   # nothing to restore
        self.assertEqual(self.run_tool("restore", "--terminal", "hyper").returncode, 2)
        self.assertEqual(self.run_tool("restore", "abc", "--tmux").returncode, 1)     # prefix too short
        self.assertEqual(self.run_tool("resume", uuid(5)).returncode, 1)
        self.assertEqual(self.run_tool("nonsense").returncode, 2)

    def test_forget(self):
        self.crashed(1)
        p = self.run_tool("forget", uuid(1)[:13])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.session(uuid(1)).status, "closed")
        self.assertEqual(self.run_tool("forget", uuid(1)[:13]).returncode, 1)

    def test_forget_forks(self):
        self.crashed(1)
        cwd = self.workdir("fork")
        self.transcript(uuid(2), cwd)
        self.start(uuid(2), cwd, forked_from=uuid(1))
        self.end(uuid(2), "other")
        self.assertEqual(self.run_tool("forget").returncode, 2)
        p = self.run_tool("forget", "--forks")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.session(uuid(2)).status, "closed")
        self.assertEqual(self.session(uuid(1)).status, "interrupted")      # the original is left alone

    def test_prune(self):
        old = (datetime.datetime.now().astimezone() - datetime.timedelta(days=60)).isoformat(timespec="seconds")
        cwd = self.workdir()
        for n, reason, ts in ((1, "prompt_input_exit", old), (2, "prompt_input_exit", self.m.now_iso()),
                              (3, "other", self.m.now_iso()), (4, "other", old)):
            os.utime(self.transcript(uuid(n), cwd), (0, 0))
            self.m.append({"ts": ts, "event": "start", "session_id": uuid(n), "cwd": cwd})
            self.m.append({"ts": ts, "event": "end", "session_id": uuid(n), "reason": reason})
        self.m.append({"ts": old, "event": "end", "session_id": uuid(5), "reason": "shutdown"})   # foreign
        p = self.run_tool("prune")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(set(self.m.read_registry()), {uuid(2), uuid(3)})
        self.assertFalse(os.path.exists(self.m.REGISTRY + ".bak"))
        self.assertEqual(stat.S_IMODE(os.stat(self.m.REGISTRY).st_mode), 0o600)
        self.m.append({"ts": old, "event": "end", "session_id": uuid(6), "reason": "shutdown"})
        self.run_tool("prune", "--keep-backup")
        self.assertEqual(stat.S_IMODE(os.stat(self.m.REGISTRY + ".bak").st_mode), 0o600)


class TestPicker(Sandbox):
    def test_fzf_selection_maps_back_by_full_id(self):
        # UUIDv7 ids started within a minute share their first 8 hex digits
        ids = ["0190c0de-0000-7000-8000-{:012x}".format(i) for i in (1, 2)]
        for sid in ids:
            cwd = self.workdir(sid[-4:])
            self.transcript(sid, cwd)
            self.start(sid, cwd)
            self.end(sid, "other")
        fake = os.path.join(self.tmp, "bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "fzf"), "w") as f:   # "selects" only the first line
            f.write("#!/bin/sh\nhead -n 1\n")
        os.chmod(os.path.join(fake, "fzf"), 0o755)
        os.environ["PATH"] = fake + os.pathsep + os.environ["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", os.environ["PATH"].split(os.pathsep, 1)[1])
        cands = self.m.restorable(quiet=True)
        self.assertEqual(len(cands), 2)
        self.assertEqual(len(self.m.pick(cands)), 1)   # an 8-char prefix match would have returned both

    def test_plain_fallback(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd)
        self.start(uuid(1), cwd)
        self.end(uuid(1), "other")
        self.m.shutil.which = lambda name: None
        import builtins
        orig = builtins.input
        builtins.input = lambda prompt: "n"
        self.addCleanup(setattr, builtins, "input", orig)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.pick(self.m.restorable(quiet=True)), [])


if __name__ == "__main__":
    unittest.main()

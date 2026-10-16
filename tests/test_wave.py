"""After a reboot only the sessions that died in it should be pre-selected: closing a window
also counts as a crash, so the registry holds days of older deaths too."""
import argparse
import contextlib
import datetime
import io
import json
import os
import unittest

from helpers import Sandbox, load, uuid


def ago(minutes):
    return (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")


class TestWave(Sandbox):
    def died(self, n, minutes_ago):
        cwd = self.workdir("w{}".format(n))
        os.utime(self.transcript(uuid(n), cwd), (0, 0))
        self.m.append({"ts": ago(minutes_ago + 60), "event": "start", "session_id": uuid(n), "cwd": cwd})
        self.m.append({"ts": ago(minutes_ago), "event": "end", "session_id": uuid(n), "reason": "other"})

    def test_latest_wave(self):
        self.died(1, 1)
        self.died(2, 12)          # same reboot, a slow shutdown
        self.died(3, 60 * 26)     # a window closed yesterday
        cands = self.m.restorable(quiet=True)
        self.assertEqual({s.id for s in self.m.latest_wave(cands)}, {uuid(1), uuid(2)})
        self.assertEqual(self.m.latest_wave([]), [])

    def test_sigkill_victim_with_a_lingering_pid_file_died_at_boot(self):
        cwd = self.workdir()
        os.utime(self.transcript(uuid(1), cwd), (0, 0))                 # idle for ages before the power cut
        self.m.append({"ts": ago(600), "event": "start", "session_id": uuid(1), "cwd": cwd, "pid": 999999,
                       "proc_start": "Mon Jan  1 00:00:00 2024"})
        with open(os.path.join(self.claude_dir, "sessions", "999999.json"), "w") as f:
            json.dump({"pid": 999999, "sessionId": uuid(1), "cwd": cwd, "procStart": "Mon Jan  1 00:00:00 2024"}, f)
        boot = datetime.datetime.now().astimezone() - datetime.timedelta(minutes=3)
        self.m._BOOT[:] = [boot]
        s = self.session(uuid(1))
        self.assertEqual((s.status, s.lingering, s.died), ("killed", True, boot))

    def test_fzf_binds(self):
        self.assertEqual(self.m.fzf_preselect(4, 2), ["--bind=load:first+toggle+down+toggle+down+first"])
        self.assertEqual(self.m.fzf_preselect(4, 4), ["--bind=load:select-all"])
        self.assertEqual(self.m.fzf_preselect(4, 0), [])

    def test_plain_prompt_offers_the_wave_or_everything(self):
        for n, m in ((1, 1), (2, 2), (3, 3000)):
            self.died(n, m)
        cands = self.m.restorable(quiet=True)
        self.m.shutil.which = lambda name: None
        import builtins
        orig = builtins.input
        self.addCleanup(setattr, builtins, "input", orig)
        for answer, want in (("", 2), ("a", 3), ("n", 0)):
            builtins.input = lambda prompt, a=answer: a
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(len(self.m.pick(cands, preselect=2)), want)

    def test_restore_hands_the_picker_the_wave_first(self):
        self.died(1, 3000)
        self.died(2, 2)
        self.died(3, 1)
        seen = {}

        def fake_pick(cands, keep_bypass=False, preselect=None):
            seen["ids"], seen["k"] = [s.id for s in cands], preselect
            return []

        self.m.pick = fake_pick
        args = argparse.Namespace(ids=[], all=False, older=False, tmux=True, no_attach=True, terminal=None,
                                  keep_bypass=False, dry_run=True, reap=False)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = self.m.cmd_restore(args)
        self.assertEqual(rc, 3)
        self.assertEqual(seen["k"], 2)
        self.assertEqual(seen["ids"], [uuid(3), uuid(2), uuid(1)])


class TestAutorestore(Sandbox):
    def setUp(self):
        super().setUp()
        self.m = load(dict(self.env, CLAUDE_BARDO_LAUNCHER="myterm -e {cmd}"))   # any platform can open a "window"
        self.m.running_claude_ids = lambda: set()
        self.opened = []
        self.m.subprocess.run = lambda cmd, **kw: self.opened.append(cmd)

    def died(self, minutes_ago):
        cwd = self.workdir()
        os.utime(self.transcript(uuid(1), cwd), (0, 0))
        self.m.append({"ts": ago(minutes_ago + 60), "event": "start", "session_id": uuid(1), "cwd": cwd})
        self.m.append({"ts": ago(minutes_ago), "event": "end", "session_id": uuid(1), "reason": "other"})

    def test_opens_the_picker_when_the_last_shutdown_killed_something(self):
        self.died(20)
        self.m._BOOT[:] = [datetime.datetime.now().astimezone() - datetime.timedelta(minutes=5)]
        self.assertEqual(self.m.cmd_autorestore(None), 0)
        self.assertEqual(len(self.opened), 1)
        self.assertIn("restore", self.opened[0])
        self.assertNotIn("--keep-bypass", self.opened[0])

    def test_stays_quiet_when_the_deaths_came_after_boot(self):
        self.died(2)                                   # e.g. `install --launchd` loading the agent mid-day
        self.m._BOOT[:] = [datetime.datetime.now().astimezone() - datetime.timedelta(days=30)]
        self.assertEqual(self.m.cmd_autorestore(None), 0)
        self.assertEqual(self.opened, [])


if __name__ == "__main__":
    unittest.main()

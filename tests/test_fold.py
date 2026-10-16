"""How the registry, Claude Code's pid files and transcripts fold into a session status."""
import datetime
import json
import os
import unittest

from helpers import Sandbox, uuid


class TestEndReasons(Sandbox):
    def test_reason_table(self):
        table = {
            "other": "interrupted", "shutdown": "interrupted", None: "interrupted",
            "prompt_input_exit": "closed", "clear": "closed", "resume": "closed", "logout": "closed",
            "bypass_permissions_disabled": "closed", "forgotten": "closed",
        }
        for i, (reason, want) in enumerate(table.items(), 1):
            with self.subTest(reason=reason):
                cwd = self.workdir("r{}".format(i))
                self.transcript(uuid(i), cwd)
                self.start(uuid(i), cwd)
                self.end(uuid(i), reason)
                self.assertEqual(self.session(uuid(i)).status, want)

    def test_unknown_reason_stays_restorable_but_says_so(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd)
        self.start(uuid(1), cwd)
        self.end(uuid(1), "meteor_strike")
        s = self.session(uuid(1))
        self.assertEqual(s.status, "interrupted")
        self.assertIn("unrecognised end reason", s.note)


class TestStatus(Sandbox):
    def test_start_without_end_and_dead_pid_is_killed(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd)
        self.start(uuid(1), cwd, pid=999999, proc_start="Mon Jan  1 00:00:00 2024")
        self.assertEqual(self.session(uuid(1)).status, "killed")

    def test_unresumable(self):
        cwd = self.workdir()
        self.start(uuid(1), cwd)                               # no transcript
        self.end(uuid(1), "other")
        gone = os.path.join(self.tmp, "deleted-worktree")
        self.transcript(uuid(2), gone)                         # cwd no longer exists
        self.start(uuid(2), gone)
        self.end(uuid(2), "other")
        self.assertEqual(self.session(uuid(1)).status, "unresumable")
        self.assertIn("transcript missing", self.session(uuid(1)).note)
        self.assertEqual(self.session(uuid(2)).status, "unresumable")
        self.assertIn("cwd gone", self.session(uuid(2)).note)

    def test_end_only_records(self):
        cwd = self.workdir()
        self.end(uuid(1), "shutdown")                          # a foreign tool's hook: no transcript
        self.transcript(uuid(2), cwd)
        self.end(uuid(2), "other")                             # our start hook failed; transcript exists
        self.transcript(uuid(3), cwd)
        self.end(uuid(3), "prompt_input_exit")
        self.assertIsNone(self.session(uuid(1)))
        s = self.session(uuid(2))
        self.assertEqual((s.status, s.cwd), ("interrupted", cwd))
        self.assertIn("no start record", s.note)
        self.assertIsNone(self.session(uuid(3)))

    def test_restoring_ttl_and_launch_failed(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd)
        self.start(uuid(1), cwd)
        self.end(uuid(1), "other")
        self.m.append({"ts": self.m.now_iso(), "event": "restoring", "session_id": uuid(1)})
        self.assertEqual(self.session(uuid(1)).status, "restoring")
        self.m.RESTORING_TTL = -1
        self.assertEqual(self.session(uuid(1)).status, "interrupted")
        self.m.append({"ts": self.m.now_iso(), "event": "launch-failed", "session_id": uuid(1), "rc": 127})
        self.assertIn("last relaunch failed rc=127", self.session(uuid(1)).note)

    def test_lingering_pid_file_is_killed(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd)
        with open(os.path.join(self.claude_dir, "sessions", "999999.json"), "w") as f:
            json.dump({"pid": 999999, "sessionId": uuid(1), "cwd": cwd, "kind": "interactive",
                       "procStart": "Mon Jan  1 00:00:00 2024", "startedAt": 1700000000000}, f)
        s = self.session(uuid(1))
        self.assertEqual(s.status, "killed")
        self.assertIn("lingering", s.note)

    def test_live_pid_file(self):
        cwd = self.workdir()
        self.transcript(uuid(1), cwd)
        me = os.getpid()
        with open(os.path.join(self.claude_dir, "sessions", "{}.json".format(me)), "w") as f:
            json.dump({"pid": me, "sessionId": uuid(1), "cwd": cwd, "procStart": self.m.ps("lstart", me)}, f)
        self.start(uuid(1), cwd)
        self.assertEqual(self.session(uuid(1)).status, "live")

    def test_background_pid_files_are_ignored(self):
        with open(os.path.join(self.claude_dir, "sessions", "1.json"), "w") as f:
            json.dump({"pid": 1, "sessionId": uuid(1), "kind": "background"}, f)
        self.assertEqual(self.m.live_sessions(), ([], []))

    def test_old_interruptions_hidden_from_restore(self):
        cwd = self.workdir()
        old = (datetime.datetime.now().astimezone() - datetime.timedelta(days=20)).isoformat(timespec="seconds")
        for i, ts in ((1, old), (2, self.m.now_iso())):
            p = self.transcript(uuid(i), cwd)
            os.utime(p, (0, 0))
            self.m.append({"ts": ts, "event": "start", "session_id": uuid(i), "cwd": cwd})
            self.m.append({"ts": ts, "event": "end", "session_id": uuid(i), "reason": "other"})
        self.assertEqual([s.id for s in self.m.restorable(quiet=True)], [uuid(2)])
        self.assertEqual(len(self.m.restorable(include_older=True)), 2)

    def test_name_precedence(self):
        cwd = self.workdir("my-project")
        self.transcript(uuid(1), cwd, [{"type": "ai-title", "aiTitle": "AI title"}])
        self.start(uuid(1), cwd)
        self.assertEqual(self.session(uuid(1)).name, "AI title")
        self.transcript(uuid(2), cwd, [{"type": "ai-title", "aiTitle": "AI"}, {"type": "custom-title", "customTitle": "Mine\x1b[31m"}])
        self.start(uuid(2), cwd, name="hook title", name_source="title")
        self.assertEqual(self.session(uuid(2)).name, "Mine[31m")       # control characters stripped
        self.transcript(uuid(3), cwd)
        self.start(uuid(3), cwd)
        self.assertEqual(self.session(uuid(3)).name, "my-project")

    def test_id_width(self):
        v7 = ["0190c0de-0000-7000-8000-{:012x}".format(i) for i in range(3)]
        self.assertEqual(self.m.id_width([uuid(1), uuid(2).replace("0000", "1111", 1)]), 8)
        n = self.m.id_width(v7)
        self.assertEqual(len({i[:n] for i in v7}), 3)


if __name__ == "__main__":
    unittest.main()

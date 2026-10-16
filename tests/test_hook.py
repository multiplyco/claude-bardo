"""The hook runs inside every Claude Code session: it must never print, never fail, and
record only what it should."""
import json
import os
import subprocess
import sys
import time
import unittest

from helpers import Sandbox, uuid


class TestHook(Sandbox):
    def hook(self, payload, env=None):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return self.run_tool("hook", stdin=stdin, env=env)

    def records(self):
        if not os.path.exists(self.m.REGISTRY):
            return []
        with open(self.m.REGISTRY) as f:
            return [json.loads(l) for l in f if l.strip()]

    def payload(self, sid, event="SessionStart", **kw):
        d = {"session_id": sid, "hook_event_name": event, "cwd": self.workdir(),
             "transcript_path": os.path.join(self.tmp, sid + ".jsonl")}
        d.update(kw)
        return d

    def test_garbage_in_nothing_out(self):
        for stdin in ("", "not json", "[1,2,3]", "null", json.dumps({"session_id": "x"}), "{" * 5000):
            with self.subTest(stdin=stdin[:20]):
                p = self.hook(stdin)
                self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertEqual(self.records(), [])

    def test_skips_non_interactive_and_foreign_sessions(self):
        self.hook(self.payload(uuid(1)), env={"CLAUDE_CODE_ENTRYPOINT": "sdk-ts"})
        self.hook(self.payload(uuid(2)), env={"CLAUDE_CODE_SESSION_ATTENDED": "0"})
        self.hook(self.payload(uuid(3), transcript_path=None))       # other tools' hooks carry no transcript
        self.hook(self.payload(uuid(4), hook_event_name="PreToolUse"))
        self.hook(self.payload(uuid(5) + "\n"))
        # Grok Build runs ~/.claude/settings.json hooks too; its envelope adds camelCase keys
        self.hook(self.payload(uuid(6), hookEventName="session_start", sessionId=uuid(6)))
        self.hook(self.payload(uuid(6), event="SessionEnd", hookEventName="session_end", reason="shutdown"))
        self.assertEqual(self.records(), [])

    def test_records_start_and_end(self):
        fake = subprocess.Popen(["claude", "-c", "import time; time.sleep(30)", "--model", "opus",
                                 "--dangerously-skip-permissions", "my secret first prompt"], executable=sys.executable)
        self.addCleanup(fake.wait)
        self.addCleanup(fake.kill)
        time.sleep(0.3)
        p = self.hook(self.payload(uuid(1), source="startup", session_title="t"),
                      env={"CLAUDE_PID": str(fake.pid), "CLAUDE_CODE_ENTRYPOINT": "cli"})
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.hook(self.payload(uuid(1), event="SessionEnd", reason="other"))
        start, end = [r for r in self.records() if r["event"] != "probe"]
        self.assertEqual(start["event"], "start")
        self.assertEqual(start["pid"], fake.pid)
        self.assertEqual(start["v"], 1)
        if sys.platform == "darwin" or os.path.exists("/proc"):
            self.assertTrue(start["argv_exact"])
            # argv[0] is the fake's (a framework Python may re-exec under its own path); the flags are the point
            self.assertEqual(start["argv"][1:], ["--model", "opus", "--dangerously-skip-permissions"])
        self.assertNotIn("secret", json.dumps(start))
        self.assertTrue(start["proc_start"])
        self.assertEqual((end["event"], end["reason"]), ("end", "other"))

    def test_records_where_a_fork_came_from(self):
        fake = subprocess.Popen(["claude", "-c", "import time; time.sleep(30)", "--resume", uuid(9), "--fork-session"],
                                executable=sys.executable)
        self.addCleanup(fake.wait)
        self.addCleanup(fake.kill)
        time.sleep(0.3)
        self.hook(self.payload(uuid(1), source="resume"), env={"CLAUDE_PID": str(fake.pid), "CLAUDE_CODE_ENTRYPOINT": "cli"})
        start = self.records()[0]
        if start.get("argv_exact"):
            self.assertEqual(start["forked_from"], uuid(9))
            self.assertNotIn("--fork-session", start["argv"])

    def test_records_where_the_session_lives(self):
        """Measurement for the window-close proposal: the hook's ancestors at start, and at
        end (after the end record, never instead of it) the ancestors plus live terminals."""
        self.hook(self.payload(uuid(1)))
        p = self.hook(self.payload(uuid(1), event="SessionEnd", reason="other"))
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        start, end, probe = self.records()
        self.assertEqual([start["event"], end["event"], probe["event"]], ["start", "end", "probe"])
        me = [a for a in start["anc"] if a[0] == os.getpid()]      # this test process spawned the hook
        self.assertEqual(len(me), 1)
        self.assertEqual(len(me[0][2]), 24)                        # lstart, to tell a reused pid apart
        self.assertEqual((probe["session_id"], probe["at"]), (uuid(1), "end"))
        self.assertIn(os.getpid(), [a[0] for a in probe["anc"]])
        self.assertIsInstance(probe["terms"], list)

    def test_probe_is_invisible_to_the_fold(self):
        self.transcript(uuid(1), self.workdir())
        self.start(uuid(1), self.workdir())
        self.end(uuid(1), "prompt_input_exit")
        self.m.append({"ts": self.m.now_iso(), "event": "probe", "session_id": uuid(1), "at": "end", "anc": [], "terms": []})
        self.assertEqual(self.session(uuid(1)).status, "closed")

    def test_proc_table_and_ancestry(self):
        table = self.m.proc_table()
        self.assertIn(os.getpid(), table)
        chain = self.m.ancestry(os.getpid(), table)
        self.assertTrue(chain)
        self.assertNotIn(1, [a[0] for a in chain])
        self.assertEqual(self.m.ancestry(10, {10: (10, "self", "")}), [[10, "self", ""]])       # cycles end
        self.assertEqual(self.m.ancestry(10, {10: (11, "a", ""), 11: (10, "b", "")}), [[11, "b", ""], [10, "a", ""]])
        self.assertEqual(self.m.ancestry(10, {10: (12, "a", "")}), [])                           # parent vanished

    def test_unwritable_state_never_fails_the_hook(self):
        env = {"CLAUDE_BARDO_DIR": "/dev/null/nope"}
        p = self.hook(self.payload(uuid(1)), env=env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()

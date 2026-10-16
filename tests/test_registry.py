"""The registry file: append-only JSONL, private, crash tolerant, forward compatible."""
import json
import os
import stat
import unittest

from helpers import Sandbox, uuid


class TestRegistry(Sandbox):
    def test_valid_id(self):
        self.assertTrue(self.m.valid_id(uuid(1)))
        self.assertTrue(self.m.valid_id(uuid(1).upper()))
        for bad in (uuid(1) + "\n", " " + uuid(1), uuid(1)[:-1], 12345, None, "", ["x"]):
            with self.subTest(bad=bad):
                self.assertFalse(self.m.valid_id(bad))

    def test_append_is_private_and_versioned(self):
        self.m.append({"ts": self.m.now_iso(), "event": "start", "session_id": uuid(1)})
        self.assertEqual(stat.S_IMODE(os.stat(self.state).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.m.REGISTRY).st_mode), 0o600)
        with open(self.m.REGISTRY) as f:
            self.assertEqual(json.loads(f.readline())["v"], self.m.SCHEMA)

    def test_existing_world_readable_files_are_tightened(self):
        os.makedirs(self.state, mode=0o755)
        os.chmod(self.state, 0o755)
        with open(self.m.REGISTRY, "w") as f:
            f.write("")
        os.chmod(self.m.REGISTRY, 0o644)
        self.m.append({"ts": self.m.now_iso(), "event": "start", "session_id": uuid(1)})
        self.assertEqual(stat.S_IMODE(os.stat(self.state).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.m.REGISTRY).st_mode), 0o600)

    def test_torn_last_line_does_not_swallow_the_next_record(self):
        os.makedirs(self.state)
        with open(self.m.REGISTRY, "w") as f:
            f.write(json.dumps({"event": "start", "session_id": uuid(1)}) + "\n")
            f.write('{"event": "start", "session_id": "0000')          # crash mid-write
        self.m.append({"ts": self.m.now_iso(), "event": "start", "session_id": uuid(2)})
        self.assertEqual(set(self.m.read_registry()), {uuid(1), uuid(2)})

    def test_garbage_is_skipped_not_fatal(self):
        os.makedirs(self.state)
        with open(self.m.REGISTRY, "w") as f:
            f.write("not json\n[1,2]\n\n")
            f.write(json.dumps({"event": "start", "session_id": 12345}) + "\n")
            f.write(json.dumps({"event": "start", "session_id": "../../etc"}) + "\n")
            f.write(json.dumps({"event": "start", "session_id": uuid(3), "cwd": 7, "future_field": {"x": 1}}) + "\n")
            f.write(json.dumps({"event": "teleported", "session_id": uuid(3)}) + "\n")   # unknown event type
        self.assertEqual(set(self.m.read_registry()), {uuid(3)})
        self.m.all_sessions()   # a non-string cwd must not crash the fold

    def test_log_rotates(self):
        self.m.LOG_MAX = 100
        for i in range(20):
            self.m.log("line {}".format(i))
        self.assertTrue(os.path.exists(self.m.LOG + ".1"))
        self.assertLess(os.path.getsize(self.m.LOG), 200)
        self.assertEqual(stat.S_IMODE(os.stat(self.m.LOG).st_mode), 0o600)

    def test_log_strips_control_characters(self):
        self.m.log("evil \x1b]52;c;aGk=\x07 title")
        with open(self.m.LOG) as f:
            self.assertNotIn("\x1b", f.read())


if __name__ == "__main__":
    unittest.main()

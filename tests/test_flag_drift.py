"""Does the flag knowledge still match the installed Claude Code? Skipped when claude is not
installed. A failure here means a new flag needs a table entry (and a test in test_argv)."""
import re
import shutil
import subprocess
import unittest

from helpers import Sandbox

SELF_FLAGS = {"-h", "--help", "-v", "--version"}


@unittest.skipUnless(shutil.which("claude"), "claude not installed")
class TestFlagDrift(Sandbox):
    def help_flags(self):
        out = subprocess.run(["claude", "--help"], capture_output=True, text=True, timeout=60).stdout
        flags = {}
        for line in out.splitlines():
            m = re.match(r"^  (-[^ ].*?)(?:\s{2,}|$)", line)      # option lines are indented exactly two spaces
            if not m:
                continue
            spec = m.group(1)
            arity = "variadic" if "...>" in spec or "...]" in spec else "optional" if "[" in spec else "value" if "<" in spec else "bool"
            for name in re.findall(r"(--?[A-Za-z][\w-]*)", spec.split(" <")[0].split(" [")[0]):
                flags[name] = arity
        return flags

    def test_every_flag_is_known(self):
        m = self.m
        known = (m.VALUE_FLAGS | m.VARIADIC_FLAGS | m.OPTIONAL_VALUE_FLAGS | m.BOOL_FLAGS
                 | m.DROP_WITH_VALUE | m.DROP_FLAGS | m.BYPASS_FLAGS)
        flags = self.help_flags()
        self.assertGreater(len(flags), 20, "could not parse `claude --help`")
        unknown = sorted(f for f in flags if f not in known and f not in SELF_FLAGS)
        self.assertEqual(unknown, [], "new claude flags; add them to a table in claude-bardo")

    def test_arity_matches(self):
        m = self.m
        allowed = {
            "value": m.VALUE_FLAGS | m.DROP_WITH_VALUE,
            "variadic": m.VARIADIC_FLAGS | m.DROP_WITH_VALUE,
            "optional": m.OPTIONAL_VALUE_FLAGS | m.DROP_WITH_VALUE,
            "bool": m.BOOL_FLAGS | m.DROP_FLAGS | m.BYPASS_FLAGS,
        }
        wrong = sorted("{} is {}".format(f, a) for f, a in self.help_flags().items()
                       if f not in SELF_FLAGS and any(f in s for s in allowed.values()) and f not in allowed[a])
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()

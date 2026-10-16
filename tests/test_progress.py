"""Slow work shows a progress line on stderr, so a command never looks hung: only on a
terminal, only once the work is slow, and erased before the results print."""
import io
import time
from unittest import mock

from helpers import Sandbox


class Terminal(io.StringIO):
    def isatty(self):
        return True


class TestProgress(Sandbox):
    def spin(self, seconds, err, **kw):
        with mock.patch.object(self.m.sys, "stderr", err):
            with self.m.Progress("reading transcripts", 3, **kw) as p:
                p.step()
                time.sleep(seconds)
        return err.getvalue()

    def test_draws_a_count_and_erases_itself(self):
        out = self.spin(0.3, Terminal(), delay=0)
        self.assertIn("reading transcripts 1/3", out)
        self.assertTrue(out.endswith("\r\x1b[K"))

    def test_fast_work_draws_nothing(self):
        self.assertEqual(self.spin(0, Terminal(), delay=0.5), "")

    def test_nothing_off_a_terminal(self):
        self.assertEqual(self.spin(0.3, io.StringIO(), delay=0), "")

    def test_nothing_on_a_dumb_terminal(self):
        with mock.patch.dict(self.m.os.environ, {"TERM": "dumb"}):
            self.assertEqual(self.spin(0.3, Terminal(), delay=0), "")

"""Load claude-bardo as a module inside a throwaway sandbox (its own HOME, Claude config
dir and state dir), so no test ever reads or writes the developer's real sessions."""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "claude-bardo")


def load(env):
    """Import the script with `env` applied (its paths are read at import time)."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        loader = importlib.machinery.SourceFileLoader("claude_bardo_under_test", TOOL)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return mod


class Sandbox(unittest.TestCase):
    """A fresh module per test, pointed at temp dirs, blind to real running claude processes."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="bardo-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.claude_dir = os.path.join(self.tmp, "claude")
        self.state = os.path.join(self.tmp, "state")
        for d in (self.home, os.path.join(self.claude_dir, "sessions"), os.path.join(self.claude_dir, "projects")):
            os.makedirs(d)
        self.env = {
            "HOME": self.home,
            "CLAUDE_CONFIG_DIR": self.claude_dir,
            "CLAUDE_BARDO_DIR": self.state,
            "CLAUDE_BARDO_TERMINAL": "ghostty",
            "CLAUDE_BARDO_LAUNCHER": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.m = load(self.env)
        self.m.running_claude_ids = lambda: set()   # never see the developer's live claude processes

    # --- fixtures -------------------------------------------------------------------
    def workdir(self, name="proj"):
        d = os.path.join(self.tmp, "work", name)
        os.makedirs(d, exist_ok=True)
        return d

    def transcript(self, sid, cwd, lines=()):
        slug = "".join(c if c.isalnum() else "-" for c in cwd)
        d = os.path.join(self.claude_dir, "projects", slug)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, sid + ".jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "user", "cwd": cwd, "message": {"content": "hi"}}) + "\n")
            for rec in lines:
                f.write(json.dumps(rec) + "\n")
        return p

    def start(self, sid, cwd, argv=None, **kw):
        rec = {"ts": self.m.now_iso(), "event": "start", "session_id": sid, "cwd": cwd, "pid": None,
               "argv": argv or ["claude"], "argv_exact": True}
        rec.update(kw)
        self.m.append(rec)
        return rec

    def end(self, sid, reason, **kw):
        rec = {"ts": self.m.now_iso(), "event": "end", "session_id": sid, "reason": reason, "pid": None}
        rec.update(kw)
        self.m.append(rec)

    def session(self, sid):
        return next((s for s in self.m.all_sessions() if s.id == sid), None)

    def run_tool(self, *args, stdin=None, env=None):
        e = dict(os.environ, **self.env)
        e.update(env or {})
        return subprocess.run([sys.executable, TOOL] + list(args), input=stdin, capture_output=True, text=True, env=e)


def uuid(n):
    """Deterministic, valid session ids: uuid(1) = 00000000-0000-4000-8000-000000000001."""
    return "00000000-0000-4000-8000-{:012x}".format(n)

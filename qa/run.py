#!/usr/bin/env python3
"""claude-bardo QA runner: start real Claude Code sessions, crash them the four ways a
machine loses them, restore, and check that exactly the right ones came back.

  python3 qa/run.py                  # iTerm windows (watch it happen)
  python3 qa/run.py --backend tmux   # headless, in a private tmux server
  python3 qa/run.py --keep           # leave transcripts and the run's registry behind

Isolation: the sessions use their own registry (qa/.results/<run>/state) and load only
this runner's hooks (--setting-sources project,local), so your real sessions, hooks and
registry are never touched. Cost: a handful of one-word replies from --model (haiku).
See qa/suite.md for the cases and qa/README.md for the report format.
"""
import argparse
import datetime
import glob
import html
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "claude-bardo")
RESULTS = os.path.join(ROOT, "qa", ".results")
WORK = os.path.join(RESULTS, "work")          # stable across runs: Claude's trust prompt is answered once
PROJECTS = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")
LIVE = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "sessions")
DOWN, ENTER = "\x1b[B", "\r"

# name, how it dies, what that stands for, extra flags, wrap in caffeinate, secret word
SPECS = [
    ("alpha", "SIGHUP", "terminal crash", [], False, "juniper"),
    ("bravo", "SIGTERM", "reboot", [], True, "saffron"),
    ("charlie", "SIGKILL", "power loss", [], False, "quartz"),
    ("delta", "SIGTERM", "reboot, with a bypass flag", ["--allow-dangerously-skip-permissions"], False, "lantern"),
    ("echo", "/exit", "deliberate exit", [], False, "meadow"),
]
RESTORED = ("alpha", "bravo", "charlie", "delta")


def sh(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    try:
        return subprocess.run(cmd, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 99, "", str(e))


def q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def wait(pred, timeout, step=0.5):
    end = time.monotonic() + timeout
    while True:
        v = pred()
        if v or time.monotonic() > end:
            return v
        time.sleep(step)


# --- terminals ---------------------------------------------------------------------------
class Tmux:
    """A private tmux server (own TMUX_TMPDIR): nothing leaks into the user's tmux."""
    name = "tmux"

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="bardo-qa-")   # short path: tmux sockets have a length limit
        self.env = dict(os.environ, TMUX_TMPDIR=self.dir)
        self.restore_args, self.restore_env = ["--tmux", "--no-attach"], {"TMUX_TMPDIR": self.dir}

    def gate(self):
        return (True, "tmux " + sh(["tmux", "-V"]).stdout.strip()) if shutil.which("tmux") else (False, "tmux not installed")

    def tmux(self, *args):
        return sh(["tmux", "-f", "/dev/null"] + list(args), env=self.env)

    def open(self, name, script):
        first = self.tmux("has-session", "-t", "=qa").returncode != 0
        if first:
            self.tmux("new-session", "-d", "-s", "qa", "-x", "200", "-y", "50", "-n", name, script)
        else:
            self.tmux("new-window", "-d", "-t", "=qa", "-n", name, script)
        return ("target", "=qa:" + name)

    def _target(self, h):
        if h[0] == "target":
            return h[1]
        for line in self.tmux("list-panes", "-a", "-F", "#{pane_tty} #{pane_id}").stdout.splitlines():
            tty, pane = line.split()
            if tty == h[1]:
                return pane
        return None

    def screen(self, h):
        t = self._target(h)
        return self.tmux("capture-pane", "-p", "-t", t).stdout if t else ""

    def keys(self, h, text):
        t = self._target(h)
        if t:
            self.tmux("send-keys", "-t", t, "-l", text)

    def type(self, h, text):
        t = self._target(h)
        if t:
            self.tmux("send-keys", "-t", t, "-l", text)
            time.sleep(0.3)
            self.tmux("send-keys", "-t", t, "Enter")

    def close_all(self):
        self.tmux("kill-server")
        shutil.rmtree(self.dir, ignore_errors=True)


class ITerm:
    """iTerm2 over AppleScript. Values travel as argv items, never spliced into the script."""
    name = "iterm"
    FIND = ['tell application "iTerm"', "repeat with w in windows", "repeat with t in tabs of w",
            "repeat with s in sessions of t", "if (tty of s) is (item 1 of argv) then"]
    END = ["end if", "end repeat", "end repeat", "end repeat", "end tell"]

    def __init__(self):
        self.windows = []
        self.restore_args, self.restore_env = ["--terminal", "iterm"], {}

    def osa(self, lines, *args, timeout=30):
        cmd = ["/usr/bin/osascript"]
        for l in ["on run argv"] + lines + ["end run"]:
            cmd += ["-e", l]
        return sh(cmd + list(args), timeout=timeout)

    def gate(self):
        if sys.platform != "darwin":
            return False, "iTerm backend needs macOS"
        if not any(os.path.isdir(os.path.join(d, "iTerm.app")) for d in ("/Applications", os.path.expanduser("~/Applications"))):
            return False, "iTerm.app not installed"
        p = self.osa(['tell application "iTerm" to return version'], timeout=60)
        if p.returncode != 0:
            return False, "cannot control iTerm ({}); allow it under System Settings > Privacy & Security > Automation".format(
                p.stderr.strip()[:120])
        return True, "iTerm " + p.stdout.strip()

    def open(self, name, script):
        p = self.osa(['tell application "iTerm"', "set w to (create window with default profile command (item 1 of argv))",
                      "return id of w", "end tell"], script)
        wid = p.stdout.strip()
        if wid:
            self.windows.append(wid)
        return ("window", wid)

    def _session(self, h, body, *args):
        if h[0] == "window":
            return self.osa(['tell application "iTerm"', "tell current session of (window id ((item 1 of argv) as integer))"]
                            + body + ["end tell", "end tell"], h[1], *args)
        return self.osa(self.FIND + body + self.END, h[1], *args)

    def screen(self, h):
        return self._session(h, ["return contents"] if h[0] == "window" else ["return contents of s"]).stdout

    def keys(self, h, text):
        body = ["write text (item 2 of argv) newline NO"] if h[0] == "window" else ["tell s to write text (item 2 of argv) newline NO"]
        self._session(h, body, text)

    def type(self, h, text):
        self.keys(h, text)
        time.sleep(0.3)
        self.keys(h, ENTER)

    def close_tty(self, tty):
        self.osa(self.FIND + ["close s"] + self.END, tty)

    def close_all(self):
        for wid in self.windows:
            self.osa(['tell application "iTerm"', "try", "close (window id ((item 1 of argv) as integer))", "end try", "end tell"], wid)


# --- the run -------------------------------------------------------------------------------
class Run:
    def __init__(self, args):
        self.args = args
        self.id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(RESULTS, self.id)
        self.state = os.path.join(self.dir, "state")
        self.settings = os.path.join(self.dir, "qa-settings.json")
        self.term = ITerm() if args.backend == "iterm" else Tmux()
        self.cases = []
        self.s = {name: {"name": name, "signal": sig, "stands_for": why, "extra": extra, "caffeinate": caff, "word": word,
                         "id": str(uuid.uuid4()), "cwd": os.path.join(WORK, name)}
                  for name, sig, why, extra, caff, word in SPECS}
        self.version = ""
        self.halt = None
        self.launched = False

    # reporting
    def case(self, cid, name, covers, fn, critical=False):
        """Run one case. A critical case that does not PASS stops the run: everything after
        it is NOT_RUN, never a FAIL reported against sessions that never came up."""
        if self.halt:
            status, evidence = "NOT_RUN", "{} did not pass".format(self.halt)
        else:
            t0 = time.monotonic()
            try:
                status, evidence = fn()
            except Exception as e:  # noqa: BLE001
                status, evidence = "FAIL", "harness error: {!r}".format(e)
            evidence = "{} ({:.0f}s)".format(evidence, time.monotonic() - t0)
        self.cases.append({"id": cid, "name": name, "covers": covers, "status": status, "evidence": evidence})
        if critical and status != "PASS" and not self.halt:
            self.halt = cid
        print("  {:<4} {:<13} {}  {}".format(cid, status, name, evidence), flush=True)
        return status == "PASS"

    def bardo(self, *args, env=None):
        e = dict(os.environ, CLAUDE_BARDO_DIR=self.state, PYTHONDONTWRITEBYTECODE="1")
        e.update(env or {})
        return sh([sys.executable, TOOL] + list(args), env=e)

    def listing(self, *flags):
        rows = [json.loads(l) for l in self.bardo("list", "--json", *flags).stdout.splitlines() if l.strip()]
        return {r["id"]: r for r in rows}

    def registry(self):
        path = os.path.join(self.state, "registry.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def transcript(self, s):
        hits = glob.glob(os.path.join(glob.escape(PROJECTS), "*", s["id"] + ".jsonl"))
        return hits[0] if hits else None

    def replies(self, s):
        """Assistant text in the session's transcript, oldest first."""
        p = self.transcript(s)
        out = []
        if not p:
            return out
        with open(p, errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                content = (rec.get("message") or {}).get("content")
                parts = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
                text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
                if text.strip():
                    out.append(text.strip())
        return out

    def procs(self):
        """[(pid, args)] of every process, for finding relaunched sessions."""
        out = []
        for line in sh(["/bin/ps", "-axww", "-o", "pid=,args="]).stdout.splitlines():
            pid, _, args = line.strip().partition(" ")
            if pid.isdigit():
                out.append((int(pid), args))
        return out

    def resumed(self, s):
        for pid, args in self.procs():
            toks = args.split()
            if toks and os.path.basename(toks[0]) == "claude" and "--resume" in toks and s["id"] in toks:
                return pid, toks
        return None

    def tty(self, pid):
        t = sh(["/bin/ps", "-o", "tty=", "-p", str(pid)]).stdout.strip()
        return "/dev/" + t if t and t not in ("??", "-") else None

    def untrust_prompt(self, h):
        """Claude asks before working in a new folder; its default answer is "No, exit"."""
        scr = self.term.screen(h)
        if "trust this folder" in scr:
            self.term.keys(h, DOWN)
            time.sleep(0.4)
            self.term.keys(h, ENTER)
            return True
        return False

    # cases
    def gate(self):
        problems, facts = [], []
        claude = shutil.which("claude")
        if not claude:
            problems.append("claude not on PATH")
        else:
            self.version = sh([claude, "--version"]).stdout.strip()
            facts.append(self.version)
            auth = sh([claude, "auth", "status"])
            if auth.returncode != 0 or '"loggedIn": true' not in auth.stdout:
                problems.append("claude is not logged in")
        v = self.bardo("--version")
        if v.returncode != 0:
            problems.append("claude-bardo does not run: " + v.stderr.strip()[:100])
        else:
            facts.append(v.stdout.strip())
        if any(c in TOOL for c in " '\"\\"):
            problems.append("the repo path contains spaces or quotes (iTerm cannot launch it)")
        ok, why = self.term.gate()
        (facts if ok else problems).append(why)
        if problems:
            return "FAIL", "; ".join(problems)
        return "PASS", ", ".join(facts)

    def setup(self):
        os.makedirs(self.state, mode=0o700)
        hook = {"hooks": [{"type": "command", "command": "{} hook".format(TOOL), "timeout": 10}]}
        with open(self.settings, "w") as f:
            json.dump({"hooks": {"SessionStart": [hook], "SessionEnd": [hook]}}, f, indent=2)
        path = os.environ.get("PATH", "")
        for s in self.s.values():
            os.makedirs(s["cwd"], exist_ok=True)
            claude = ["claude", "--setting-sources", "project,local", "--settings", self.settings,
                      "--model", self.args.model, "--permission-mode", "default"] + s["extra"] + [
                "--session-id", s["id"], "Reply with exactly one lowercase word and nothing else: {}".format(s["word"])]
            if s["caffeinate"]:
                claude = ["caffeinate", "-i", "--"] + claude
            script = os.path.join(self.dir, "launch-{}.sh".format(s["name"]))
            with open(script, "w") as f:
                f.write("#!/bin/sh\n# claude-bardo QA: session {}\n".format(s["name"]))
                f.write("export PATH={}\nexport CLAUDE_BARDO_DIR={}\ncd {} || exit 1\n".format(q(path), q(self.state), q(s["cwd"])))
                f.write("exec " + " ".join(q(t) for t in claude) + "\n")
            os.chmod(script, 0o755)
            s["script"] = script

    def tc_launch(self):
        self.setup()
        self.launched = True
        for s in self.s.values():
            s["h"] = self.term.open(s["name"], s["script"])
            time.sleep(0.8)
        t0 = time.monotonic()

        def answered():
            for s in self.s.values():
                if not self.replies(s):
                    self.untrust_prompt(s["h"])
            return all(self.replies(s) for s in self.s.values())

        ok = wait(answered, self.args.timeout, step=2)
        got = {n: (self.replies(s) or ["-"])[0][:20] for n, s in self.s.items()}
        if not ok:
            return "INCONCLUSIVE", "not every session answered within {}s: {}".format(self.args.timeout, got)
        right = sum(1 for s in self.s.values() if s["word"] in self.replies(s)[0].lower())
        return "PASS", "5/5 sessions answered in {:.0f}s ({}/5 with their word)".format(time.monotonic() - t0, right)

    def tc_hook(self):
        starts = {r["session_id"]: r for r in self.registry() if r.get("event") == "start"}
        bad = []
        for s in self.s.values():
            r = starts.get(s["id"])
            if not r:
                bad.append("{}: no start record".format(s["name"]))
                continue
            s["pid"] = r.get("pid")
            if not r.get("pid") or not r.get("argv_exact"):
                bad.append("{}: pid={} exact={}".format(s["name"], r.get("pid"), r.get("argv_exact")))
            if "--model" not in (r.get("argv") or []):
                bad.append("{}: argv lost --model".format(s["name"]))
            if s["caffeinate"] and r.get("caffeinate") != ["-i"]:
                bad.append("{}: caffeinate={}".format(s["name"], r.get("caffeinate")))
        with open(os.path.join(self.state, "registry.jsonl")) as f:
            if "Reply with exactly" in f.read():
                bad.append("the first prompt was written to the registry")
        return ("FAIL", "; ".join(bad)) if bad else ("PASS", "5 start records with pid + exact argv; no prompt text on disk; caffeinate seen")

    def tc_live(self):
        rows = self.listing()
        st = {n: (rows.get(s["id"]) or {}).get("status") for n, s in self.s.items()}
        return ("PASS" if all(v == "live" for v in st.values()) else "FAIL"), "statuses {}".format(st)

    def kill(self):
        for s in self.s.values():
            if s["signal"] == "/exit":
                self.term.type(s["h"], "/exit")
            elif s.get("pid"):
                try:
                    os.kill(s["pid"], getattr(signal, s["signal"]))
                except ProcessLookupError:
                    pass

    def tc_endings(self):
        self.kill()
        gone = wait(lambda: not any(self.alive(s.get("pid")) for s in self.s.values()), 30)
        expect = {self.s[n]["id"] for n in ("alpha", "bravo", "delta", "echo")}
        wait(lambda: expect <= {r["session_id"] for r in self.registry() if r.get("event") == "end"}, 10)
        time.sleep(1)                       # a straggling SessionEnd for charlie would show up here
        ends = {r["session_id"]: r.get("reason") for r in self.registry() if r.get("event") == "end"}
        seen = {n: ends.get(s["id"], "(no SessionEnd)") for n, s in self.s.items()}
        ev = ", ".join("{} {}: {}".format(n, self.s[n]["signal"], seen[n]) for n in self.s)
        ok = gone and seen["echo"] == "prompt_input_exit" and seen["charlie"] == "(no SessionEnd)" and all(
            seen[n] not in ("prompt_input_exit", "clear", "logout", "resume", "(no SessionEnd)") for n in ("alpha", "bravo", "delta"))
        return ("PASS" if ok else "FAIL"), ("" if gone else "processes still alive; ") + ev

    def alive(self, pid):
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def tc_classify(self):
        rows = self.listing("--all")
        st = {n: (rows.get(s["id"]) or {}).get("status") for n, s in self.s.items()}
        want = {"alpha": "interrupted", "bravo": "interrupted", "charlie": "killed", "delta": "interrupted", "echo": "closed"}
        bypass = (rows.get(self.s["delta"]["id"]) or {}).get("bypass")
        ok = st == want and bypass == ["--allow-dangerously-skip-permissions"]
        return ("PASS" if ok else "FAIL"), "statuses {}; delta bypass flagged: {}".format(st, bool(bypass))

    def tc_restore(self):
        ids = [self.s[n]["id"] for n in RESTORED]
        p = self.bardo("restore", *ids, *self.term.restore_args, env=self.term.restore_env)
        refused = self.bardo("restore", self.s["echo"]["id"], *self.term.restore_args, env=self.term.restore_env)
        ok = p.returncode == 0 and refused.returncode == 1 and "no restorable session" in refused.stderr
        return ("PASS" if ok else "FAIL"), "restore rc={} ({} windows); echo refused rc={} {}".format(
            p.returncode, p.stdout.count("↺"), refused.returncode, (p.stderr or refused.stderr).strip()[:120])

    def tc_relaunched(self):
        found = wait(lambda: all(self.resumed(self.s[n]) for n in RESTORED), 60, step=1)
        bad, notes = [], []
        for n in RESTORED:
            hit = self.resumed(self.s[n])
            if not hit:
                bad.append("{} not running".format(n))
                continue
            pid, toks = hit
            self.s[n]["new_pid"], self.s[n]["tty"] = pid, self.tty(pid)
            for flag in ("--model", "--settings", "--setting-sources", "--permission-mode"):
                if flag not in toks:
                    bad.append("{} lost {}".format(n, flag))
            if "--allow-dangerously-skip-permissions" in toks:
                bad.append("{} replayed the bypass flag".format(n))
            if self.s[n]["caffeinate"]:
                wrapped = any(a.split()[0].endswith("caffeinate") and self.s[n]["id"] in a and " -i " in a for _, a in self.procs())
                notes.append("bravo under caffeinate: {}".format(wrapped))
                if not wrapped:
                    bad.append("bravo lost its caffeinate wrapper")
        if self.resumed(self.s["echo"]):
            bad.append("echo was relaunched")
        if not found and not bad:
            bad.append("timed out")
        return ("FAIL", "; ".join(bad)) if bad else ("PASS", "4 relaunched with flags intact, bypass dropped, echo left alone; " + "; ".join(notes))

    def tc_live_again(self):
        ok = wait(lambda: all((self.listing().get(self.s[n]["id"]) or {}).get("status") == "live" for n in RESTORED), 30)
        rows = self.listing("--all")
        st = {n: (rows.get(s["id"]) or {}).get("status") for n, s in self.s.items()}
        return ("PASS" if ok and st["echo"] == "closed" else "FAIL"), "statuses {}".format(st)

    def tc_memory(self):
        s = self.s["alpha"]
        if not s.get("tty"):
            return "INCONCLUSIVE", "alpha's relaunched window was not found"
        h = ("tty", s["tty"])
        before = len(self.replies(s))
        wait(lambda: "❯" in self.term.screen(h) or ">" in self.term.screen(h), 20)
        self.term.type(h, "Which single word did you reply with earlier in this conversation? Reply with only that word.")
        ok = wait(lambda: len(self.replies(s)) > before, self.args.timeout, step=2)
        if not ok:
            return "INCONCLUSIVE", "no reply within {}s".format(self.args.timeout)
        reply = self.replies(s)[-1]
        return ("PASS" if s["word"] in reply.lower() else "FAIL"), "asked after the crash, alpha answered {!r}".format(reply[:40])

    def tc_fork(self):
        s = self.s["alpha"]
        known = {r["session_id"] for r in self.registry() if r.get("event") == "start"}
        p = self.bardo("restore", "--fork", s["id"], *self.term.restore_args, env=self.term.restore_env)
        if p.returncode != 0:
            return "FAIL", "restore --fork rc={} {}".format(p.returncode, p.stderr.strip()[:100])

        def forked():
            for pid, args in self.procs():
                toks = args.split()
                if toks and os.path.basename(toks[0]) == "claude" and "--fork-session" in toks and s["id"] in toks:
                    return pid, toks
            return None

        hit = wait(forked, 60, step=1)
        if not hit:
            return "FAIL", "no forked process appeared"
        self.fork = {"pid": hit[0], "tty": self.tty(hit[0])}
        new = wait(lambda: [r for r in self.registry() if r.get("event") == "start" and r["session_id"] not in known
                            and r["session_id"] not in {x["id"] for x in self.s.values()}], 30)
        self.fork["id"] = new[0]["session_id"] if new else None
        still = (self.listing().get(s["id"]) or {}).get("status")
        ok = (bool(new) and still == "live" and self.alive(s.get("new_pid")) and new[0].get("forked_from") == s["id"]
              and "--fork-session" not in (new[0].get("argv") or []))
        return ("PASS" if ok else "FAIL"), "fork registered as {} (argv {}), alpha still {}".format(
            (self.fork["id"] or "nothing")[:8], (new[0].get("argv") if new else None), still)

    def tc_no_double(self):
        p = self.bardo("restore", self.s["alpha"]["id"], "--dry-run", *self.term.restore_args, env=self.term.restore_env)
        return ("PASS" if p.returncode == 1 else "FAIL"), "restoring a live session again: rc={} {}".format(
            p.returncode, p.stderr.strip()[:80])

    # teardown
    def teardown(self):
        f = getattr(self, "fork", None)
        if f and self.alive(f.get("pid")):
            if f.get("tty"):
                self.term.type(("tty", f["tty"]), "/exit")
            wait(lambda: not self.alive(f["pid"]), 10)
            if self.alive(f["pid"]):
                os.kill(f["pid"], signal.SIGTERM)
        if f and isinstance(self.term, ITerm) and f.get("tty"):
            self.term.close_tty(f["tty"])
        if f and f.get("id") and not self.args.keep:
            for p in glob.glob(os.path.join(glob.escape(PROJECTS), "*", f["id"] + ".jsonl")):
                os.remove(p)
        for n, s in self.s.items():
            pid = s.get("new_pid") or s.get("pid")
            if self.alive(pid):
                h = ("tty", s["tty"]) if s.get("tty") else s.get("h")
                if h:
                    self.term.type(h, "/exit")
        wait(lambda: not any(self.alive(s.get("new_pid") or s.get("pid")) for s in self.s.values()), 15)
        for s in self.s.values():
            for pid in (s.get("new_pid"), s.get("pid")):
                if self.alive(pid):
                    os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        if isinstance(self.term, ITerm):
            for s in self.s.values():
                if s.get("tty"):
                    self.term.close_tty(s["tty"])
        self.term.close_all()
        ids = {s["id"] for s in self.s.values()}
        for path in glob.glob(os.path.join(glob.escape(LIVE), "*.json")):   # SIGKILL leaves charlie's pid file behind
            try:
                with open(path) as f:
                    d = json.load(f)
                if d.get("sessionId") in ids and not self.alive(d.get("pid")):
                    os.remove(path)
            except (OSError, ValueError):
                pass
        if not self.args.keep:              # the ids are fresh uuid4s: a transcript named after one is ours
            for s in self.s.values():
                p = self.transcript(s)
                if p:
                    os.remove(p)
                    shutil.rmtree(p[:-len(".jsonl")], ignore_errors=True)

    # report
    def report(self):
        n = len(self.cases)
        tally = {k: sum(1 for c in self.cases if c["status"] == k) for k in ("PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN")}
        icon = "✓" if tally["PASS"] == n else "✗" if tally["FAIL"] else "!"
        tldr = "{} claude-bardo QA: {}/{} PASS · {} · {} · {}".format(
            icon, tally["PASS"], n, self.term.name, self.version or "claude ?", datetime.date.today().isoformat())
        rows = ["| id | name | covers | status | evidence |", "|----|------|--------|--------|----------|"]
        rows += ["| {id} | {name} | {covers} | {status} | {evidence} |".format(**{k: str(v).replace("|", "\\|") for k, v in c.items()})
                 for c in self.cases]
        md = tldr + "\n\n" + "\n".join(rows) + "\n"
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "report.md"), "w") as f:
            f.write(md)
        with open(os.path.join(self.dir, "report.json"), "w") as f:
            json.dump({"title": "claude-bardo QA", "generated": datetime.datetime.now().isoformat(timespec="seconds"),
                       "backend": self.term.name, "claude": self.version, "tally": tally, "cases": self.cases,
                       "sessions": {n: {k: v for k, v in s.items() if k in ("id", "signal", "stands_for", "extra", "caffeinate")}
                                    for n, s in self.s.items()}}, f, indent=2)
        color = {"PASS": "#1a7f37", "FAIL": "#cf222e", "INCONCLUSIVE": "#9a6700", "NOT_RUN": "#6e7781"}
        trs = "".join("<tr><td>{}</td><td>{}</td><td>{}</td><td style='color:{};font-weight:600'>{}</td><td>{}</td></tr>".format(
            *(html.escape(str(c[k])) for k in ("id", "name", "covers")), color[c["status"]], c["status"], html.escape(c["evidence"]))
            for c in self.cases)
        with open(os.path.join(self.dir, "report.html"), "w") as f:
            f.write("<!doctype html><meta charset=utf-8><title>claude-bardo QA</title><style>body{font:14px system-ui;margin:2em}"
                    "td,th{padding:.4em .8em;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}</style>"
                    "<h2>" + html.escape(tldr) + "</h2><table><tr><th>id<th>name<th>covers<th>status<th>evidence" + trs + "</table>")
        print("\n" + md + "\nreport: " + os.path.relpath(os.path.join(self.dir, "report.html"), ROOT))
        return 0 if icon == "✓" else 1

    def main(self):
        print("claude-bardo QA run {} ({} backend, model {})".format(self.id, self.term.name, self.args.model), flush=True)
        os.makedirs(self.dir, exist_ok=True)
        try:
            self.case("TC-00", "sanity gate", "claude installed + logged in, tool runs, terminal controllable", self.gate, critical=True)
            self.case("TC-01", "launch", "5 real sessions start and answer", self.tc_launch, critical=True)
            self.case("TC-02", "hook records", "SessionStart hook: pid, exact argv, caffeinate, no prompt on disk", self.tc_hook)
            self.case("TC-03", "live", "list sees all 5 as live", self.tc_live)
            self.case("TC-04", "four deaths", "SIGHUP / SIGTERM / SIGKILL / /exit and the SessionEnd each leaves", self.tc_endings)
            self.case("TC-05", "classified", "interrupted x3, killed, closed; bypass flagged", self.tc_classify)
            self.case("TC-06", "restore", "restore by id opens windows; a deliberate exit is refused", self.tc_restore)
            self.case("TC-07", "relaunched", "right processes, flags replayed, bypass dropped, caffeinate kept", self.tc_relaunched)
            self.case("TC-08", "live again", "restored sessions re-register through the hook", self.tc_live_again)
            self.case("TC-09", "memory", "a restored session remembers the conversation", self.tc_memory)
            self.case("TC-10", "no doubles", "a live session cannot be restored twice", self.tc_no_double)
            self.case("TC-11", "fork", "restore --fork copies a live session; the original keeps running", self.tc_fork)
        finally:
            if self.launched:
                self.teardown()
        return self.report()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backend", choices=("iterm", "tmux"), default="iterm")
    ap.add_argument("--model", default="haiku", help="model for the test sessions (default haiku: cheap one-word replies)")
    ap.add_argument("--timeout", type=int, default=120, help="seconds to wait for replies")
    ap.add_argument("--keep", action="store_true", help="keep the sessions' transcripts")
    sys.exit(Run(ap.parse_args()).main())


if __name__ == "__main__":
    main()

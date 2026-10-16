#!/usr/bin/env python3
"""Measure the window-close hypothesis (openspec/changes/window-close-is-deliberate) on a
registry: for every session end the hook probed, was the session's terminal still alive, and
did the session end alone? Prints one row per end and what the proposed rule would call it.

  python3 qa/window_close_report.py                          # your registry
  python3 qa/window_close_report.py --dir qa/.results/<run>/state
  python3 qa/window_close_report.py --since 2026-10-01 --window 10

The rule under test: reason `other` + terminal alive + no other end within --window seconds
=> `closed`. Kill criterion: any session that died in a reboot or logout reads `closed`.
Read-only; needs the `anc`/`probe` records the hook writes since 2026-09-30.
"""
import argparse
import datetime
import json
import os
import re

TERM_COMM_RE = re.compile(r"^(ghostty|iTerm2|iTermServer.*|Terminal|tmux.*|alacritty|wezterm-gui|kitty"
                          r"|gnome-terminal-|konsole|xterm)$")
# TERM_PROGRAM -> process name, for sessions that started before the hook recorded ancestors
TERM_PROGRAM_COMM = {"ghostty": "ghostty", "iTerm.app": "iTerm2", "Apple_Terminal": "Terminal", "tmux": "tmux",
                     "WezTerm": "wezterm-gui", "kitty": "kitty", "alacritty": "alacritty"}


def load(path):
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("session_id"):
                recs.append(rec)
    return recs


def ts(rec):
    try:
        return datetime.datetime.fromisoformat(rec.get("ts"))
    except (TypeError, ValueError):
        return None


def terminal_of(start):
    """(pid, comm, lstart, how): the outermost terminal above claude when it started (the
    app, not iTerm's per-session server); by TERM_PROGRAM name when no ancestors were recorded."""
    anc = (start or {}).get("anc")
    if anc:
        hits = [a for a in anc if TERM_COMM_RE.match(a[1] or "")]
        if hits:
            return hits[-1][0], hits[-1][1], hits[-1][2], "anc"
        return None, None, None, "anc: no terminal"
    comm = TERM_PROGRAM_COMM.get((start or {}).get("term") or "")
    return (None, comm, None, "term") if comm else (None, None, None, "unknown")


def alive_at_end(term, probe):
    pid, comm, lstart, how = term
    seen = [tuple(a) for a in (probe.get("terms") or []) + (probe.get("anc") or [])]
    if pid:
        return any(p == pid and s == lstart for p, _, s in seen)
    if comm:
        return any(c == comm for _, c, _ in seen)   # by name: the app was running, not necessarily this window's
    return None


def grok_ids(recs):
    """Sessions whose nearest agent ancestor was Grok Build, not claude: Grok runs
    ~/.claude/settings.json hooks too, and the hook recorded its ends until 2026-10-13."""
    ids = set()
    for r in recs:
        if r.get("event") == "probe":
            agent = next((a[1] for a in r.get("anc") or [] if a[1] in ("claude", "grok")), None)
            if agent == "grok":
                ids.add(r["session_id"])
    return ids


def orphaned(end, probe):
    """claude had no terminal above it any more when its hook ran (its parent chain was cut)."""
    anc = probe.get("anc") or []
    idx = next((i for i, a in enumerate(anc) if a[0] == end.get("pid") or a[1] == "claude"), None)
    if idx is None:
        return None
    return not any(TERM_COMM_RE.match(a[1] or "") for a in anc[idx + 1:])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=os.environ.get("CLAUDE_BARDO_DIR") or os.path.expanduser("~/.local/state/claude-bardo"))
    ap.add_argument("--since", help="only ends at or after this ISO time (local)")
    ap.add_argument("--window", type=int, default=10, help="seconds within which two ends count as together (10)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    recs = load(os.path.join(a.dir, "registry.jsonl"))
    grok = grok_ids(recs)
    starts, rows, ends = {}, [], []
    for i, r in enumerate(recs):
        if r["session_id"] in grok:
            continue
        if r.get("event") == "start":
            starts[r["session_id"]] = r
        elif r.get("event") == "end" and r.get("reason") != "forgotten":
            ends.append((i, r, starts.get(r["session_id"])))   # the start this end closes, not a later resume
    since = datetime.datetime.fromisoformat(a.since).astimezone() if a.since else None
    crash_times = [ts(r) for _, r, _ in ends if r.get("reason") in ("other", "shutdown", None) and ts(r)]
    for i, end, start in ends:
        t = ts(end)
        if t is None or (since and t < since):
            continue
        probe = next((r for r in recs[i + 1:] if r.get("event") == "probe" and r["session_id"] == end["session_id"]), None)
        if probe is None:
            continue
        term = terminal_of(start)
        alive = alive_at_end(term, probe)
        together = sum(1 for c in crash_times if c != t and abs((c - t).total_seconds()) <= a.window) \
            + max(0, sum(1 for c in crash_times if c == t) - 1)
        reason = end.get("reason")
        if reason != "other":
            verdict = "closed" if reason in ("prompt_input_exit", "logout", "clear", "resume") else "interrupted"
        else:
            verdict = "closed" if alive and together == 0 else "interrupted"
        rows.append({"ts": end["ts"], "id": end["session_id"][:8], "reason": reason, "terminal": term[1],
                     "how": term[3], "alive": alive, "orphaned": orphaned(end, probe), "together": together,
                     "verdict": verdict, "name": (start or {}).get("name") or ""})
    if a.json:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    if not rows:
        print("no probed ends yet in {} (the hook records them since 2026-09-30)".format(a.dir))
        return 0
    fmt = "{:<19}  {:<8}  {:<17}  {:<18}  {:<5}  {:<8}  {:>8}  {:<11}  {}"
    print(fmt.format("ended", "id", "reason", "terminal (how)", "alive", "orphaned", "together", "rule says", "name"))
    for r in rows:
        print(fmt.format(r["ts"][:19].replace("T", " "), r["id"], str(r["reason"])[:17],
                         "{} ({})".format(r["terminal"] or "?", r["how"])[:18], str(r["alive"]), str(r["orphaned"]),
                         r["together"], r["verdict"], r["name"][:40]))
    other = [r for r in rows if r["reason"] == "other"]
    print("\n{} probed ends, {} with reason other: {} would be closed by the rule, {} stay interrupted".format(
        len(rows), len(other), sum(r["verdict"] == "closed" for r in other), sum(r["verdict"] != "closed" for r in other)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

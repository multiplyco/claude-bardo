## Why

Closing a terminal window or tab is how most people end a session, and Claude Code reports it
exactly like a terminal crash or a reboot: a SessionEnd with reason `other`. So every window you
close stays restorable. On the author's machine that was 62 sessions over 12 days. The latest-wave
pre-selection keeps them from being relaunched by accident, but they crowd `list` and the picker.
A session should deregister itself when the user closes its window.

## What Changes

- At SessionStart, the hook also records the session's **terminal ancestor** (the Ghostty, iTerm,
  tmux server… process above claude): its pid and start time.
- At SessionEnd with reason `other`, the hook records whether that ancestor is still alive (and
  the same process), and the time.
- Classification: a session that ended **alone** while its terminal lived on is `closed`
  (note: "window closed"). A session whose terminal died, or that ended together with others (a
  quit, a crash, a reboot), stays `interrupted`.
- `closed` by window is still listed by `list --all` and restorable by explicit id: deregistered,
  never destroyed.

## The risk that decides this

Misreading a **reboot** as a window close means a session is silently not offered after the
reboot: the one failure this tool exists to prevent. At shutdown the terminal app may still be
alive when each session's hook runs. The "ended together" rule is the guard (a reboot ends every
session within seconds), and it must be measured, not assumed.

## Hypothesis and kill criteria

- **Hypothesis:** "terminal alive at SessionEnd, and no other session ended within N seconds" is
  true for a user closing a window and false for crashes, quits, logouts and reboots.
- **Measure first** (new QA cases, plus one manual reboot and logout): close one iTerm window;
  quit iTerm with three sessions open; `kill -9` the terminal; `tmux kill-window`; reboot; log
  out. Record, per session, the ancestor's liveness at SessionEnd and the spread of end times.
- **Kill:** if in any reboot or logout run a session is classified `closed`, drop the change and
  keep the wave pre-selection as the only mitigation.

## Measurement (recording since 2026-09-30)

The hook already records the raw data, and nothing reads it: `anc` on start records (the
ancestors: pid, name, start time) and a `probe` event after each end (the ancestors plus every
terminal process alive at that moment), written after the end record so it can never cost it.
`qa/window_close_report.py` applies the rule to any registry and prints what it would decide.
"The terminal" is the outermost terminal process above claude: iTerm2, not its per-session
iTermServer; the tmux server, not the terminal its client runs in.

First results, tmux, isolated registry, 2026-09-30:

| case | terminal alive | ended together | rule says |
|------|----------------|----------------|-----------|
| `kill-window` on one of three sessions | yes | no | closed |
| `kill-server` with two sessions (a terminal quit) | no (parents cut) | yes | interrupted |
| QA's direct SIGHUP/SIGTERM to three sessions at once | yes | yes | interrupted |

Both guards point the right way on the quit independently. A close followed by a quit inside
the window reads as "together": that errs towards interrupted, the safe side. Still to measure:
the reboot (the first since 2026-08-28), a logout, Ghostty and iTerm window closes (accumulating
from daily use).

## Scope

- In: Ghostty, iTerm, Terminal, tmux (the QA-covered terminals).
- Out: guessing intent for sessions without a recorded ancestor (older records stay as today).

## Capabilities

### New Capabilities
- `window-close-detection`: recording the terminal ancestor and classifying a solitary end with a
  live terminal as deliberate.

### Modified Capabilities
- None yet (no baseline specs exist; this refines today's `other` = restorable rule).

## Impact

- `claude-bardo`: hook (start and end records gain `term_pid`, `term_start`, `term_alive`), the
  fold (`end_status`), `list` notes. Registry stays schema `v: 1` (fields are additive).
- QA runner: the measurement cases above. Prior art: `overnightworks/claude-revive` uses the
  "terminal still alive" signal alone; the "ended together" guard is what this adds.

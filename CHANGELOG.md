# Changelog

## 0.1.0 (2026-10-16)

First public release. Verified against Claude Code 2.1.285 on macOS, end to end in iTerm and tmux.

- Remembers every interactive session through the SessionStart/SessionEnd hooks and relaunches the
  ones that died, each in its own window: Ghostty, iTerm, Terminal, Alacritty, WezTerm, kitty,
  tmux, or any terminal through `CLAUDE_BARDO_LAUNCHER`.
- Replays each session's flags from its exact argv; never replays the prompt, session selectors,
  one-shot modes or `--worktree`; drops permission bypass unless `restore --keep-bypass`.
- `install`/`uninstall` merge the hooks into `settings.json` without touching anyone else's;
  `install --launchd` opens the picker at login when something died.
- The picker pre-selects only the latest death wave (one reboot or crash), not every session that
  ever died: closing a window counts as a crash too.
- `doctor`, `list --json`, `resume`, registry schema `v: 1`, documented exit codes.
- Private state (`0700`/`0600`), a registry lock, torn-line repair, no network access.
- Reads only what each transcript gained since the last command (a cache in the state dir), and
  shows a progress line on a terminal while it reads, so nothing ever looks hung.
- 95 unit tests and an end-to-end QA runner that crashes real sessions four ways.
- The hook also records where each session lives (its process ancestors at start; its ancestors
  and the live terminals at end), to measure whether a closed window can be told apart from a
  reboot. Nothing reads it yet; `qa/window_close_report.py` summarises it.

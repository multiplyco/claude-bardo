# Contributing

Small, sharp changes are welcome. Before a pull request:

```sh
python3 -m unittest discover -s tests     # must pass, including test_flag_drift if claude is installed
python3 -m pyflakes claude-bardo tests qa  # no warnings
python3 qa/run.py --backend tmux          # if you touched restore, the hook or the flag policy
```

House rules:

- **One file, standard library, Python 3.7+.** People install it with `curl`. No dependencies.
  A new command or flag also goes into `claude-bardo.1` (keep it short) and the README.
- **A command never looks hung.** Anything that can take more than half a second runs inside a
  `Progress` (a spinner on stderr, terminals only, erased before the results print).
- **The hook never prints and never fails.** SessionStart stdout is injected into Claude's
  context, and a hook error shows up in every session. `tests/test_hook.py` guards this.
- **A new Claude Code flag** goes into one of the tables at the top of `claude-bardo`, with a case
  in `tests/test_argv.py`. `tests/test_flag_drift.py` fails when `claude --help` knows a flag the
  tables do not. Bump `FLAGS_VERIFIED_ON` when you have checked a new version.
- **Nothing reaches a shell unquoted.** Commands are argv lists; AppleScript gets values as `argv`
  items; tmux window names escape `#`.
- **The replay policy is conservative.** A flag that widens what an agent may do (permission
  bypass and its spellings) is never replayed by default.

Style: match the surrounding code; docstrings over comments; comments say why.

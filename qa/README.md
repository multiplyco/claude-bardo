# QA runner

End-to-end checks against **real** Claude Code sessions. The unit tests in `tests/` prove the
logic; this proves the thing works on a real machine with a real Claude Code, today.

```sh
python3 qa/run.py                   # iTerm windows: watch them open, die and come back
python3 qa/run.py --backend tmux    # headless, in a private tmux server
```

## What a run does

It starts five sessions (`alpha` to `echo`), each asked to reply with one secret word, then kills
them the ways a machine loses them: SIGHUP (terminal crash), SIGTERM (reboot, twice, one of them
with a permission-bypass flag), SIGKILL (power loss) and `/exit` (on purpose). It restores the
four that should come back, checks each relaunched process and its flags, then asks one of them
what its word was. The cases are in [`suite.md`](suite.md).

## Isolation

- The sessions load only this runner's hooks (`--setting-sources project,local --settings
  <run>/qa-settings.json`), so your own hooks never see them.
- They register in `qa/.results/<run>/state`, never in your registry.
- Restores are by explicit id, so nothing else that died on your machine is relaunched.
- The tmux backend uses its own server (`TMUX_TMPDIR`); the iTerm backend closes only the windows
  it opened.
- Teardown ends every test session, removes their transcripts and the pid file SIGKILL leaves
  behind. `--keep` keeps the transcripts.
- The work directories live in `qa/.results/work/`, so Claude's "trust this folder?" prompt comes
  up once, ever. The runner answers it.

Cost: a few one-word replies from `--model haiku`. Time: under a minute.

## Statuses

`PASS`, `FAIL`, `INCONCLUSIVE` (infrastructure was slow: a reply never came, not a regression) and
`NOT_RUN`. `TC-00` is the sanity gate (claude installed and logged in, the tool runs, the terminal
can be driven) and `TC-01` is the launch. If either does not pass, every later case is `NOT_RUN`,
so a broken setup is never reported as a broken tool.

## Report

Three tiers, like any good report: a TL;DR line with the tally, a markdown table (one row per
case with a one-line observed fact as evidence), and `qa/.results/<run>/report.{md,json,html}`.
`qa/.results/` is gitignored.

## Adding a case

Add a `tc_*` method returning `(status, evidence)`, register it in `Run.main` with an id, a name
and what it covers, and describe it in `suite.md`. Evidence is the observation, not the verdict:
`alpha answered 'juniper'`, not `memory works`.

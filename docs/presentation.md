---
theme:
  name: gruvbox-dark
  override:
    code:
      alignment: center
      minimum_size: 50
      minimum_margin:
        percent: 2
---

<!-- new_lines: 8 -->
<!-- alignment: center -->

![claude-bardo: Your Claude Code sessions, back after a reboot, a crash or a power cut](banner.png)

<!-- end_slide -->

The problem
===

You have a dozen Claude Code sessions open, across worktrees. Then the laptop reboots.

```
 before                                     after
 ┌───────────────────────────────┐          ┌──────────────────────────┐
 │ ~/code/api    --model opus    │          │ $ claude --resume        │
 │ ~/code/web    --effort high   │  reboot  │                          │
 │ ~/code/ops    --add-dir ../db │  ─────►  │ fifty sessions a project │
 │ ~/code/docs   caffeinate -i   │          │ no windows, no flags     │
 └───────────────────────────────┘          └──────────────────────────┘
```

<!-- pause -->

The conversations are still on disk. What is lost is the **desk**: which window each one
lived in, which directory, which flags it was started with.

You rebuild it by hand, one session at a time.

<!-- end_slide -->

What claude-bardo does
===

It remembers every interactive session and brings back the ones that died:

<!-- incremental_lists: true -->

- each in **its own window**
- in **its own directory**
- with **its own flags**
- **mid-conversation**

<!-- incremental_lists: false -->

<!-- pause -->

**One file.** Python 3.7+, standard library, no dependencies.

**No daemon.** Claude Code's own hooks do the recording.

**No network.** No sockets, no telemetry, no update check.

<!-- end_slide -->

Why "bardo"?
===

> In Tibetan Buddhism the *bardo* is the state between death and rebirth.
> The *Bardo Thödol* teaches that the dead who recognise the clear light are released,
> and the rest are carried back into rebirth by unfinished karma.

<!-- pause -->

Same rule here:

| a session that | is |
|---|---|
| was ended on purpose (`/exit`, `/clear`, `/resume`) | **released** |
| died with unfinished work (crash, reboot, power cut) | **brought back** |

`claude-bardo list` shows who is in the in-between.

<!-- end_slide -->

Install it once
===

```sh
mkdir -p ~/.local/bin            # and put it on your PATH
curl -fsSLo ~/.local/bin/claude-bardo \
https://raw.githubusercontent.com/multiplyco/claude-bardo/main/claude-bardo
chmod +x ~/.local/bin/claude-bardo

claude-bardo install --dry-run   # show the two hooks it would add
claude-bardo install             # add them, register what runs now
```

<!-- pause -->

That is the whole setup.

- Every session **registers itself** as it starts and **records how it ended**.
- There is nothing to remember to run before a reboot.
- `install` backs up `~/.claude/settings.json` and never touches anyone else's hooks.

<!-- end_slide -->

After a reboot or a crash
===

```sh
claude-bardo            # what died, what is live
claude-bardo restore    # picker, the last crash pre-selected: press Enter
```

<!-- pause -->

What `claude-bardo` shows (illustrative):

```
id        status        age  name               directory
01a0fbe7  live           1m  release notes      ~/code/docs
01a0fad5  interrupted    6m  refactor billing   ~/code/api
01a0fb43  interrupted    6m  landing page copy  ~/code/web
01a0f6c1  killed         6m  infra migration    ~/code/ops
01a0e74e  interrupted    3d  auth spike         ~/code/api
```

<!-- pause -->

The three that died 6 minutes ago went down together, in the last crash or reboot:
`restore` pre-selects them. The one from 3 days ago is listed below them, unselected.

<!-- end_slide -->

How it works
===

```
 claude starts ──► SessionStart hook ──┐
                                       ├──► registry.jsonl
 claude ends ────► SessionEnd hook ────┘    a JSON line per start and end:
                   (with a reason)          directory, exact flags, pid,
                                            transcript, end reason
 kill -9, power cut: no hook runs,
 but ~/.claude/sessions/<pid>.json lingers
```

<!-- pause -->

```
 claude-bardo restore
   1. fold the registry and Claude Code's process files into a status
   2. open the picker, the latest wave pre-selected
   3. a new window each:  cd <dir> && claude <flags> --resume <id>
```

No daemon, no polling: Claude Code calls the hook, the hook appends a line.

<!-- end_slide -->

How it knows what died
===

| what happened | what Claude Code leaves | status |
|---|---|---|
| terminal crash (SIGHUP) | SessionEnd, reason `other` | `interrupted` |
| reboot, macOS logout (SIGTERM) | SessionEnd, reason `other` | `interrupted` |
| `kill -9`, power loss | no SessionEnd, `<pid>.json` lingers | `killed` |
| `/exit`, `/clear`, `/resume`, `/logout` | SessionEnd, a deliberate reason | `closed` |

<!-- pause -->

- `interrupted` and `killed` come back. `closed` never does.
- An end reason it has never seen counts as a crash, and says so:
  losing a session is the one failure this tool exists to prevent.

<!-- end_slide -->

The latest wave
===

Closing a terminal window is a SIGHUP too, so the registry also remembers
sessions you closed days ago. A reboot kills everything within seconds.

```
 older deaths (windows you closed)             the latest wave
 ─────●───────────────●───────────────────────●●●●─────►  time
   Mon 14:02       Wed 11:40               Fri 09:12
     [ ]             [ ]                  [x][x][x][x]
 listed below, unselected             pre-selected: press Enter
```

<!-- pause -->

- The picker pre-selects the sessions that died within **30 minutes** of the newest death.
- Older deaths are listed below it, unselected. `forget` drops one for good.
- `restore` hides deaths older than 14 days unless you pass `--older`.

<!-- end_slide -->

What gets replayed
===

A restored session runs `claude <flags> --resume <id>` in its original directory.
The flags come from the process's **exact argv** (the kernel's, not `ps` text).

- **Replayed:** known flags and their values (`--model`, `--effort`, `--settings`,
  `--add-dir`, ...), and a `caffeinate -i --` wrapper.
- **Never:** the prompt you typed (it is not even stored), and `--resume`, `--continue`,
  `--session-id`, `--name`, `-p`, `--bg`, `--worktree`.
- **Dropped unless `restore --keep-bypass`:** `--dangerously-skip-permissions` and every
  other spelling of permission bypass.
- **Dropped and named** in the restored window: flags newer than this release.

<!-- pause -->

Why drop the bypass? Killing a terminal is the emergency stop for a runaway agent,
and this tool counts that as a crash. **A crash must not re-arm it.**

<!-- end_slide -->

Rehearse it without rebooting
===

```sh
# copy your live sessions into iTerm windows
claude-bardo restore --fork --terminal iterm
```

<!-- pause -->

- Each copy runs `claude --resume <id> --fork-session`: same directory, same flags,
  the whole conversation, under a **new** session id.
- The originals keep running where they are.
- A full dress rehearsal of a restore, and a way to move your sessions to another terminal.

<!-- pause -->

When you are done, quit that terminal and clean up the copies:

```sh
claude-bardo forget --forks
```

<!-- end_slide -->

The commands
===

| command | does |
|---|---|
| `list` | what died, what is live (the default); `--all`, `--json` |
| `restore [ids]` | picker, `--all` or id prefixes; `--tmux`, `--terminal`, `--dry-run` |
| `restore --fork` | copy your live sessions, originals untouched |
| `resume <id>` | bring one session back in *this* terminal |
| `forget <ids>` | "I closed that on purpose": it leaves the picker |
| `prune` | drop closed history older than `--days` (30) |
| `snapshot` | register sessions that ran before you installed |
| `doctor` | check the hooks, state, terminal and Claude Code internals |
| `install` / `uninstall` | the hooks, and an optional `--launchd` login agent |

Exit codes: `0` ok, `1` failure, `2` usage, `3` nothing to restore or nothing selected.

<!-- end_slide -->

Terminals, and the login agent
===

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Where sessions come back**

- **Ghostty** by default
- `--terminal` or `CLAUDE_BARDO_TERMINAL`: `iterm`, `terminal`, `alacritty`, `wezterm`, `kitty`
- `restore --tmux` from any terminal, also on Linux
- `fzf` (optional) makes the picker nicer

<!-- column: 1 -->

**At login**

```sh
claude-bardo install --launchd
```

If anything died in the last shutdown, it opens **one** window with the picker.
Nothing relaunches until you press Enter, and it never keeps a permission bypass.

<!-- reset_layout -->

Any other terminal, through a template:

```sh
export CLAUDE_BARDO_LAUNCHER='myterm --new-window -e {cmd}'
```

<!-- end_slide -->

Safety and limits
===

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Safe by design**

- **No network**: no sockets, telemetry or update check.
- **Transcripts are read, never copied**: only the directory and the titles. Message content is never stored or logged.
- **Stores** one line per start and end: time, id, pid, directory, title, flags. Flag values can be sensitive.
- **Private**: state dir `0700`, files `0600`.
- A crash never re-arms a permission bypass.
- `uninstall --purge` erases it all.

<!-- column: 1 -->

**Honest limits**

- It leans on Claude Code internals that are **not a documented API**. `doctor` checks each one, and each degrades quietly.
- Flags are verified on Claude Code **2.1.301**: newer ones are dropped and named.
- **macOS first.** Linux works with `restore --tmux`.
- A **closed window looks like a crash**: it waits in the list until you `forget` or `prune` it.
- Interactive sessions only, not `claude -p` or SDK runs.

<!-- reset_layout -->

<!-- end_slide -->

Learn more
===

| where | what |
|---|---|
| `README.md` | everything here, plus the registry schema |
| `man claude-bardo` | the man page (installed from a clone) |
| `claude-bardo doctor` | is my setup sound, today? |
| `qa/` | real sessions, crashed four ways, then restored |
| `tests/` | 95 unit tests that touch nothing real |
| `presenterm docs/presentation.md` | this deck, in your terminal |

<!-- end_slide -->

<!-- jump_to_middle -->

Sessions you ended are released. The rest come back.
===

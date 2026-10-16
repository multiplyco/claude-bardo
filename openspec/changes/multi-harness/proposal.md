## Why

The reboot problem is not Claude-specific: anyone running a dozen agent sessions in OpenCode, Grok
Build or OpenAI's Codex CLI loses them the same way, and each of those CLIs can resume a session by
id. The mechanism claude-bardo proved (register on start, classify the end, replay the command) is
harness-agnostic; only the adapters differ.

## What Changes

- A **harness adapter** per CLI, answering five questions: how a session registers (hooks, or a
  fallback), how its death is classified, how liveness is checked, how it is resumed
  (`<cli> <flags> <resume-by-id>`), and which of its flags are safe to replay.
- Adapters to start with, each **to verify** before building (probe, like QA `TC-00`):
  - **Grok Build**: has hooks (`Stop`, `PreCompact`, `SessionEnd` in `~/.grok/hooks/*.json`) and
    session files under `~/.grok/sessions/…/updates.jsonl`. Needs: the resume command
    (`grok --resume <id>`, per its docs; untested).
    **Probed for free, 2026-10-13:** Grok (1.0.52) also runs every hook in `~/.claude/settings.json`
    by default (`[compat.claude] hooks`), so claude-bardo's own hook fired in Grok sessions: 15
    starts and 37 ends in the registry, 2026-09-19 to 2026-10-13. What that showed:
    - SessionStart exists (source `new` or `load`) but arrives with no `transcript_path`;
      SessionEnd carries one.
    - The envelope is Claude's snake_case keys plus camelCase ones (`hookEventName`, `sessionId`,
      `workspaceRoot`); `GROK_SESSION_ID` is in the hook's environment. Ids are UUIDv7.
    - Every Grok end read `shutdown`, with no reboot in the window: Grok's normal exit. SessionEnd
      can fire several times per id (8 for one); children carry `subagentType`.
    - The hook's ancestors include a `grok` process (the liveness and argv handle).
    claude-bardo now ignores the camelCase envelope; a Grok adapter turns that rule into
    `harness: grok` instead of installing a hook of its own.
  - **OpenAI Codex CLI**: sessions under `~/.codex/sessions/` (rollout JSONL), `codex resume <id>`.
    Needs: whether it has session start/end hooks at all, or only `notify`.
  - **OpenCode**: `opencode --session <id>` / `--continue`, a plugin API with session events.
    Needs: which events fire on start/end/crash, where sessions are stored.
- The registry gains a `harness` field (additive to schema `v: 1`; missing means `claude-code`).
- `list`, the picker and `restore` show and restore sessions of every installed harness together:
  one reboot, one picker.
- `install` wires each detected harness's hooks, with the same never-touch-others merge rule.

## Capabilities

### New Capabilities
- `harness-adapters`: the adapter contract (register, classify, liveness, resume, replay policy)
  and one adapter per supported CLI.

### Modified Capabilities
- None yet (no baseline specs exist; the Claude Code behaviour becomes the first adapter).

## Hypothesis and kill criteria

- **Hypothesis:** each target CLI offers (a) a start/end signal and (b) resume-by-id, so an
  adapter is under ~150 lines and needs no daemon.
- **Kill:** if two of the three need a polling daemon to see deaths (no end hook, no per-process
  session file), stop and reconsider: a daemon is exactly what this tool's design avoids.
- **Kill:** if a harness cannot resume a session by id in a new process, it is out of scope.

## Scope

- In: macOS first, the same terminals and the picker, one registry.
- Out: syncing sessions between machines; converting a session from one harness to another.

## Open questions

- **The name.** `claude-bardo` says Claude. Keep it as the brand and add harnesses quietly, or
  rename to `bardo` once a second harness lands (the binary could keep a `claude-bardo` alias)?
- Which harness first? Grok Build looks cheapest: it already fires our hook (see above).

## Impact

- `claude-bardo`: adapter layer around today's Claude-specific code (flag tables, hook parsing,
  `~/.claude` paths, liveness). Tests and the QA runner gain a per-harness dimension.
- Stays one file, standard library only, unless the adapters force a package (decide in design).

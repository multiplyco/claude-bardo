# Security

claude-bardo runs as a hook inside every Claude Code session and relaunches sessions, so a bug
here can matter. Please report vulnerabilities privately through GitHub's
[security advisories](https://github.com/multiplyco/claude-bardo/security/advisories/new), not in a
public issue.

What it is designed to guarantee:

- It makes no network connections.
- Nothing from the registry, a transcript, a directory name or a session title reaches a shell
  unquoted, an AppleScript unescaped, or a tmux format.
- Permission bypass is never replayed unless `restore --keep-bypass` is passed by hand.
- Its state is readable only by you (`0700` directory, `0600` files).
- It never writes to `~/.claude` except `settings.json` during `install`/`uninstall` (with a
  backup), and never touches a transcript.

A report that breaks one of these is exactly what we want to hear about.

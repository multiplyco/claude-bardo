"""How a new terminal window is opened, per terminal, and what can never reach a shell."""
import sys
import unittest

from helpers import Sandbox, load, uuid

INNER = ["/home/u/.local/bin/claude-bardo", "_launch", uuid(1)]


@unittest.skipUnless(sys.platform == "darwin", "window mode is macOS-only")
class TestLaunchers(Sandbox):
    def test_ghostty(self):
        cmd, why = self.m.launcher_cmd(INNER, "ghostty")
        self.assertIsNone(why)
        self.assertEqual(cmd[:4], [self.m.OPEN, "-na", "Ghostty", "--args"])
        self.assertIn("--window-save-state=never", cmd)
        self.assertEqual(cmd[-4:], ["-e"] + INNER)

    def test_iterm_passes_the_command_as_an_argument(self):
        cmd, why = self.m.launcher_cmd(INNER, "iTerm2")
        self.assertIsNone(why)
        self.assertEqual(cmd[0], self.m.OSASCRIPT)
        self.assertEqual(cmd[-1], " ".join(INNER))
        script = " ".join(cmd[1:-1])
        self.assertNotIn(uuid(1), script)             # never spliced into the AppleScript text
        cmd, why = self.m.launcher_cmd(["/Users/a b/claude-bardo", "_launch", uuid(1)], "iterm")
        self.assertIsNone(cmd)
        self.assertIn("without spaces", why)

    def test_terminal_app_quotes_for_the_shell(self):
        cmd, _ = self.m.launcher_cmd(["/Users/a b/claude-bardo", "_launch", uuid(1)], "Terminal.app")
        self.assertEqual(cmd[-1], "exec '/Users/a b/claude-bardo' _launch " + uuid(1))

    def test_other_terminals(self):
        self.assertEqual(self.m.launcher_cmd(INNER, "wezterm")[0][-5:], ["start", "--"] + INNER)
        self.assertEqual(self.m.launcher_cmd(INNER, "alacritty")[0][-4:], ["-e"] + INNER)
        self.assertEqual(self.m.launcher_cmd(INNER, "kitty")[0][-3:], INNER)
        cmd, why = self.m.launcher_cmd(INNER, "hyper")
        self.assertIsNone(cmd)
        self.assertIn("unknown terminal", why)

    def test_custom_launcher_template(self):
        m = load(dict(self.env, CLAUDE_BARDO_LAUNCHER="myterm --new-window --run {cmd} --stay"))
        cmd, why = m.launcher_cmd(INNER)
        self.assertEqual(cmd, ["myterm", "--new-window", "--run"] + INNER + ["--stay"])
        m = load(dict(self.env, CLAUDE_BARDO_LAUNCHER="myterm --run"))
        self.assertIn("{cmd}", m.launcher_cmd(INNER)[1])

    def test_only_ghostty_reaps(self):
        self.assertTrue(self.m.reaps("ghostty"))
        self.assertFalse(self.m.reaps("iterm"))


class TestNames(Sandbox):
    def test_terminal_key(self):
        for name, key in (("Ghostty", "ghostty"), ("/Applications/Ghostty.app", "ghostty"), ("iTerm.app", "iterm"),
                          ("iTerm2", "iterm"), ("Apple_Terminal", "terminal"), ("WezTerm", "wezterm")):
            self.assertEqual(self.m.terminal_key(name), key)

    def test_tmux_names_cannot_run_formats(self):
        self.assertEqual(self.m.tmux_name("#(curl x|sh) #{pane}"), "##(curl x|sh) ##{pane}")
        self.assertEqual(self.m.tmux_name("\x1b[31m"), "[31m")
        self.assertEqual(self.m.tmux_name(""), "session")


if __name__ == "__main__":
    unittest.main()

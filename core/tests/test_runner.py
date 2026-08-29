import os
import re
import unittest

from stdedit import runner
from stdedit import icons


def make_which(available):
    """Build a fake shutil.which that only knows *available* tools."""
    def _which(name):
        return f"/usr/bin/{name}" if name in available else None
    return _which


CAPTURE = []


def fake_popen(argv, *args, **kwargs):
    CAPTURE.append((argv, args, kwargs))


class RunCommandForTests(unittest.TestCase):
    def cmd_for(self, path, available):
        cmd, reason = runner.run_command_for(
            path, _which=make_which(set(available)))
        self.assertIsNotNone(cmd, reason)
        return cmd

    def test_python_uses_python3(self):
        cmd = self.cmd_for("proj/hello.py", {"python3"})
        self.assertTrue(cmd.startswith("python3 "), cmd)
        self.assertIn("hello.py", cmd)

    def test_paths_with_spaces_are_shell_quoted(self):
        cmd = self.cmd_for("my proj/hello world.py", {"python3"})
        self.assertRegex(cmd, r"'/.*my proj/hello world\.py'")

    def test_javascript_uses_node(self):
        self.assertIn("node", self.cmd_for("app/index.js", {"node"}))
        self.assertIn("node", self.cmd_for("mod.mjs", {"node"}))

    def test_typescript_uses_tsx_via_npx(self):
        cmd = self.cmd_for("src/main.ts", {"npx"})
        self.assertIn("npx --yes tsx", cmd)
        self.assertIn("tsx", self.cmd_for("page.jsx", {"npx"}))

    def test_java_uses_single_file_launcher(self):
        cmd = self.cmd_for("Main.java", {"java"})
        self.assertIn("java", cmd)
        self.assertNotIn("javac", cmd)

    def test_c_uses_gcc_and_temp_output(self):
        cmd = self.cmd_for("prog.c", {"gcc"})
        self.assertIn("gcc", cmd)
        self.assertRegex(cmd, r"-o /tmp/stdedit-run-\d+")

    def test_cpp_variants_use_gplusplus(self):
        for ext in ("cpp", "cc", "cxx", "C"):
            self.assertIn("g++", self.cmd_for(f"prog.{ext}", {"g++"}))

    def test_rust_uses_rustc(self):
        self.assertIn("rustc", self.cmd_for("lib.rs", {"rustc"}))

    def test_go_uses_go_run(self):
        self.assertIn("go run", self.cmd_for("pkg/main.go", {"go"}))

    def test_shell_script_prefers_bash(self):
        cmd = self.cmd_for("deploy.sh", {"bash", "sh"})
        self.assertIn("bash", cmd)
        self.assertTrue(cmd.startswith("bash "), cmd)

    def test_shell_falls_back_to_sh(self):
        cmd = self.cmd_for("deploy.sh", {"sh"})
        self.assertIn("sh ", cmd)
        self.assertFalse(cmd.startswith("bash "), cmd)

    def test_shell_with_no_interpreter_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "deploy.sh", _which=make_which(set()))
        self.assertIsNone(cmd)
        self.assertIn("not found", reason)

    def test_perl_ruby_php_lua_r(self):
        self.assertIn("perl", self.cmd_for("script.pl", {"perl"}))
        self.assertIn("ruby", self.cmd_for("app.rb", {"ruby"}))
        self.assertIn("php", self.cmd_for("page.php", {"php"}))
        self.assertIn("lua", self.cmd_for("mod.lua", {"lua"}))
        self.assertIn("Rscript", self.cmd_for("analysis.R", {"Rscript"}))
        self.assertIn("Rscript", self.cmd_for("analysis.r", {"Rscript"}))

    def test_missing_runtime_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "hello.py", _which=make_which({"node"}))
        self.assertIsNone(cmd)
        self.assertIn("python3", reason)
        self.assertIn("not found", reason)

    def test_unknown_extension_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "archive.zip", _which=make_which({"python3"}))
        self.assertIsNone(cmd)
        self.assertIn("No runner", reason)

    def test_extensionless_file_reports_reason(self):
        cmd, reason = runner.run_command_for(
            "README", _which=make_which({"python3"}))
        self.assertIsNone(cmd)
        self.assertIn("No runner", reason)

    def test_non_runnable_types(self):
        for fname in ("doc.md", "page.html", "style.css", "data.json",
                      "config.yaml", "query.sql", "graph.xml", "notes.txt"):
            cmd, reason = runner.run_command_for(
                fname, _which=make_which({"python3"}))
            self.assertIsNone(cmd, fname)
            self.assertIn("No run command", reason, fname)


class TerminalLauncherTests(unittest.TestCase):
    def test_prefers_kitty_when_present(self):
        argv = runner.terminal_launcher(
            _which=make_which({"kitty", "xterm"}), env={})
        self.assertEqual(argv[:2], ["kitty", "-e"])

    def test_falls_back_to_xterm(self):
        argv = runner.terminal_launcher(
            _which=make_which({"xterm"}), env={})
        self.assertEqual(argv[:2], ["xterm", "-e"])

    def test_generic_default_as_last_resort(self):
        argv = runner.terminal_launcher(
            _which=make_which({"x-terminal-emulator"}), env={})
        self.assertEqual(argv[:2], ["x-terminal-emulator", "-e"])

    def test_none_when_no_terminal(self):
        self.assertIsNone(runner.terminal_launcher(
            _which=make_which({"python3"}), env={}))

    def test_env_override_wins(self):
        argv = runner.terminal_launcher(
            _which=make_which({"cat", "kitty"}),
            env={"STDEDIT_TERMINAL": "cat"})
        self.assertEqual(argv, ["cat"])

    def test_env_override_missing_binary(self):
        self.assertIsNone(runner.terminal_launcher(
            _which=make_which({"kitty"}),
            env={"STDEDIT_TERMINAL": "ghost"}))


class RunFileTests(unittest.TestCase):
    def setUp(self):
        CAPTURE.clear()

    def test_run_python_in_kitty(self):
        ok, status = runner.run_file(
            "proj/hello.py",
            _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={})
        self.assertTrue(ok, status)
        self.assertRegex(status, r"Running: python3 .*hello\.py .*kitty")
        self.assertEqual(1, len(CAPTURE))
        argv, _, kwargs = CAPTURE[0]
        self.assertTrue(argv[0].endswith("kitty"))
        self.assertEqual(argv[1:3], ["-e", "bash"])
        script = argv[-1]
        self.assertIn('cd "$(dirname --', script)
        self.assertRegExpIn(script, r"hello\.py")
        self.assertIn("python3", script)
        self.assertIn("[Enter] close", script)
        self.assertIn("[r] rerun", script)
        self.assertNotIn("[e] edit", script)
        self.assertIn("exit: $rc", script)
        self.assertIn("read -n 1 -s -r", script)
        self.assertIn("PIPESTATUS[0]", script)
        self.assertIn("2>&1 | sed 's/^/  /'", script)
        self.assertTrue(kwargs.get("start_new_session"))

    def test_no_terminal_reports_reason(self):
        ok, status = runner.run_file(
            "a.py", _which=make_which({"python3"}), _popen=fake_popen)
        self.assertFalse(ok)
        self.assertIn("No terminal emulator", status)
        self.assertEqual([], CAPTURE)

    def test_compile_script_cleans_up_temp_binary(self):
        runner.run_file(
            "main.c", _which=make_which({"gcc", "kitty"}),
            _popen=fake_popen, env={})
        argv, _, _ = CAPTURE[0]
        command = argv[-1]
        outs = set(re.findall(r"/tmp/stdedit-run-\d+", command))
        self.assertEqual(1, len(outs), outs)
        out = outs.pop()
        self.assertIn(f"-o {out}", command)
        self.assertIn(f"rm -f {out}", command)

    def test_missing_runtime_cascades_to_status(self):
        ok, status = runner.run_file(
            "Main.java", _which=make_which({"kitty"}), _popen=fake_popen)
        self.assertFalse(ok)
        self.assertIn("Runtime 'java' not found", status)

    def test_empty_path_is_safe(self):
        ok, status = runner.run_file("", _which=make_which({"kitty"}),
                                     _popen=fake_popen)
        self.assertFalse(ok)

    def test_popen_error_reports_friendly_status(self):
        def boom(_argv, *a, **k):
            raise OSError("no DISPLAY")
        ok, status = runner.run_file(
            "a.py", _which=make_which({"python3", "kitty"}), _popen=boom)
        self.assertFalse(ok)
        self.assertIn("Could not launch terminal", status)
        self.assertIn("no DISPLAY", status)

    def assertRegExpIn(self, text, pattern):
        self.assertIsNotNone(re.search(pattern, text), (pattern, text))


class RunCurrentFileTests(unittest.TestCase):
    """tui._run_current_file: auto-save-then-run wiring."""

    def setUp(self):
        from stdedit import tui
        self.tui = tui
        self.orig_run_file = tui.runner.run_file
        self.runs = []
        self.saves = []
        tui.runner.run_file = self._fake_run

    def tearDown(self):
        self.tui.runner.run_file = self.orig_run_file

    def _fake_run(self, path):
        self.runs.append(path)
        return True, f"Running: {path}"

    def make_buf(self, filename, modified):
        class FakeBuf:
            pass
        buf = FakeBuf()
        buf.filename = filename
        buf.modified = modified
        def save(path=None):
            self.saves.append(path)
            buf.modified = False
        buf.save = save
        return buf

    def test_no_filename_reports_reason(self):
        status = self.tui._run_current_file(self.make_buf(None, False))
        self.assertIn("Nothing to run", status)
        self.assertEqual([], self.runs)
        self.assertEqual([], self.saves)

    def test_autosaves_then_runs_when_modified(self):
        status = self.tui._run_current_file(
            self.make_buf("/tmp/a.py", True))
        self.assertEqual(["/tmp/a.py"], self.runs)
        self.assertEqual([None], self.saves)
        self.assertTrue(status.startswith("Running:"))

    def test_runs_without_saving_when_clean(self):
        status = self.tui._run_current_file(
            self.make_buf("/tmp/a.py", False))
        self.assertEqual(["/tmp/a.py"], self.runs)
        self.assertEqual([], self.saves)
        self.assertTrue(status.startswith("Running:"))

    def test_save_error_blocks_run(self):
        buf = self.make_buf("/tmp/b.py", True)
        def save(path=None):
            raise OSError("disk full")
        buf.save = save
        status = self.tui._run_current_file(buf)
        self.assertIn("Could not save before running", status)
        self.assertIn("disk full", status)
        self.assertEqual([], self.runs)


class DecorationTests(unittest.TestCase):
    """The spawned terminal is framed by a boxed banner + colored footer."""

    def setUp(self):
        CAPTURE.clear()

    def test_frame_geometry_all_lines_exact_width(self):
        lines = runner._frame_lines(
            "/tmp/a.py", "Python 3", "", "python3 /tmp/a.py", width=70)
        for line in lines:
            self.assertEqual(70, len(line), repr(line))
        self.assertTrue(lines[0].startswith("┌"))
        self.assertTrue(lines[-1].startswith("├"))

    def test_frame_header_labels_file_and_command(self):
        lines = runner._frame_lines(
            "/tmp/run/sample.py", "Python 3", "", "python3 /tmp/run/sample.py",
            width=70)
        self.assertIn("▶", lines[1])
        self.assertIn("YUKI", lines[1])
        self.assertIn("Python 3", lines[1])
        self.assertIn("sample.py", lines[1])
        self.assertIn("file: /tmp/run/sample.py", lines[2])
        self.assertIn("cmd: python3 /tmp/run/sample.py", lines[3])

    def test_frame_keeps_geometry_with_icon(self):
        lines = runner._frame_lines(
            "/tmp/a.py", "Python 3", "🐍", "python3 /tmp/a.py", width=70)
        self.assertIn("🐍", lines[1])

    def test_long_path_wraps_to_indented_continuation_rows(self):
        long = "/tmp/" + "y" * 200 + "/sample.py"
        lines = runner._frame_lines(
            long, "Python 3", "", f"python3 {long}", width=70)
        for line in lines:
            self.assertLessEqual(len(line), 70, repr(line))
        joined = "\n".join(lines[1:5])
        self.assertNotIn("…", joined)
        self.assertIn("│   /tmp/", joined)

    def test_title_osc_carries_basename_and_runtime(self):
        s = runner._build_script(
            "/tmp/my.py", "python3 /tmp/my.py", runtime="python3", icon="")
        self.assertIn("\\033]0;%s\\007", s)
        self.assertIn("YUKI — run my.py (Python 3)", s)
        self.assertTrue(s.startswith("printf "), s)

    def test_tricky_filenames_are_escaped_in_emitted_lines(self):
        s = runner._build_script(
            "/tmp/odd 'name' (x).py", "python3 /tmp/odd 'name' (x).py",
            runtime="python3", icon="")
        self.assertIn("'\\''", s)
        self.assertNotIn("syntax error", s)

    def test_colors_active_by_default(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="")
        self.assertIn("\\x1b[32m", s)
        self.assertIn("\\x1b[31m", s)
        self.assertIn("\\x1b[0m", s)

    def test_no_color_keeps_frame_drops_sgr(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="",
            colors=False)
        self.assertIn("┌", s)
        self.assertIn("YUKI — run", s)
        self.assertNotIn("\\x1b[", s)

    def test_raw_script_matches_plain_template(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="",
            raw=True)
        for forbidden in ("┌", "▶", "\\033]0;", "\\x1b["):
            self.assertNotIn(forbidden, s)
        self.assertIn('cd "$(dirname --', s)
        self.assertIn('echo "[YUKI] finished (exit $rc) — press Enter to close"', s)
        self.assertIn("read -r _", s)

    def test_run_file_respects_raw_env(self):
        ok, _status = runner.run_file(
            "proj/a.py", _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={"STDEDIT_RUN_RAW": "1"})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertNotIn("┌", script)
        self.assertNotIn("▶", script)

    def test_run_file_respects_no_color_env(self):
        ok, _status = runner.run_file(
            "proj/a.py", _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={"NO_COLOR": "1"})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertNotIn("\\x1b[", script)
        self.assertIn("┌", script)

    def test_run_file_omits_icon_when_disabled(self):
        glyph = icons.icon_for_file("proj/a.py", True)
        self.assertTrue(glyph)
        ok, _status = runner.run_file(
            "proj/a.py", _which=make_which({"python3", "kitty"}),
            _popen=fake_popen, env={"STDEDIT_ICONS": "0"})
        self.assertTrue(ok)
        script = CAPTURE[0][0][-1]
        self.assertNotIn(glyph, script)

    def test_built_script_indents_program_output(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="")
        self.assertIn("2>&1 | sed 's/^/  /'", s)
        self.assertIn("rc=${PIPESTATUS[0]}", s)
        self.assertIn("{ python3 /tmp/a.py; }", s)

    def test_built_script_bottom_bar_and_keys(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="")
        self.assertIn('bar=" exit: $rc  │  [r] rerun  [Enter] close "', s)
        self.assertIn("r|R) continue", s)
        self.assertNotIn("e|E)", s)
        self.assertNotIn("command -v stdedit", s)
        self.assertNotIn("[e] edit", s)
        self.assertIn("read -n 1 -s -r k", s)
        self.assertIn("run_once", s)

    def test_bottom_bar_honors_no_color(self):
        s = runner._build_script(
            "/tmp/a.py", "python3 /tmp/a.py", runtime="python3", icon="",
            colors=False)
        self.assertIn(" exit: $rc ", s)
        self.assertIn("[r] rerun", s)
        self.assertIn("[Enter] close", s)
        self.assertNotIn("\\x1b[7m", s)

    def test_compile_script_wraps_cmd_line_without_cutting_path(self):
        s = runner._build_script(
            "/tmp/long/dir/name/prog.c",
            "gcc /tmp/long/dir/name/prog.c -o /tmp/stdedit-run-4242 "
            "&& /tmp/stdedit-run-4242", runtime="gcc", icon="")
        self.assertIn("│   /tmp/stdedit-run-4242", s)
        self.assertNotIn("stdedit-run-42…", s)


if __name__ == "__main__":
    unittest.main()
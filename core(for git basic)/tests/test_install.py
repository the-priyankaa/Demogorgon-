import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from stdedit import install
from stdedit.install import (
    LAUNCHER_NAMES,
    build_parser,
    cmd_uninstall,
    is_owned_link,
    main,
    place_links,
    plan_links,
    project_root_from,
    python_version_error,
    remove_links,
)


class FakeRun:
    """Records subprocess calls with optional side effects and rc policy."""

    def __init__(self, returncode=0, side_effect=None, rc_for=None):
        self.calls = []
        self.returncode = returncode
        self.side_effect = side_effect
        self.rc_for = rc_for

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append(cmd)
        if self.side_effect:
            self.side_effect(cmd)
        rc = self.rc_for(cmd) if self.rc_for else self.returncode
        return SimpleNamespace(returncode=rc)

    def saw(self, *fragments):
        return any(all(f in c for f in fragments) for c in self.calls)


def is_probe(cmd):
    """True for launcher self-check invocations."""
    return bool(cmd) and cmd[-1] in ("--list-extensions", "status")


class InstallTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name
        self.root = os.path.join(self.base, "proj")
        self.bin_dir = os.path.join(self.base, "bin")
        os.makedirs(os.path.join(self.root, "src", "stdedit"))
        open(os.path.join(self.root, "src", "stdedit", "__init__.py"),
             "w").close()

    def venv_bin(self):
        return os.path.join(self.root, ".venv", "bin")

    def make_launcher(self, name):
        path = os.path.join(self.venv_bin(), name)
        os.makedirs(self.venv_bin(), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def make_all_launchers(self):
        for name in LAUNCHER_NAMES:
            self.make_launcher(name)

    def fabricate_venv_step(self, cmd):
        """Side effect standing in for real 'python -m venv' execution."""
        if "venv" in cmd:
            self.make_all_launchers()


class TestPathsAndPlans(InstallTestBase):
    def test_project_root_from_walks_three_levels_up(self):
        module_file = os.path.join(self.root, "src", "stdedit", "install.py")
        self.assertEqual(project_root_from(module_file), self.root)

    def test_plan_links_includes_only_existing_launchers(self):
        self.make_launcher("stdedit")
        links = plan_links(self.root, self.bin_dir)
        self.assertEqual(links, [(
            os.path.join(self.bin_dir, "stdedit"),
            os.path.join(self.venv_bin(), "stdedit"),
        )])

    def test_python_version_ok_on_current_interpreter(self):
        self.assertIsNone(python_version_error())


class TestPlaceLinks(InstallTestBase):
    def test_creates_symlinks_and_reports_each(self):
        self.make_all_launchers()
        notes = place_links(self.root, self.bin_dir)
        self.assertEqual(len(notes), len(LAUNCHER_NAMES))
        for name in LAUNCHER_NAMES:
            link_path = os.path.join(self.bin_dir, name)
            self.assertTrue(os.path.islink(link_path), name)
            self.assertEqual(os.readlink(link_path),
                             os.path.join(self.venv_bin(), name))

    def test_rerun_refreshes_instead_of_failing(self):
        self.make_all_launchers()
        place_links(self.root, self.bin_dir)
        notes = place_links(self.root, self.bin_dir)
        self.assertTrue(all(n.startswith("refreshed") for n in notes))
        for name in LAUNCHER_NAMES:
            self.assertTrue(os.path.islink(os.path.join(self.bin_dir, name)))

    def test_regular_file_collision_is_skipped_not_clobbered(self):
        self.make_all_launchers()
        os.makedirs(self.bin_dir, exist_ok=True)
        foreign = os.path.join(self.bin_dir, "stdedit")
        with open(foreign, "w") as fh:
            fh.write("not a symlink")
        place_links(self.root, self.bin_dir)
        with open(foreign) as fh:
            self.assertEqual(fh.read(), "not a symlink")


class TestOwnershipGuard(InstallTestBase):
    def test_owned_link_detected(self):
        link_path = os.path.join(self.bin_dir, "yuki")
        self.make_launcher("yuki")
        place_links(self.root, self.bin_dir)
        self.assertTrue(is_owned_link(
            link_path, os.path.realpath(install.get_venv_bin(self.root))))

    def test_remove_links_deletes_only_owned_symlinks(self):
        owned = os.path.join(self.bin_dir, "stdedit")
        self.make_all_launchers()
        place_links(self.root, self.bin_dir)

        # Replace the yuki link with a foreign-targeted symlink and the
        # carl link with a regular file.
        foreign_target = os.path.join(self.base, "elsewhere", "stdedit")
        os.makedirs(os.path.dirname(foreign_target), exist_ok=True)
        open(foreign_target, "w").close()
        foreign = os.path.join(self.bin_dir, "yuki")
        regular = os.path.join(self.bin_dir, "carl")
        for link_path in (foreign, regular):
            os.remove(link_path)
        os.symlink(foreign_target, foreign)
        open(regular, "w").close()

        removed, kept = remove_links(self.root, self.bin_dir)

        self.assertEqual(removed, [owned])
        self.assertFalse(os.path.lexists(owned))
        self.assertTrue(os.path.islink(foreign))
        self.assertTrue(os.path.exists(regular))
        self.assertEqual(len([k for k in kept if "yuki" in k]), 1)
        self.assertEqual(len([k for k in kept if "carl" in k]), 1)

    def test_uninstall_with_purge_removes_venv_too(self):
        self.make_all_launchers()
        place_links(self.root, self.bin_dir)
        args = SimpleNamespace(command="uninstall", purge=True)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_uninstall(args, self.root, self.bin_dir)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".venv")))
        for name in LAUNCHER_NAMES:
            self.assertFalse(os.path.lexists(os.path.join(self.bin_dir, name)))


class TestInstallFlow(InstallTestBase):
    def install_hermetically(self, run):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["install"], _root=self.root, _bin_dir=self.bin_dir,
                      _run=run)
        return rc, run, out.getvalue()

    def test_end_to_end_install_creates_links_and_runs_pip_editable(self):
        self.assertFalse(os.path.isdir(self.venv_bin()))
        run = FakeRun(side_effect=self.fabricate_venv_step)
        rc, run, output = self.install_hermetically(run)
        self.assertEqual(rc, 0, output)
        self.assertTrue(run.saw(sys.executable, "-m", "venv"))
        self.assertTrue(run.saw("-m", "pip", "install", "-e", self.root))
        for name in LAUNCHER_NAMES:
            link_path = os.path.join(self.bin_dir, name)
            self.assertTrue(os.path.islink(link_path), name)
        self.assertIn("done.", output)
        probes = [c for c in run.calls if is_probe(c)]
        self.assertEqual(len(probes), len(LAUNCHER_NAMES))

    def test_bare_invocation_defaults_to_install(self):
        self.assertIsNone(build_parser().parse_args([]).command)
        run = FakeRun(side_effect=self.fabricate_venv_step)
        rc, run, _ = self.install_hermetically(run)
        self.assertEqual(rc, 0)
        self.assertTrue(run.saw("-m", "pip"))

    def test_missing_python_aborts_before_anything_else(self):
        run = FakeRun()
        original = install.MIN_PYTHON
        install.MIN_PYTHON = (99, 0)
        try:
            rc, _, output = self.install_hermetically(run)
        finally:
            install.MIN_PYTHON = original
        self.assertEqual(rc, 1)
        self.assertIn("Python 99.0+ required", output)
        self.assertEqual(run.calls, [])

    def test_failing_pip_aborts_before_linking(self):
        run = FakeRun(side_effect=self.fabricate_venv_step,
                      rc_for=lambda cmd: 1 if "pip" in cmd else 0)
        rc, _, output = self.install_hermetically(run)
        self.assertEqual(rc, 1)
        self.assertIn("pip install failed", output)
        listing = os.listdir(self.bin_dir) if os.path.isdir(self.bin_dir) else []
        self.assertEqual(listing, [])

    def test_failed_self_check_is_reported(self):
        self.make_all_launchers()  # venv pre-exists; only probes will fail
        run = FakeRun(rc_for=lambda cmd: 1 if is_probe(cmd) else 0)
        rc, _, output = self.install_hermetically(run)
        self.assertEqual(rc, 1)
        self.assertIn("self-check", output)
        # Links were still placed; the failure is reported, not silent.
        self.assertTrue(os.path.islink(os.path.join(self.bin_dir, "stdedit")))


class TestStatus(InstallTestBase):
    def test_status_reports_mixed_state_without_crashing(self):
        self.make_launcher("stdedit")
        place_links(self.root, self.bin_dir)
        out = io.StringIO()
        with redirect_stdout(out):
            rc = main(["status"], _root=self.root, _bin_dir=self.bin_dir)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("python :", text)
        self.assertIn("missing", text)      # yuki/carl not built
        self.assertIn("linked ->", text)    # stdedit linked


if __name__ == "__main__":
    unittest.main()

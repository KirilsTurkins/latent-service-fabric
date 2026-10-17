"""Windows dispatch contracts plus real cmd/PowerShell launcher execution on Windows."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from tools import intellij, intellij_windows as windows


class WindowsTaskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="lsf IDE ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "website").mkdir()
        (self.root / "website/package.json").write_text(json.dumps({
            "engines": {"node": "1.2.3"},
            "scripts": {name: "fixture" for name in windows.WEBSITE_SCRIPTS.values()},
        }), encoding="utf-8")

    def prepared(self):
        path = self.root / "website/toolchain/node_modules/npm/bin/npm-cli.js"
        path.parent.mkdir(parents=True)
        path.write_text("// fixture", encoding="utf-8")
        return path

    def test_help_has_no_subprocess_or_tool_discovery(self):
        with mock.patch.object(windows.subprocess, "run") as run, mock.patch.object(windows.shutil, "which") as which:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, windows.run(self.root, "help"))
            self.assertIn("website-prepare", output.getvalue())
            self.assertIn("no Bash, Make or WSL", output.getvalue())
            run.assert_not_called()
            which.assert_not_called()

    def test_linux_tasks_fail_before_creating_state_or_starting_processes(self):
        with mock.patch.object(windows.subprocess, "run") as run:
            for task in ("check", "contracts", "validate", "repository-tests", "unknown"):
                with self.subTest(task=task), self.assertRaisesRegex(ValueError, "never starts WSL"):
                    windows.run(self.root, task)
            run.assert_not_called()
        self.assertFalse((self.root / "target").exists())

    def test_prepare_reuses_verified_owners_and_only_locked_installs(self):
        bootstrap = self.root / "Node with spaces/npm-cli.js"
        with mock.patch.object(windows, "bootstrap_cli", return_value=bootstrap):
            commands = windows.website_commands(self.root, "website-prepare", "Node with spaces/node.exe")
        self.assertEqual([sys.executable, "website/toolchain/prepare.py"], commands[0])
        self.assertEqual(["Node with spaces/node.exe", str(bootstrap), "ci", "--prefix", "website/toolchain",
                          "--ignore-scripts", "--no-audit", "--no-fund"], commands[1])
        self.assertEqual(["Node with spaces/node.exe", "website/scripts/check-package-manager.mjs"], commands[2])
        self.assertEqual(["Node with spaces/node.exe", "website/toolchain/node_modules/npm/bin/npm-cli.js",
                          "--prefix", "website", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], commands[3])

    def test_preparation_stops_at_each_failed_stage_and_keeps_exit_status(self):
        for failed in range(4):
            replies = [subprocess.CompletedProcess([], 0, "v1.2.3\n")]
            replies.extend(subprocess.CompletedProcess([], 7 if index == failed else 0) for index in range(4))
            with mock.patch.object(windows, "executable", return_value="node.exe"), \
                    mock.patch.object(windows, "bootstrap_cli", return_value=Path("npm-cli.js")), \
                    mock.patch.object(windows.subprocess, "run", side_effect=replies) as run:
                self.assertEqual(7, windows.run(self.root, "website-prepare"))
                self.assertEqual(failed + 2, run.call_count)
                for call in run.call_args_list:
                    self.assertNotIn("shell", call.kwargs)
                    self.assertEqual(self.root, call.kwargs["cwd"])
                    self.assertFalse(call.kwargs["check"])

    def test_wrong_node_fails_before_preparation(self):
        with mock.patch.object(windows, "executable", return_value="node.exe"), \
                mock.patch.object(windows.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "v9.9.9\n")) as run:
            with self.assertRaisesRegex(ValueError, "Node version"):
                windows.run(self.root, "website-prepare")
            self.assertEqual(1, run.call_count)
            self.assertEqual(30, run.call_args.kwargs["timeout"])

    def test_website_tasks_never_bootstrap_or_install_implicitly(self):
        self.prepared()
        with mock.patch.object(windows, "bootstrap_cli") as bootstrap:
            for task in windows.WEBSITE_SCRIPTS:
                commands = windows.website_commands(self.root, task, "node.exe")
                self.assertEqual("website/scripts/check-package-manager.mjs", commands[0][1])
                self.assertEqual(["run", windows.WEBSITE_SCRIPTS[task]], commands[1][-2:])
                self.assertNotIn("ci", commands[1])
            bootstrap.assert_not_called()

    def test_missing_preparation_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "website-prepare first"):
            windows.website_commands(self.root, "website-start", "node.exe")

    def test_full_website_validation_preserves_make_order(self):
        self.prepared()
        commands = windows.website_commands(self.root, "website-validate", "node.exe")
        self.assertEqual(["check", "test", "build", "build:root", "test:build"], [item[-1] for item in commands[1:]])

    def test_prepared_package_manager_precedes_global_path(self):
        self.prepared()
        replies = [subprocess.CompletedProcess([], 0, "v1.2.3\n"), subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0)]
        with mock.patch.object(windows, "executable", return_value="node.exe"), \
                mock.patch.dict(os.environ, {"PATH": "ambient"}), \
                mock.patch.object(windows.subprocess, "run", side_effect=replies) as run:
            self.assertEqual(0, windows.run(self.root, "website-start"))
            self.assertEqual(str(self.root / "website/toolchain/node_modules/.bin") + os.pathsep + "ambient",
                             run.call_args.kwargs["env"]["PATH"])
            self.assertEqual("ambient", os.environ["PATH"])

    def test_bootstrap_discovery_supports_program_files_and_explicit_override(self):
        node = self.root / "Program Files/nodejs/node.exe"
        npm = node.parent / "node_modules/npm/bin/npm-cli.js"
        npm.parent.mkdir(parents=True)
        npm.write_text("// fixture", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LSF_IDE_BOOTSTRAP_NPM_CLI": ""}), mock.patch.object(windows.shutil, "which", return_value=None):
            self.assertEqual(npm.resolve(), windows.bootstrap_cli(str(node)))
        with mock.patch.dict(os.environ, {"LSF_IDE_BOOTSTRAP_NPM_CLI": str(npm)}):
            self.assertEqual(npm.resolve(), windows.bootstrap_cli("other-node.exe"))
        with mock.patch.dict(os.environ, {"LSF_IDE_BOOTSTRAP_NPM_CLI": str(self.root / "missing/npm-cli.js")}):
            with self.assertRaisesRegex(ValueError, "must name an existing"):
                windows.bootstrap_cli(str(node))

    def test_windows_dispatch_does_not_reach_make(self):
        with mock.patch.object(intellij.sys, "platform", "win32"), \
                mock.patch.object(intellij, "task_command") as make, \
                mock.patch.object(windows, "run", return_value=8) as run:
            self.assertEqual(8, intellij.main(["run", "website-prepare"]))
            run.assert_called_once_with(intellij.ROOT, "website-prepare")
            make.assert_not_called()

    def test_generated_windows_configs_use_cmd_and_have_distinct_names(self):
        (self.root / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
        files = intellij.project_files(self.root, ["Cargo.toml"])
        configs = {path: ET.fromstring(text).find("configuration") for path, text in files.items() if path.startswith(".run/")}
        self.assertEqual(len(configs), len({node.attrib["name"] for node in configs.values()}))
        for task in windows.TASKS:
            config = configs[f".run/LSF-{task}-windows.run.xml"]
            options = {item.attrib["name"]: item.attrib["value"] for item in config.findall("option")}
            self.assertEqual(f"cmd.exe /d /c tools\\intellij.cmd {task}", options["SCRIPT_TEXT"])
            self.assertEqual("$PROJECT_DIR$", options["SCRIPT_WORKING_DIRECTORY"])
            self.assertTrue(config.attrib["name"].endswith("(Windows)"))
            self.assertTrue(config.attrib["folderName"].startswith("LSF / Windows /"))
        self.assertNotIn(".run/LSF-validate-windows.run.xml", configs)
        self.assertNotIn(".run/LSF-ide-node-prepare-windows.run.xml", configs)
        self.assertTrue(configs[".run/LSF-help.run.xml"].attrib["name"].endswith("(Bash)"))


@unittest.skipUnless(sys.platform == "win32", "real cmd.exe/PowerShell execution is qualified by the Windows CI matrix entry")
class NativeWindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="LSF launcher ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "checkout with spaces"
        (self.root / "tools").mkdir(parents=True)
        for name in ("intellij.py", "intellij_windows.py", "intellij.cmd"):
            shutil.copyfile(intellij.ROOT / "tools" / name, self.root / "tools" / name)
        (self.root / "tools/validate_docs.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
        self.environment = os.environ.copy()
        self.environment["LSF_IDE_PYTHON"] = sys.executable
        # No Git Bash, Make, py launcher or ambient Python. A WSL stub can be in
        # System32, but these commands must not attempt to start it.
        self.environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        self.cmd = str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe")

    def command(self, task):
        return subprocess.run([self.cmd, "/d", "/c", "tools\\intellij.cmd", task],
                              cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=30)

    def test_real_cmd_help_with_no_bash_make_or_path_python(self):
        result = self.command("help")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("LSF native Windows", result.stdout)
        self.assertNotIn("WSL (", result.stderr)

    def test_real_cmd_propagates_child_failure(self):
        self.assertEqual(7, self.command("docs").returncode)

    def test_invalid_explicit_python_never_falls_back(self):
        self.environment["LSF_IDE_PYTHON"] = str(self.root / "missing/python.exe")
        result = self.command("help")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("LSF native Windows", result.stdout)

    def test_real_powershell_executes_exact_generated_command(self):
        config = ET.fromstring(intellij.run_configuration("help", "Start", windows=True)).find("configuration")
        text = next(item.attrib["value"] for item in config.findall("option") if item.attrib["name"] == "SCRIPT_TEXT")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", text + "; exit $LASTEXITCODE"],
                                cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("LSF native Windows", result.stdout)

    def test_real_venv_selection_without_path_python(self):
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.root / ".venv")], check=True, timeout=60)
        self.environment.pop("LSF_IDE_PYTHON", None)
        result = self.command("help")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("LSF native Windows", result.stdout)


if __name__ == "__main__":
    unittest.main()

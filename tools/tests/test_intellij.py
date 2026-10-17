"""Portable tests for the shared IDE model; no IDE or compiler is executed."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from tools import intellij


class IntelliJTests(unittest.TestCase):
    def test_committed_files_match_generator(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual([], intellij.check_files(root, intellij.project_files(root)))

    def test_root_and_independent_workspaces_are_attached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
            (root / "crates/a").mkdir(parents=True)
            (root / "crates/a/Cargo.toml").write_text('[package]\nname = "a"\n')
            (root / "research/probe").mkdir(parents=True)
            (root / "research/probe/Cargo.toml").write_text('[workspace]\n')
            paths = ["Cargo.toml", "crates/a/Cargo.toml", "research/probe/Cargo.toml"]
            roots, cargo = intellij.source_model(root, paths)
            self.assertIn("crates/a", roots)
            self.assertIn("research/probe", roots)
            self.assertEqual(["Cargo.toml", "research/probe/Cargo.toml"], cargo)

    def test_templates_are_not_attached_as_cargo_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text('[workspace]\n')
            roots, cargo = intellij.source_model(root, ["Cargo.toml", "sdk/rust/templates/app/Cargo.toml"])
            self.assertEqual(["Cargo.toml"], cargo)
            self.assertIn("sdk/rust", roots)

    def test_all_sdk_directories_are_modules_without_readme_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text('[workspace]\n')
            paths = ["Cargo.toml", "sdk/README.md", "sdk/new-language/README.md", "website/package.json", "tools/test.py"]
            roots, _ = intellij.source_model(root, paths)
            self.assertIn("sdk/new-language", roots)
            self.assertIn("website", roots)
            self.assertIn("tools", roots)
            self.assertNotIn("sdk/README.md", roots)

    def test_nested_content_roots_are_excluded_from_parent_only(self):
        roots = [".", "sdk", "sdk/rust", "sdk/rust/examples/demo"]
        tree = ET.fromstring(intellij.module_file(".", roots))
        excluded = [element.attrib["url"] for element in tree.findall(".//excludeFolder")]
        self.assertIn("file://$MODULE_DIR$/../../sdk", excluded)
        self.assertNotIn("file://$MODULE_DIR$/../../sdk/rust", excluded)
        child = ET.fromstring(intellij.module_file("sdk/rust", roots))
        self.assertIn("file://$MODULE_DIR$/../../sdk/rust/examples/demo", [item.attrib["url"] for item in child.findall(".//excludeFolder")])

    def test_java_sources_and_locked_jar_directory_are_indexed(self):
        tree = ET.fromstring(intellij.module_file("sdk/java-client", [".", "sdk/java-client"]))
        sources = {node.attrib["url"]: node.attrib for node in tree.findall(".//sourceFolder")}
        prefix = "file://$MODULE_DIR$/../../sdk/java-client/"
        self.assertEqual("true", sources[prefix + "build/generated/java"]["generated"])
        self.assertEqual("true", sources[prefix + "src/transportTest/java"]["isTestSource"])
        self.assertIn(prefix + "src/transport/java", sources)
        self.assertEqual(prefix + "build/deps", tree.find(".//jarDirectory").attrib["url"])
        self.assertNotIn("build", [item.attrib["pattern"] for item in tree.findall(".//excludePattern")])
        self.assertNotIn(prefix + "build", [item.attrib["url"] for item in tree.findall(".//excludeFolder")])

    def test_build_outputs_are_excluded_without_hiding_source_bins(self):
        tree = ET.fromstring(intellij.module_file("tools", [".", "tools"]))
        patterns = [item.attrib["pattern"] for item in tree.findall(".//excludePattern")]
        self.assertIn("target", patterns)
        self.assertIn("node_modules", patterns)
        self.assertNotIn("bin", patterns)
        self.assertNotIn("build", patterns)

    def test_xml_escapes_paths_and_names(self):
        text = intellij.module_file("sdk/a&b", [".", "sdk/a&b"])
        self.assertIn("a&amp;b", text)
        self.assertIn("sdk/a&b", ET.fromstring(text).find(".//content").attrib["url"])

    def test_paths_cannot_escape_checkout(self):
        for name in ("../x", "/tmp/x", "a/../x", "a\\b", "C:/x", "a//b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                intellij.safe_relative(name)

    def test_generator_is_deterministic_and_order_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text('[workspace]\n')
            paths = ["Cargo.toml", "website/package.json", "sdk/go/go.mod"]
            self.assertEqual(intellij.project_files(root, paths), intellij.project_files(root, list(reversed(paths))))

    def test_shared_runs_are_permanent_root_relative_and_not_startup_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text('[workspace]\n')
            files = intellij.project_files(root, ["Cargo.toml"])
            self.assertNotIn(".idea/workspace.xml", files)
            self.assertNotIn(".idea/startupTasks.xml", files)
            for name, text in files.items():
                if name.startswith(".run/"):
                    config = ET.fromstring(text).find("configuration")
                    self.assertEqual("false", config.attrib["default"])
                    self.assertIn("$PROJECT_DIR$", text)
                    self.assertIsNone(config.find("method/option"))

    def test_cargo_debug_defaults_are_locked_and_unprivileged(self):
        tree = ET.fromstring(intellij.cargo_configuration("help", "run --package latent --locked -- --help"))
        options = {item.attrib["name"]: item.attrib["value"] for item in tree.findall(".//configuration/option")}
        self.assertIn("--locked", options["command"])
        self.assertEqual("false", options["withSudo"])
        self.assertEqual("false", options["allFeatures"])

    def test_task_dispatch_is_argv_based_and_reuses_make(self):
        with mock.patch.object(intellij.sys, "executable", "/path with spaces/python"):
            self.assertEqual(["make", "check", "PYTHON='/path with spaces/python'"], intellij.task_command(Path("."), "check"))
            self.assertEqual(["/path with spaces/python", "sdk/java-client/tools/build.py", "test"], intellij.task_command(Path("."), "java-client-test"))
        with self.assertRaises(ValueError):
            intellij.task_command(Path("."), "check; echo injected")

    def test_full_validation_gets_a_fresh_owned_inventory_root(self):
        first = intellij.task_command(Path("."), "validate")[-1]
        second = intellij.task_command(Path("."), "validate")[-1]
        self.assertTrue(first.startswith("WORKSPACE_ROOT=target/ide/validate-"))
        self.assertNotEqual(first, second)
        self.assertNotIn("test", intellij.MAKE_TASKS)
        self.assertNotIn("test-run", intellij.MAKE_TASKS)
        self.assertNotIn("test-prepare", intellij.MAKE_TASKS)

    def test_make_tasks_exist_in_authoritative_makefile(self):
        text = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
        for task in intellij.MAKE_TASKS:
            self.assertTrue(any(line.startswith(task + ":") or line.startswith(task + " ") or (line.split(":")[0].split() and task in line.split(":")[0].split()) for line in text.splitlines() if ":" in line and not line.startswith("\t")), task)

    def test_check_detects_missing_modified_and_stale_owned_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {".run/LSF-a.run.xml": intellij.run_configuration("a", "Tests")}
            self.assertEqual([".run/LSF-a.run.xml"], intellij.check_files(root, files))
            intellij.write_files(root, files)
            self.assertEqual([], intellij.check_files(root, files))
            (root / ".run/LSF-stale.run.xml").write_text(next(iter(files.values())))
            (root / ".run/LSF-a.run.xml").write_text("changed")
            self.assertEqual([".run/LSF-a.run.xml", ".run/LSF-stale.run.xml"], intellij.check_files(root, files))

    def test_write_preserves_personal_files_and_removes_only_owned_stale_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intellij.write_files(root, {".run/LSF-old.run.xml": intellij.run_configuration("old", "Tests")})
            (root / ".run/personal.run.xml").write_text("personal")
            (root / ".idea").mkdir()
            (root / ".idea/workspace.xml").write_text("private workspace")
            intellij.write_files(root, {".run/LSF-new.run.xml": intellij.run_configuration("new", "Tests")})
            self.assertFalse((root / ".run/LSF-old.run.xml").exists())
            self.assertEqual("personal", (root / ".run/personal.run.xml").read_text())
            self.assertEqual("private workspace", (root / ".idea/workspace.xml").read_text())

    def test_write_refuses_unowned_destination_before_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".idea").mkdir()
            (root / ".idea/modules.xml").write_text("existing personal project")
            with self.assertRaises(ValueError):
                intellij.write_files(root, {".run/LSF-new.run.xml": intellij.run_configuration("new", "Tests"), ".idea/modules.xml": "replacement"})
            self.assertFalse((root / ".run/LSF-new.run.xml").exists())
            self.assertEqual("existing personal project", (root / ".idea/modules.xml").read_text())

    def test_symlink_destinations_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
                intellij.write_files(root, {".idea/modules.xml": "replacement"})
            self.assertEqual([], list(root.iterdir()))

    def test_shell_run_uses_terminal_path_not_a_machine_specific_interpreter(self):
        config = ET.fromstring(intellij.run_configuration("docs", "Checks"))
        options = {item.attrib["name"]: item.attrib["value"] for item in config.findall(".//configuration/option")}
        self.assertEqual("false", options["EXECUTE_SCRIPT_FILE"])
        self.assertEqual("", options["INTERPRETER_PATH"])
        self.assertEqual("bash tools/intellij.sh docs", options["SCRIPT_TEXT"])

    def test_workspace_excludes_and_absolute_glob_boundaries_are_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/no"]\n')
            paths = ["Cargo.toml", "crates/yes/Cargo.toml", "crates/no/Cargo.toml", "other/crates/no/Cargo.toml"]
            for path in paths[1:]:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text('[package]\nname = "fixture"\n')
            roots, _ = intellij.source_model(root, paths)
            self.assertIn("crates/yes", roots)
            self.assertNotIn("crates/no", roots)
            self.assertNotIn("other/crates/no", roots)

    def test_local_node_preparation_is_private_loopback_and_never_replaces_state(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(intellij.sys, "platform", "linux"):
            root = Path(directory)
            intellij.prepare_node(root)
            node_file = root / "target/ide/node/node.json"
            initial = node_file.read_bytes()
            node = intellij.json.loads(initial)
            client = intellij.json.loads((node_file.parent / "client.json").read_bytes())
            self.assertEqual("127.0.0.1:43170", node["bind"])
            self.assertEqual(node["credentials"][0]["token"], client["profiles"][0]["token"])
            self.assertGreaterEqual(len(node["credentials"][0]["token"]), 32)
            with self.assertRaises(FileExistsError):
                intellij.prepare_node(root)
            self.assertEqual(initial, node_file.read_bytes())

    def test_local_node_rejects_unsupported_hosts_before_writing(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(intellij.sys, "platform", "win32"):
            root = Path(directory)
            with self.assertRaises(ValueError):
                intellij.prepare_node(root)
            self.assertEqual([], list(root.iterdir()))

    def test_runner_preserves_exit_status_and_checkout_working_directory(self):
        with mock.patch.object(intellij.subprocess, "run") as run:
            run.return_value.returncode = 7
            self.assertEqual(7, intellij.main(["run", "docs"]))
            self.assertEqual(intellij.ROOT, run.call_args.kwargs["cwd"])
            self.assertFalse(run.call_args.kwargs["check"])
            self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()

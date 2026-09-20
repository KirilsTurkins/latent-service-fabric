"""Recipe equivalence and failure semantics; subprocess mocks are NOT build evidence."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import ci_cargo as cargo


class CargoRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Cargo.toml").write_text('[workspace.package]\nrust-version = "1.94.1"\n')
        (self.root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.97.1"\n')
        self.root_patch = mock.patch.object(cargo, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def commands(self, recipe):
        return [entry["argv"] for entry in cargo.plan(recipe)["commands"]]

    def test_workspace_build_and_check_are_not_assumed_redundant(self):
        flags = ["--workspace", "--all-targets", "--all-features", "--locked"]
        self.assertEqual(self.commands("workspace-check"), [["cargo", "check", *flags]])
        self.assertEqual(self.commands("prepare"), [
            ["cargo", "build", *flags],
            ["cargo", "test", *flags, "--no-run", "--message-format=json,json-render-diagnostics"],
        ])

    def test_independent_production_feature_resolution_is_retained(self):
        self.assertEqual(self.commands("production"), [
            ["cargo", "check", "-p", "latent", "-p", "latentd", "--all-features", "--locked"],
            ["cargo", "check", "-p", "latent-wasmtime", "--bin", "latent-aot-compiler", "--all-features", "--locked"],
        ])
        self.assertTrue(all("--workspace" not in command and "--all-targets" not in command
                            for command in self.commands("production")))

    def test_all_five_host_guest_binding_checks_are_retained(self):
        self.assertEqual(self.commands("bindings"), [
            ["cargo", "check", "-p", "latent-rpc", "--all-targets", "--all-features", "--locked"],
            ["cargo", "check", "-p", "latent-component-bindings", "--locked"],
            ["cargo", "check", "-p", "latent-component-bindings", "--target", "wasm32-wasip2", "--locked"],
            ["cargo", "check", "-p", "latent-toolchain-smoke", "--target", "wasm32-wasip2", "--locked"],
            ["cargo", "check", "-p", "latent-toolchain-smoke", "--example", "echo-capsule", "--target", "wasm32-wasip2", "--locked"],
        ])

    def test_tests_doctests_and_compatibility_negative_controls_are_retained(self):
        self.assertEqual(self.commands("test"), [
            ["cargo", "test", "--workspace", "--all-targets", "--all-features", "--locked"],
            ["cargo", "test", "-p", "latent-admission", "-p", "latent-scheduler", "--doc", "--locked"],
            ["cargo", "test", "-p", "latent-signing", "--lib", "--locked", "--features", "ed25519-dalek/legacy_compatibility", "crypto::tests"],
        ])

    def test_format_and_clippy_policy_are_retained(self):
        self.assertEqual(self.commands("format"), [["cargo", "fmt", "--all", "--check"]])
        self.assertEqual(self.commands("clippy"), [
            ["cargo", "clippy", "--workspace", "--all-targets", "--all-features", "--locked"],
            ["cargo", "clippy", "-p", "latent", "-p", "latentd", "-p", "latent-testkit", "-p", "latent-admission", "--all-targets", "--all-features", "--locked", "--no-deps", "--", "-D", "warnings"],
        ])

    def test_msrv_is_independent_and_comes_from_workspace_declaration(self):
        self.assertEqual(self.commands("msrv"), [["cargo", "+1.94.1", "check", "--workspace", "--all-targets", "--all-features", "--locked"]])
        (self.root / "Cargo.toml").write_text('[workspace.package]\nrust-version = "1.95.0"\n')
        self.assertEqual(self.commands("msrv")[0][1], "+1.95.0")
        with self.assertRaises(ValueError):
            cargo.plan("msrv", "ci-correctness")

    def test_unknown_recipes_and_configurations_fail_closed(self):
        for recipe, config in [("all", "current"), ("test", "release"), ("format", "ci-correctness")]:
            with self.subTest(recipe=recipe, config=config), self.assertRaises(ValueError):
                cargo.plan(recipe, config)

    def test_options_precede_rustc_separator(self):
        strict = cargo.plan("clippy", "ci-correctness", timings=True)["commands"][1]["argv"]
        self.assertLess(strict.index("--config"), strict.index("--"))
        self.assertLess(strict.index("--timings"), strict.index("--"))
        self.assertEqual(strict[-3:], ["--", "-D", "warnings"])
        self.assertNotIn("--config", self.commands("clippy")[1])

    def test_timings_do_not_change_formatting(self):
        self.assertEqual(cargo.plan("format", timings=True)["commands"][0]["argv"], self.commands("format")[0])

    def test_every_command_has_a_coverage_tuple(self):
        for recipe in cargo.RECIPES:
            for entry in cargo.plan(recipe)["commands"]:
                for field in ("name", "packages", "features", "targets", "profile", "toolchain", "declaredToolchain", "coverage"):
                    self.assertTrue(entry[field], (recipe, field))

    def test_workflow_keeps_required_recipes_and_runtime_inventory_handoff(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
        rust = workflow.split("\n  rust:\n", 1)[1].split("\n  oci-registry:\n", 1)[0]
        for recipe in ("format", *cargo.RUST_RECIPES):
            self.assertIn("python3 tools/ci_cargo.py run " + recipe, rust)
        self.assertIn('run prepare --inventory "$RUNNER_TEMP/lsf-workspace-tests.jsonl"', rust)
        self.assertIn('tools/ci_rust_artifacts.py --inventory "$RUNNER_TEMP/lsf-workspace-tests.jsonl"', rust)
        self.assertIn("python3 tools/ci_cargo.py run msrv", workflow)
        self.assertNotIn("--configuration ci-correctness", workflow)
        self.assertIn("    name: CI result\n    if: always()", workflow)

    def test_missing_toolchain_declaration_fails_without_executing(self):
        (self.root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = 12\n')
        with mock.patch.object(cargo.subprocess, "run") as run, self.assertRaises(ValueError):
            cargo.execute("test")
        run.assert_not_called()

    def test_failure_stops_later_commands(self):
        with mock.patch.object(cargo.subprocess, "run", return_value=subprocess.CompletedProcess([], 31)) as run:
            self.assertEqual(cargo.execute("bindings"), 31)
            self.assertEqual(run.call_count, 1)

    def test_no_cache_hit_short_circuit(self):
        with mock.patch.dict("os.environ", {"CACHE_HIT": "true", "CARGO_CACHE_HIT": "true"}), \
             mock.patch.object(cargo.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(cargo.execute("test"), 0)
            self.assertEqual(run.call_count, 3)

    def test_signal_exit_is_a_failure(self):
        with mock.patch.object(cargo.subprocess, "run", return_value=subprocess.CompletedProcess([], -9)):
            self.assertEqual(cargo.execute("workspace-check"), 137)

    def test_inventory_option_is_exclusive_to_preparation(self):
        with self.assertRaises(ValueError):
            cargo.execute("prepare")
        with self.assertRaises(ValueError):
            cargo.execute("test", inventory=self.root / "target/inventory.jsonl")

    def test_failed_first_build_removes_stale_inventory(self):
        path = self.root / "target/inventory.jsonl"
        path.parent.mkdir()
        path.write_text("old positive-looking inventory")
        with mock.patch.object(cargo.subprocess, "run", return_value=subprocess.CompletedProcess([], 17)):
            self.assertEqual(cargo.execute("prepare", inventory=path), 17)
        self.assertFalse(path.exists())

    def prepare_with_output(self, output, code=0):
        path = self.root / "target/inventory.jsonl"
        def run(command, **kwargs):
            if "stdout" in kwargs:
                self.assertFalse(path.exists())
                kwargs["stdout"].write(output)
                return subprocess.CompletedProcess(command, code)
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(cargo.subprocess, "run", side_effect=run):
            result = cargo.execute("prepare", inventory=path)
        return result, path

    def test_successful_inventory_is_published_atomically(self):
        output = '{"reason":"compiler-artifact"}\n{"reason":"build-finished","success":true}\n'
        result, path = self.prepare_with_output(output)
        self.assertEqual(result, 0)
        self.assertEqual(path.read_text(), output)
        self.assertEqual(list(path.parent.glob(".cargo-inventory-*")), [])

    def test_partial_inventory_is_removed_on_cargo_failure(self):
        result, path = self.prepare_with_output('{"reason":', 23)
        self.assertEqual(result, 23)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.glob(".cargo-inventory-*")), [])

    def test_invalid_or_unsuccessful_stream_never_publishes(self):
        for output in ("", "garbage", "[]\n", '{"reason":"compiler-artifact"}\n',
                       '{"reason":"build-finished","success":true}\n',
                       '{"reason":"compiler-artifact"}\n{"reason":"build-finished","success":false}\n',
                       '{"reason":"compiler-artifact"}\n{"reason":"build-finished","success":true}\n{}\n',
                       '{"reason":"compiler-artifact","reason":"build-finished","success":true}\n'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.prepare_with_output(output)
            self.assertFalse((self.root / "target/inventory.jsonl").exists())
            self.assertEqual(list((self.root / "target").glob(".cargo-inventory-*")), [])

    def test_inventory_cannot_overwrite_source_or_follow_symlinks(self):
        target = self.root / "target"
        target.mkdir()
        (target / "link.jsonl").symlink_to(self.root / "Cargo.toml")
        (target / "linked-parent").symlink_to(self.root, target_is_directory=True)
        for path in (self.root / "Cargo.toml", target / "link.jsonl", target,
                     target / "linked-parent/Cargo.toml"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                cargo.execute("prepare", inventory=path)
        self.assertIn("rust-version", (self.root / "Cargo.toml").read_text())

    def test_overlong_inventory_line_fails(self):
        path = self.root / "large.jsonl"
        path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            cargo.validate_inventory(path)

    def test_cli_plan_is_json_and_execution_errors_return_failure(self):
        with mock.patch("builtins.print") as output:
            self.assertEqual(cargo.main(["plan", "test"]), 0)
        self.assertEqual(json.loads(output.call_args.args[0])["recipe"], "test")
        with mock.patch.object(cargo.subprocess, "run", side_effect=FileNotFoundError("Cargo missing")), mock.patch("builtins.print"):
            self.assertEqual(cargo.main(["run", "test"]), 1)


if __name__ == "__main__":
    unittest.main()

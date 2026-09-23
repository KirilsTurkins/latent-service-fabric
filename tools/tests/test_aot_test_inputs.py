"""Preparation tests use tiny ELF files, never as sandbox qualification evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import aot_test_inputs as inputs


class PreparedInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        (self.repo / "target/debug/deps").mkdir(parents=True)
        self.package = self.repo / "crates/latent-wasmtime"
        self.package.mkdir(parents=True)
        for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml"):
            (self.repo / name).write_text("test identity\n")
        (self.package / "Cargo.toml").write_text("test package\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        # Cargo's target directory is untracked, just as in the real repository.
        self.records = []
        for role in ("compiler", *inputs.HARNESS_NAMES):
            binary = role == "compiler"
            name = "latent-aot-compiler" if binary else role
            relative = f"src/bin/{name}.rs" if binary else f"tests/{name}.rs"
            path = self.repo / "target/debug" / (name if binary else f"deps/{name}-exact")
            shutil.copyfile("/bin/true", path)
            path.chmod(0o755)
            self.records.append({"reason": "compiler-artifact", "manifest_path": str(self.package / "Cargo.toml"),
                                 "target": {"name": name, "kind": ["bin" if binary else "test"],
                                            "src_path": str(self.package / relative)},
                                 "profile": {"test": not binary, "opt_level": "0"},
                                 "features": list(inputs.FEATURES), "executable": str(path)})
        self.records.append({"reason": "build-finished", "success": True})
        self.inventory = self.repo / "target/inventory.jsonl"
        self.write_inventory()
        self.output = self.repo / "target/prepared"

    def write_inventory(self):
        self.inventory.write_text("".join(json.dumps(record) + "\n" for record in self.records))

    def prepare(self):
        # Only querying rustc's installed library directory is mocked locally.
        # objcopy, hashing, filesystem operations, and Git checks execute for real.
        with mock.patch.object(inputs.artifacts, "cargo_environment", return_value={
                "LD_LIBRARY_PATH": str(self.repo / "target/debug/deps"),
                "CARGO_MANIFEST_DIR": str(self.package)}):
            return inputs.prepare(self.repo, self.inventory, self.output)

    def rewrite(self, path, change):
        manifest = inputs.read_json(path)
        change(manifest)
        path.chmod(0o644)
        path.write_text(json.dumps(manifest))

    def test_exact_copy_keeps_originals_and_records_separate_costs(self):
        originals = {record["executable"]: inputs.digest(Path(record["executable"]))
                     for record in self.records[:-1]}
        path = self.prepare()
        manifest = inputs.validate(self.repo, path)
        for original, digest in originals.items():
            self.assertEqual(inputs.digest(Path(original)), digest)
        for role in ("compiler", "aot_supervisor"):
            record = manifest["entries"][role]["prepared"]
            self.assertEqual(inputs.digest(Path(record["path"])), record["sha256"])
            self.assertGreater(manifest["preparation_ns"][role + "_strip_ns"], 0)
            self.assertGreater(manifest["preparation_ns"][role + "_expected_digest_ns"], 0)
        self.assertEqual(inputs.environment(path, manifest)["LSF_AOT_TEST_INPUTS_SHA256"],
                         bytes(inputs.digest(path)).hex())
        self.assertNotIn("compiler", manifest["runtime"])

    def test_validation_and_environment_do_not_build_strip_or_query_rustc(self):
        path = self.prepare()
        original = inputs.artifacts.run_owned
        calls = []
        def guarded(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[0], "git")
            return original(command, **kwargs)
        with mock.patch.object(inputs.artifacts, "run_owned", side_effect=guarded):
            manifest = inputs.validate(self.repo, path)
            inputs.environment(path, manifest)
        self.assertTrue(calls)

    def test_missing_modified_or_nonexecutable_copy_is_rejected(self):
        path = self.prepare()
        copy = self.output / "compiler"
        saved = copy.read_bytes()
        for mutation in ("changed", "missing", "mode"):
            with self.subTest(mutation=mutation):
                if copy.exists():
                    copy.chmod(0o755)
                copy.write_bytes(saved)
                copy.chmod(0o555)
                if mutation == "missing":
                    copy.unlink()
                elif mutation == "changed":
                    copy.chmod(0o755)
                    copy.write_bytes(b"not the prepared executable")
                else:
                    copy.chmod(0o444)
                with self.assertRaises((inputs.InputError, OSError)):
                    inputs.validate(self.repo, path)

    def test_wrong_profile_and_missing_role_are_rejected(self):
        path = self.prepare()
        self.rewrite(path, lambda data: data.update(profile="release"))
        with self.assertRaisesRegex(inputs.InputError, "profile"):
            inputs.validate(self.repo, path)
        self.rewrite(path, lambda data: data.update(profile=inputs.PROFILE))
        self.rewrite(path, lambda data: data["entries"].pop("compiler"))
        with self.assertRaisesRegex(inputs.InputError, "roles"):
            inputs.validate(self.repo, path)

    def test_stale_original_and_checkout_are_rejected(self):
        path = self.prepare()
        original = Path(self.records[0]["executable"])
        with original.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(inputs.InputError, "changed-file"):
            inputs.validate(self.repo, path)
        shutil.copyfile("/bin/true", original)
        (self.repo / "Cargo.lock").write_text("changed lock\n")
        with self.assertRaisesRegex(inputs.InputError, "clean-tracked"):
            inputs.validate(self.repo, path)

    def test_symlink_copy_is_rejected(self):
        path = self.prepare()
        copy = self.output / "compiler"
        copy.unlink()
        copy.symlink_to(self.records[0]["executable"])
        with self.assertRaisesRegex(inputs.InputError, "symlink"):
            inputs.validate(self.repo, path)

    def test_incomplete_failed_duplicate_foreign_and_wrong_profile_inventories(self):
        baseline = json.loads(json.dumps(self.records))
        for mutation in ("incomplete", "failed", "duplicate", "foreign", "profile", "after-finish", "features"):
            with self.subTest(mutation=mutation):
                self.records = json.loads(json.dumps(baseline))
                if mutation == "incomplete":
                    self.records.pop()
                elif mutation == "failed":
                    self.records[-1]["success"] = False
                elif mutation == "duplicate":
                    self.records.insert(0, self.records[0])
                elif mutation == "foreign":
                    self.records[0]["executable"] = "/bin/true"
                elif mutation == "profile":
                    self.records[0]["profile"]["opt_level"] = "3"
                elif mutation == "features":
                    self.records[0]["features"] = ["different-feature"]
                else:
                    self.records.append(self.records[0])
                self.write_inventory()
                with self.assertRaises((inputs.InputError, OSError)):
                    inputs.inventory_inputs(self.inventory, self.repo)

    def test_duplicate_json_key_and_oversized_manifest_are_rejected(self):
        path = self.repo / "manifest.json"
        path.write_text('{"profile":"a","profile":"b"}')
        with self.assertRaises(inputs.artifacts.ArtifactError):
            inputs.read_json(path)
        path.write_bytes(b" " * (inputs.MAX_MANIFEST + 1))
        with self.assertRaisesRegex(inputs.InputError, "manifest-limit"):
            inputs.read_json(path)

    def test_execution_only_forbids_preparation_before_any_command(self):
        with mock.patch.dict(os.environ, {"LSF_AOT_TEST_EXECUTION_ONLY": "1"}):
            with mock.patch.object(inputs.artifacts, "run_owned") as command:
                with self.assertRaisesRegex(inputs.InputError, "preparation-forbidden"):
                    self.prepare()
                command.assert_not_called()

    def test_missing_measurement_feature_is_not_the_all_features_profile(self):
        for record in self.records[:-1]:
            record["features"] = []
        self.write_inventory()
        with self.assertRaisesRegex(inputs.InputError, "feature"):
            self.prepare()

    def test_previous_feature_closure_is_not_the_current_profile(self):
        for record in self.records[:-1]:
            record["features"] = ["aot-test-timings"]
        self.write_inventory()
        with self.assertRaisesRegex(inputs.InputError, "incompatible-cargo-feature-sets"):
            self.prepare()

    def test_changed_inventory_and_runtime_injection_fail_validation(self):
        path = self.prepare()
        saved = self.inventory.read_bytes()
        self.inventory.write_bytes(saved + b" ")
        with self.assertRaisesRegex(inputs.InputError, "changed-file"):
            inputs.validate(self.repo, path)
        self.inventory.write_bytes(saved)
        self.rewrite(path, lambda data: data["runtime"].update(LD_PRELOAD="/unapproved/library"))
        with self.assertRaisesRegex(inputs.InputError, "invalid-runtime"):
            inputs.validate(self.repo, path)

    def test_existing_output_is_never_overwritten(self):
        self.prepare()
        with self.assertRaisesRegex(inputs.InputError, "output-exists"):
            self.prepare()


if __name__ == "__main__":
    unittest.main()

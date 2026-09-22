"""Cache compatibility tests, not evidence of Cargo reuse or benchmark improvement."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest import mock

from tools import ci_cargo, ci_cargo_cache as cache


class CacheIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.names = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml",
                      "tools/ci_cargo.py", "tools/ci_cargo_cache.py", "crates/example/Cargo.toml",
                      "crates/example/build.rs", ".cargo/ci-correctness.toml",
                      ".github/workflows/ci.yml", "README.md", "crates/example/src/lib.rs"]
        for name in self.names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("input: " + name)
        self.inputs = {"files": {"Cargo.lock": "lock-hash"},
                       "tools": {"rustc": "compiler-hash", "cargo": "cargo-hash", "CC": "native-hash"},
                       "host": {"system": "Linux", "machine": "x86_64", "target": "x86_64-unknown-linux-gnu"},
                       "environment": {"CARGO_INCREMENTAL": "0"}}

    def digest(self, **changes):
        return cache.identity(**(self.inputs | changes))["digest"]

    def test_identity_is_deterministic_and_order_independent(self):
        self.assertEqual(self.digest(), self.digest())
        self.assertEqual(self.digest(tools=dict(reversed(list(self.inputs["tools"].items())))), self.digest())
        self.assertEqual(len(self.digest()), 64)

    def test_toolchain_architecture_profile_flags_and_lock_invalidate(self):
        variants = [
            {"files": {"Cargo.lock": "new-lock"}},
            {"tools": self.inputs["tools"] | {"rustc": "another-compiler"}},
            {"tools": self.inputs["tools"] | {"cargo": "another-cargo"}},
            {"tools": self.inputs["tools"] | {"CC": "another-native-compiler"}},
            {"host": self.inputs["host"] | {"machine": "aarch64"}},
            {"host": self.inputs["host"] | {"target": "aarch64-unknown-linux-gnu"}},
            {"environment": {"RUSTFLAGS": "-Ctarget-cpu=native"}},
            {"environment": {"CARGO_ENCODED_RUSTFLAGS": "-C\x1fdebuginfo=1"}},
            {"environment": {"CARGO_PROFILE_TEST_DEBUG": "1"}},
            {"configuration": "ci-correctness"}, {"recipe": "msrv"},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(self.digest(**variant), self.digest())

    def test_recipe_feature_and_target_changes_invalidate(self):
        baseline = self.digest()
        first = ci_cargo.RECIPES["workspace-check"][0]
        for changed in (replace(first, features="default"), replace(first, targets="wasm32-wasip2"),
                        replace(first, args=("check", "--workspace", "--locked"))):
            with mock.patch.dict(ci_cargo.RECIPES, {"workspace-check": (changed,)}):
                self.assertNotEqual(baseline, self.digest())

    def test_every_build_input_changes_its_hash(self):
        before = cache.hash_inputs(self.root, self.names, "current")
        for name in before:
            path = self.root / name
            old = path.read_bytes()
            path.write_bytes(old + b"\nchanged")
            with self.subTest(name=name):
                self.assertNotEqual(before, cache.hash_inputs(self.root, self.names, "current"))
            path.write_bytes(old)

    def test_unrelated_workflow_docs_and_source_changes_do_not_invalidate(self):
        before = cache.hash_inputs(self.root, self.names, "current")
        for name in (".github/workflows/ci.yml", "README.md", "crates/example/src/lib.rs"):
            (self.root / name).write_text("unrelated new contents")
        self.assertEqual(before, cache.hash_inputs(self.root, self.names, "current"))

    def test_inactive_profile_is_not_a_baseline_build_input(self):
        baseline = cache.hash_inputs(self.root, self.names, "current")
        candidate = cache.hash_inputs(self.root, self.names, "ci-correctness")
        (self.root / ".cargo/ci-correctness.toml").write_text("new candidate")
        self.assertEqual(baseline, cache.hash_inputs(self.root, self.names, "current"))
        self.assertNotEqual(candidate, cache.hash_inputs(self.root, self.names, "ci-correctness"))

    def test_missing_deleted_foreign_and_symlinked_inputs_fail(self):
        with self.assertRaises(ValueError):
            cache.hash_inputs(self.root, self.names[1:], "current")
        path = self.root / "Cargo.lock"
        path.unlink()
        with self.assertRaises(ValueError):
            cache.hash_inputs(self.root, self.names, "current")
        path.symlink_to(self.root / "README.md")
        with self.assertRaises(ValueError):
            cache.hash_inputs(self.root, self.names, "current")
        path.unlink()
        path.write_text("restored lock")
        for name in ("../Cargo.toml", "/tmp/Cargo.toml"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                cache.hash_inputs(self.root, self.names + [name], "current")

    def test_input_count_and_size_are_bounded(self):
        with mock.patch.object(cache, "MAX_INPUT_FILES", 1), self.assertRaises(ValueError):
            cache.hash_inputs(self.root, self.names, "current")
        with mock.patch.object(cache, "MAX_INPUT_BYTES", 1), self.assertRaises(ValueError):
            cache.hash_inputs(self.root, self.names, "current")

    def test_credentials_and_unrelated_environment_are_not_retained(self):
        environment = {"RUSTFLAGS": "--cfg secret_looking_value", "GITHUB_TOKEN": "real-secret",
                       "CARGO_REGISTRIES_PRIVATE_TOKEN": "registry-secret", "CARGO_PROFILE_SECRET": "other-secret",
                       "ACTIONS_RUNTIME_TOKEN": "action-secret", "HOME": "/unrelated", "GITHUB_JOB": "another-layout"}
        output = cache.environment_identity(environment)
        self.assertEqual(set(output), {"RUSTFLAGS"})
        serialized = json.dumps(output)
        for value in environment.values():
            self.assertNotIn(value, serialized)
        self.assertEqual(self.digest(environment={}), self.digest(environment={"GITHUB_JOB": "another-layout"}))

    def test_only_trusted_refs_may_write(self):
        trusted = {("push", "refs/heads/development"), ("workflow_dispatch", "refs/heads/development"),
                   ("workflow_dispatch", "refs/heads/release")}
        for event in ("push", "pull_request", "pull_request_target", "workflow_dispatch", "schedule"):
            for ref in ("refs/heads/development", "refs/heads/release", "refs/heads/feat/example", "refs/pull/5/merge"):
                self.assertEqual(cache.writer_allowed(event, ref), (event, ref) in trusted)

    def test_workflow_cache_writes_and_scope_match_the_reviewed_policy(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
        rust = workflow.split("\n  rust:\n", 1)[1].split("\n  oci-registry:\n", 1)[0]
        for option in ("cache-targets", "cache-bin", "cache-workspace-crates", "cache-all-crates", "cache-on-failure"):
            self.assertIn(option + ": false", rust)
        self.assertIn("default: baseline", workflow)
        self.assertIn("steps.cargo-cache-identity.outputs.prefix", rust)
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/development'", rust)
        self.assertIn("github.ref == 'refs/heads/development' || github.ref == 'refs/heads/release'", rust)
        self.assertNotIn("pull_request_target", rust)

    def test_candidate_rejects_unknown_or_msrv_profile_combinations(self):
        for changed in ({"recipe": "release"}, {"configuration": "release"},
                        {"recipe": "msrv", "configuration": "ci-correctness"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.digest(**changed)

    def test_candidate_rejects_unobserved_compiler_or_linker_overrides(self):
        cache.validate_supported_environment({"RUSTFLAGS": "-Cdebuginfo=1"})
        for name in ("RUSTC", "RUSTC_WRAPPER", "CARGO_TARGET_DIR", "CARGO_BUILD_TARGET",
                     "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                cache.validate_supported_environment({name: "/custom/tool"})
        for data in (b'[build]\nrustc="custom"', b'[build]\ntarget-dir="custom"',
                     b'[target.x86_64-unknown-linux-gnu]\nlinker="custom"', b'not valid TOML'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                cache.validate_supported_configuration(data)
        cache.validate_supported_configuration(b'[profile.dev]\ndebug=1\n[build]\njobs=2')

    def test_observation_failure_cannot_produce_a_key(self):
        with mock.patch.object(cache.subprocess, "run", return_value=subprocess.CompletedProcess([], 2, "", "private error")):
            with self.assertRaisesRegex(ValueError, "cannot observe") as error:
                cache.checked_output(["rustc", "-vV"], self.root)
            self.assertNotIn("private error", str(error.exception))
        with mock.patch.object(cache, "observe", side_effect=ValueError("missing input")), mock.patch("builtins.print"):
            output = self.root / "outputs"
            self.assertEqual(cache.main(["--github-output", str(output)]), 1)
            self.assertFalse(output.exists())

    def test_full_compatibility_digest_is_in_the_nonfallback_prefix(self):
        value = cache.identity(**self.inputs)
        output = self.root / "outputs"
        with mock.patch.object(cache, "observe", return_value=value), mock.patch("builtins.print"):
            self.assertEqual(cache.main(["--github-output", str(output)]), 0)
        self.assertEqual(output.read_text(), f"prefix={cache.NAMESPACE}-{value['digest']}\n")

    def test_cache_scope_is_dependencies_not_evidence_or_workspace_outputs(self):
        value = cache.identity(**self.inputs)
        self.assertEqual(value["cachePaths"], ["target/debug/.fingerprint", "target/debug/build", "target/debug/deps"])
        self.assertNotIn("target/debug", value["cachePaths"])
        self.assertNotIn("target", value["cachePaths"])

    def test_opt_in_profile_preserves_correctness_and_never_overrides_release(self):
        profile = tomllib.loads((Path(__file__).resolve().parents[2] / ".cargo/ci-correctness.toml").read_text())
        self.assertEqual(set(profile["profile"]), {"dev", "test"})
        for name in ("dev", "test"):
            self.assertEqual(profile["profile"][name]["opt-level"], 0)
            self.assertEqual(profile["profile"][name]["debug"], 1)
            self.assertIs(profile["profile"][name]["debug-assertions"], True)
            self.assertIs(profile["profile"][name]["overflow-checks"], True)
            self.assertIs(profile["profile"][name]["incremental"], False)
        self.assertEqual(profile["build"]["jobs"], 2)


if __name__ == "__main__":
    unittest.main()

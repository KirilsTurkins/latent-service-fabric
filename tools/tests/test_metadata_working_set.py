"""Metadata suite selection/observations fail closed without Cargo or heavy publication."""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tools import ci_rust_artifacts as artifacts


def valid_observations() -> list[dict]:
    values = []
    for mode in ("publish", "apply", "reopen"):
        observation = {"mode": mode, "complete": True}
        if mode == "publish":
            observation.update(verified_releases=32, documentation_bytes=32 * 3 * 1024 * 1024)
        else:
            observation["scenarios"] = [
                {"name": name, "routes": 32, "generation": 1,
                 "baseline_kib": 20_000, "peak_kib": 30_000, "growth_kib": 10_000,
                 "state_bytes": 100_000, "state_unchanged": mode == "reopen"}
                for name in ("distinct-releases", "shared-release-distinct-scopes")
            ]
        values.append({"schema": artifacts.METADATA_SCHEMA, "mode": mode, "releases": 32,
                       "documentation_bytes_per_release": 3 * 1024 * 1024,
                       "max_growth_kib": 64 * 1024, "max_state_bytes": 512 * 1024,
                       "wall_ns": 10_000, "os": "linux", "arch": "x86_64",
                       "observation": observation})
    return values


def encode(values: list[dict]) -> bytes:
    return "".join("LSF_METADATA_MEASUREMENT " + json.dumps(value) + "\n" for value in values).encode()


class ObservationTests(unittest.TestCase):
    def test_exact_complete_observations(self):
        values = valid_observations()
        self.assertEqual(artifacts.validate_metadata_observations(encode(values)), values)

    def test_missing_duplicate_reordered_and_small_substitute_fail(self):
        values = valid_observations()
        for wrong in ([], values[:1], values[:2], values * 2, values[::-1]):
            with self.subTest(wrong=wrong), self.assertRaises(artifacts.ArtifactError):
                artifacts.validate_metadata_observations(encode(wrong))
        for key, replacement in (("schema", "metadata-correctness"), ("releases", 4),
                                 ("documentation_bytes_per_release", 16 * 1024),
                                 ("max_growth_kib", 128 * 1024), ("max_state_bytes", 1024 * 1024),
                                 ("wall_ns", 0), ("wall_ns", True), ("arch", ""), ("os", "darwin")):
            wrong = copy.deepcopy(values)
            wrong[1][key] = replacement
            with self.subTest(key=key), self.assertRaises(artifacts.ArtifactError):
                artifacts.validate_metadata_observations(encode(wrong))

    def test_zero_missing_negative_or_malformed_memory_is_never_a_measurement(self):
        for key, replacement in (("baseline_kib", 0), ("baseline_kib", None),
                                 ("baseline_kib", True), ("peak_kib", 10),
                                 ("growth_kib", 0), ("growth_kib", 10_000.0),
                                 ("state_bytes", 512 * 1024), ("state_bytes", 0),
                                 ("routes", 0), ("generation", True),
                                 ("state_unchanged", False), ("name", "wrong")):
            wrong = valid_observations()
            wrong[2]["observation"]["scenarios"][0][key] = replacement
            with self.subTest(key=key), self.assertRaises(artifacts.ArtifactError):
                artifacts.validate_metadata_observations(encode(wrong))
        wrong = valid_observations()
        scenario = wrong[1]["observation"]["scenarios"][0]
        scenario.update(peak_kib=20_000 + 64 * 1024 + 1, growth_kib=64 * 1024 + 1)
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.validate_metadata_observations(encode(wrong))

    def test_missing_scenario_or_incomplete_publication_fails(self):
        for mode in range(3):
            wrong = valid_observations()
            wrong[mode]["observation"]["complete"] = False
            with self.subTest(mode=mode), self.assertRaises(artifacts.ArtifactError):
                artifacts.validate_metadata_observations(encode(wrong))
        for mutation in ([], [{}], [{}, {}], None):
            wrong = valid_observations()
            wrong[1]["observation"]["scenarios"] = mutation
            with self.subTest(mutation=mutation), self.assertRaises(artifacts.ArtifactError):
                artifacts.validate_metadata_observations(encode(wrong))
        wrong = valid_observations()
        wrong[0]["observation"]["verified_releases"] = 31
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.validate_metadata_observations(encode(wrong))

    def test_duplicate_json_keys_are_rejected(self):
        wrong = encode(valid_observations()).replace(b'"mode": "publish"', b'"mode": "publish", "mode": "publish"', 1)
        with self.assertRaisesRegex(artifacts.ArtifactError, "duplicate"):
            artifacts.validate_metadata_observations(wrong)


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.suite = artifacts.SUITES["metadata-working-set"]
        self.repo = Path.cwd().resolve()
        self.artifact = artifacts.Artifact(self.repo / "test-binary", self.repo, ())
        self.listing = (self.suite.filter + ": test\n\n1 test, 0 benchmarks\n").encode()
        self.success = b"test result: ok. 1 passed; 0 failed; 0 ignored; 0 filtered out; finished in 0.00s\n"

    def test_inventory_declares_exact_linux_physical_owner(self):
        self.assertEqual(self.suite.manifest, "crates/latent-control-store/Cargo.toml")
        self.assertEqual(self.suite.target, "latent_control_store")
        self.assertEqual(self.suite.source, "src/lib.rs")
        self.assertEqual(self.suite.names, frozenset({artifacts.METADATA_TEST}))
        self.assertTrue(self.suite.exact)
        self.assertEqual(self.suite.timeout, 930)
        self.assertEqual(self.suite.platforms, ("linux",))
        self.assertEqual(self.suite.resource_class, "physical-exclusive")
        self.assertIn("proc-vmhwm", self.suite.prerequisites)

    def test_one_ignored_execution_preserves_observations_and_full_deadline(self):
        with patch.object(artifacts.sys, "platform", "linux"), \
                patch.object(artifacts, "read_inventory", return_value=self.artifact), \
                patch.object(artifacts, "cargo_environment", return_value={}), \
                patch.object(artifacts, "run_owned", side_effect=[
                    (0, self.listing), (0, self.success + encode(valid_observations()))]) as run, \
                redirect_stdout(io.StringIO()):
            artifacts.run_suite(self.repo, self.repo / "inventory", self.suite, {})
        self.assertEqual(run.call_count, 2)  # discovery, then exactly one parent execution
        self.assertEqual(run.call_args.args[0], [str(self.artifact.executable), artifacts.METADATA_TEST,
                         "--ignored", "--exact", "--test-threads=1", "--show-output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 930)

    def test_success_without_observations_or_missing_ignored_test_is_rejected(self):
        for listing, execution in ((self.listing, self.success),
                                   (b"0 tests, 0 benchmarks\n", self.success)):
            with patch.object(artifacts.sys, "platform", "linux"), \
                    patch.object(artifacts, "read_inventory", return_value=self.artifact), \
                    patch.object(artifacts, "cargo_environment", return_value={}), \
                    patch.object(artifacts, "run_owned", side_effect=[(0, listing), (0, execution)]), \
                    redirect_stdout(io.StringIO()), self.assertRaises(artifacts.ArtifactError):
                artifacts.run_suite(self.repo, self.repo / "inventory", self.suite, {})

    def test_inherited_child_modes_faults_and_unsupported_host_never_run(self):
        with patch.object(artifacts.sys, "platform", "linux"), \
                patch.object(artifacts, "read_inventory") as read:
            for key in ("LSF_DEPLOYMENT_MEMORY_MODE", "LSF_DEPLOYMENT_MEMORY_ROOT", "LSF_METADATA_RETAIN"):
                with self.subTest(key=key), self.assertRaisesRegex(artifacts.ArtifactError, "unexpected"):
                    artifacts.run_suite(self.repo, self.repo / "inventory", self.suite, {key: ""})
            read.assert_not_called()
        with patch.object(artifacts.sys, "platform", "darwin"), \
                self.assertRaisesRegex(artifacts.ArtifactError, "unsupported"):
            artifacts.run_suite(self.repo, self.repo / "inventory", self.suite, {})

    def test_real_process_output_cap_and_deadline_still_fail_closed(self):
        for code, timeout, maximum, reason in (("print('x' * 100000)", 5, 16, "output-limit"),
                                               ("import time; time.sleep(30)", 0.1, 16, "timeout")):
            with self.subTest(reason=reason), self.assertRaisesRegex(artifacts.ArtifactError, reason):
                artifacts.run_owned([sys.executable, "-c", code], cwd=self.repo,
                                    env=dict(os.environ), timeout=timeout, maximum=maximum)


if __name__ == "__main__":
    unittest.main()

"""Generic-only lifecycle build receipts with strict shared controls; no compiler execution."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools.optimization_backend_revision import builds
from tools.optimization_evidence.artifacts import Artifacts
from tools.optimization_revision_runner import backend, budget_build
from tools.tests.test_optimization_budget_evidence import Fixture


class BudgetBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))
        identity = self.fixture.suite["identity"]
        values = copy.deepcopy(identity["builds"])
        for label, value in values.items():
            for prefix in budget_build.CONTROLS:
                if prefix == "Cargo.lock":
                    continue
                name = prefix if Path(prefix).suffix else prefix + "/neutral.rs"
                value["inputs"][name] = self.fixture.write(f"builds/{label}/source/{name}", prefix.encode())
            if label == "harness":
                value.pop("executables")
                value["component"] = self.fixture.write("generic/generic-capsule.wasm", b"\0asm\r\0\1\0")
                value["command"] = budget_build.GENERIC_COMMAND
            else:
                value["executables"] = {"backend": value["executables"]["server"]}
                value["command"] = ["/bin/bash", "-eu", "-o", "pipefail", "-c", backend.RECIPE]
        self.value = {"schema": budget_build.SCHEMA, "requested_refs": self.fixture.suite["requested_refs"],
                      "build": copy.deepcopy(identity["build"]), "builds": {key: values[key] for key in ("control", "candidate")},
                      "harness": values["harness"], "cleanup": {"owned_worktree_removed": True}}
        self.value["build"]["overrides"]["collector_surface"] = "libtest"

    def artifacts(self):
        binaries = {value["executables"]["backend"]["path"] for value in self.value["builds"].values()}
        return Artifacts(self.fixture.root, list(self.fixture.refs.values()), binaries)

    def test_generic_receipt_reuses_strict_build_graph_without_echo(self):
        self.assertEqual(builds.validate_budget(self.value, self.artifacts(), "smoke"), self.value)
        self.assertNotIn("echo", self.value["harness"])
        with self.assertRaisesRegex(ValueError, "build-schema"):
            builds.validate(self.value, self.artifacts(), "smoke")

    def test_rehashed_crossed_common_cpu_or_source_is_rejected(self):
        key = backend.COLD_CONTROLS[0]
        row = self.value["builds"]["candidate"]["inputs"][key]
        self.value["builds"]["candidate"]["inputs"][key] = self.fixture.write(row["path"], b"different CPU observer")
        with self.assertRaisesRegex(ValueError, "inputs-or-paths"):
            builds.validate_budget(self.value, self.artifacts(), "smoke")

    def test_legacy_echo_recipe_and_unreclaimed_build_cannot_qualify(self):
        self.value["harness"]["command"] = ["/usr/bin/python3", "tools/build_echo_capsule.py", "--verify-reproducible"]
        with self.assertRaisesRegex(ValueError, "generic-build-command"):
            builds.validate_budget(self.value, self.artifacts(), "smoke")
        self.value["harness"]["command"] = budget_build.GENERIC_COMMAND
        self.value["cleanup"]["owned_worktree_removed"] = False
        with self.assertRaisesRegex(ValueError, "worktree-not-removed"):
            builds.validate_budget(self.value, self.artifacts(), "smoke")


if __name__ == "__main__":
    unittest.main()

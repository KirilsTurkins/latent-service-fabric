"""Whole-suite replay over the real parser with tiny synthetic raw observations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from tools.tests.test_optimization_revision_evidence import Fixture as ExternalFixture
from tools.tests.phase1_paired_fixtures import candidate
from tools.optimization_evidence.common import canonical, sha256
from tools.optimization_revision_runner.backend import CONTROLS, RECIPE
from tools.optimization_backend_revision import validate_suite
from tools.optimization_backend_revision import model


class Fixture(ExternalFixture):
    def __init__(self, root):
        super().__init__(root)
        original = self.suite
        built = copy.deepcopy(original["identity"]["builds"])
        for label, build in built.items():
            build.pop("component", None)
            for prefix in CONTROLS:
                name = prefix if Path(prefix).suffix else prefix + "/proof.rs"
                build["inputs"][name] = self.write(f"builds/{label}/source/{name}", prefix.encode())
            if label == "harness":
                build.pop("executables")
                build["command"] = ["/usr/bin/python3", "tools/build_echo_capsule.py", "--verify-reproducible"]
            else:
                build["executables"] = {"backend": build["executables"]["server"]}
                build["command"] = ["/bin/bash", "-eu", "-o", "pipefail", "-c", RECIPE]
        component = self.write("echo/echo-capsule.wasm", b"candidate")
        capsule = {"component": {"digest": component["sha256"]}}
        deployment = {"spec": {"release": component["sha256"]}}
        built["harness"]["echo"] = {"component": component, "capsule": self.write("echo/capsule.json", capsule),
                                     "deployment": self.write("echo/deployment.json", deployment),
                                     "contracts": self.write("echo/contracts.json", {"format_version": 1}),
                                     "build": self.write("echo/build.json", {"synthetic": True})}
        receipt = {"schema": "latent.optimization.backend-builds.v1", "requested_refs": original["requested_refs"],
                   "build": copy.deepcopy(original["identity"]["build"]), "builds": {key: built[key] for key in ("control", "candidate")},
                   "harness": built["harness"], "cleanup": {"owned_worktree_removed": True}}
        receipt["build"]["overrides"]["collector_surface"] = "libtest"
        self.suite = {"schema": "latent.optimization.backend-revision-suite.v1", "profile": "smoke", "plan": model.plan("smoke"),
                      "builds": self.write("backend-builds.json", receipt), "runner_source": original["identity"]["runner_source"],
                      "runner_source_after": original["identity"]["runner_source"], "status": "passed", "reason": None,
                      "elapsed_nanos": "2000000000", "runs": [], "artifacts": []}
        host = original["identity"]["environment"]
        for index, variant in enumerate(("control", "candidate")):
            prefix = f"runs/pair-01-{variant}/"
            supplied = model.identity(receipt, variant, host)
            limits = {"cpuFuel": 10_000_000_000, "memoryBytes": 16_777_216, "logBytes": 16384, "wallTimeLimitMillis": None}
            docs = {"capsule": {"metadata": {"tenant": "examples", "name": "measurement-echo"},
                                 "component": {"digest": component["sha256"]}, "exports": ["examples:echo/api@0.1.0"],
                                 "execution": {"limits": limits}},
                    "deployment": {"metadata": {"tenant": "examples", "name": "measurement-echo"},
                                   "spec": {"service": "measurement-echo", "release": component["sha256"], "resources": limits}},
                    "contracts": {"format_version": 1, "contracts": [{"interfaces": [{"id": "examples:echo/api@0.1.0"}]}]}}
            metadata = {}
            for name, value in docs.items():
                reference = self.write(prefix + "echo-" + name + ".json", value)
                metadata[name] = dict(reference, path="echo-" + name + ".json")
            raw = candidate(self.suite["plan"], supplied, metadata)
            raw.update(schema="latent.optimization.backend-revision-arm.v1", arm="lsf",
                       warmup_method="first-rpc-empty-cache-in-declared-warmup")
            for name in ("preparation_elapsed_micros", "preparation_cache_after", "prepared_release_elapsed_micros"):
                raw.pop(name)
            final = raw.pop("after_release")
            owner = self.owner("artifact-identity-helper", supplied["binary"]["sha256"])
            for ordinal, sample in enumerate(raw["samples"]):
                sample["post_call"]["inventory"]["cacheSummary"]["hits"] = str(ordinal)
            final["inventory"]["cacheSummary"] = copy.deepcopy(raw["samples"][-1]["post_call"]["inventory"]["cacheSummary"])
            raw["before_shutdown"] = final
            for sample in [*[row["post_call"] for row in raw["samples"]], final]:
                sample["resources"]["identity"] = {"processId": owner["process_id"], "startTimeTicks": owner["start_time_ticks"]}
                sample["resources"]["process"]["processId"] = owner["process_id"]
            binary = receipt["builds"][variant]["executables"]["backend"]
            self.suite["runs"].append({"repetition": 1, "variant": variant, "status": "passed", "reason": None,
                "command": ["/retained/" + binary["path"], "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
                "started_micros": str(index * 1000000), "finished_micros": str((index + 1) * 1000000),
                "identity": self.write(prefix + "identity.json", supplied), "plan": self.write(prefix + "plan.json", self.suite["plan"]),
                "raw": self.write(prefix + "candidate.json", raw), "process": self.write(prefix + "process.json", owner),
                "log": self.write(prefix + "log.txt", b"synthetic\n"), "cleanup": self.write(prefix + "parent-cleanup.json", {"removed": True}),
                "host_before": host, "host_after": host, "cgroup_before": self.cgroups(), "cgroup_after": self.cgroups()})
        self.save()


class BackendSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))
        self.path = self.fixture.root / "suite.json"

    def test_complete_smoke_is_still_incomplete_evidence(self):
        value = validate_suite(self.path)
        self.assertEqual((value["status"], value["validated_calls"]), ("incomplete", "12"))
        self.assertTrue(value["population_complete"])
        self.assertEqual(len(value["pairs"]), 1)
        self.assertEqual(value, validate_suite(self.path))

    def test_rehashed_crossed_probe_pid_is_rejected(self):
        row = self.fixture.suite["runs"][0]["raw"]
        raw = json.loads((self.fixture.root / row["path"]).read_bytes())
        for sample in [*[value["post_call"] for value in raw["samples"]], raw["before_shutdown"]]:
            sample["resources"]["identity"]["processId"] += 1
            sample["resources"]["process"]["processId"] += 1
        self.fixture.replace(row, raw)
        with self.assertRaisesRegex(ValueError, "not-supervised"):
            validate_suite(self.path)

    def test_rehashed_unobserved_warmup_cannot_be_hidden(self):
        row = self.fixture.suite["runs"][0]["raw"]
        raw = json.loads((self.fixture.root / row["path"]).read_bytes())
        raw["samples"].pop(0)
        self.fixture.replace(row, raw)
        with self.assertRaisesRegex(ValueError, "sample-count"):
            validate_suite(self.path)

    def test_failed_arm_and_partial_population_stay_failed(self):
        self.fixture.suite.update(status="failed", reason="collection-failed")
        self.fixture.suite["runs"][1].update(status="failed", reason="collector-failed")
        self.fixture.save()
        result = validate_suite(self.path)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["validated_calls"], "6")
        self.assertFalse(result["attempt_count_complete"])

    def test_missing_pair_and_changed_command_are_rejected(self):
        self.fixture.suite["runs"].pop()
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "missing-arm"):
            validate_suite(self.path)

    def test_historical_collector_name_is_not_a_valid_revision_method(self):
        self.fixture.suite["runs"][0]["command"][2] = "standalone::measurements::comparison::phase1_comparison_collector"
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "collector-command"):
            validate_suite(self.path)


if __name__ == "__main__":
    unittest.main()

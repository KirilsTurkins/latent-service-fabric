"""Small synthetic replay/tamper proofs; no processes, guests or builds."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from tools.tests.test_optimization_evidence import Fixture as ClientFixture
from tools.optimization_evidence.common import EvidenceError, canonical, sha256
from tools.optimization_runner import fixtures
from tools.optimization_evidence.suite import ZERO_SHUTDOWN
from tools.optimization_revision_runner.model import CONTROL, HARNESS_COMMAND, SERVER_RECIPE, SOURCE_CONTROLS, plan, run_id
from tools.optimization_revision_evidence import validate_suite
from tools.optimization_revision_evidence.suite import comparisons


class Fixture(ClientFixture):
    def __init__(self, root):
        self.root, self.refs, self.pid, self.prefix, self.variant = root, {}, 1000, "", "control"
        self.mapping = {}
        selected = plan("smoke")
        source = lambda commit: {"commit": commit, "tree": "b" * 40, "clean": True, "cargo_lock_sha256": sha256(b"lock")}
        refs = {"control": CONTROL, "candidate": "c" * 40, "harness": "d" * 40}
        builds = {}
        for label in refs:
            inputs = {"Cargo.lock": self.write(f"builds/{label}/source/Cargo.lock", b"lock")}
            for name in SOURCE_CONTROLS:
                key = name if Path(name).suffix else name + "/proof.rs"
                data = (ROOT / name).read_bytes() if name.endswith(".json") else name.encode()
                inputs[key] = self.write(f"builds/{label}/source/{key}", data)
            executables = {name: self.write(f"builds/{label}/{name}", (label + name).encode())
                           for name in (("client", "cli") if label == "harness" else ("server",))}
            builds[label] = {"source": source(refs[label]), "source_after": source(refs[label]), "inputs": inputs,
                             "executables": executables, "source_path": "/owned/source", "target_path": "/owned/target",
                             "command": HARNESS_COMMAND if label == "harness" else ["/bin/bash", "-eu", "-o", "pipefail", "-c", SERVER_RECIPE],
                             "process": self.owner("artifact-identity-helper", sha256(b"bash")),
                             "log": self.write(f"builds/{label}/build.log", b"build fixture\n")}
            self.write(f"builds/{label}/build.log.process.json", builds[label]["process"])
        component = self.write("builds/harness/base.wasm", b"\0asm\r\0\1\0")
        builds["harness"]["component"] = component
        packages = fixtures.materialize(root / component["path"], root / "fixtures")
        publications = [{name: self.register(path) for name, path in package.items()} for package in packages]
        options = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo", "opt_level": "3", "debug": "1",
                   "codegen_units": "16", "lto": "false", "debug_assertions": "false", "overflow_checks": "false",
                   "incremental": "false", "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
                   "linker_build_id": "sha1", "promoted_locals": "source-filename",
                   "collector_surface": "separate-standalone-server-and-load-client",
                   "recipe_sha256": builds["control"]["inputs"]["tools/phase0_build_environment.sh"]["sha256"]}
        host = {"os": "Linux", "arch": "x86_64", "kernel": "synthetic", "cpu_model": "synthetic",
                "logical_cpus": "4", "memory_total_bytes": "1000000", "virtualization": {}, "allocator": {},
                "cpu_policy": {}, "load_before": [0, 0, 0]}
        proof_names = ("tools/run_optimization_revision_benchmarks.py", "tools/run_optimization_benchmarks.py",
                       "tools/optimization_revision_runner/model.py", "tools/optimization_revision_evidence/suite.py",
                       "tools/optimization_evidence/client.py", "tools/optimization_runner/fixtures.py")
        self.suite = {"schema": "latent.optimization.revision-suite.v1", "profile": "smoke", "plan": selected,
                      "requested_refs": refs, "status": "passed", "reason": None, "elapsed_nanos": "30000000000",
                      "measurement_elapsed_nanos": "20000000000", "cleanup": {"owned_worktree_removed": True},
                      "identity": {"runner_source": source(refs["harness"]), "runner_source_after": source(refs["harness"]),
                                   "build": {"profile": "release", "rustc": "rustc fixture", "cargo": "cargo fixture",
                                             "wasmtime": "47.0.3", "target": "x86_64-unknown-linux-gnu", "overrides": options},
                                   "builds": builds, "components": [package["component"] for package in publications],
                                   "publications": publications, "environment": host, "cgroup": self.cgroups(),
                                   "harness_sources": {name: self.write("harness-source/" + name, name.encode()) for name in proof_names}},
                      "runs": [], "artifacts": []}
        stopped = {"schemaVersion": "latent.standalone.status.v1", "event": "stopped", "clean": True,
                   "report": {**dict.fromkeys(ZERO_SHUTDOWN, 0), "clean": True, "telemetryFlushed": True,
                              "epochHelperJoined": True, "quarantinedCells": 0, "telemetryRetainedEntries": 2}}
        for index, variant in enumerate(("control", "candidate")):
            self.variant, self.prefix = variant, variant + "/"
            server = self.owner("lsf-server", builds[variant]["executables"]["server"]["sha256"])
            batches, clients = [], []
            for ordinal, case in enumerate(selected["cases"]):
                owner = self.owner("load-client", builds["harness"]["executables"]["client"]["sha256"])
                clients.append(owner)
                self.mapping = {f"lsf-{case['id']}": run_id(1, variant, case["id"])}
                batch = self.batch("lsf", case, server, owner, self.suite["identity"]["components"])
                before = self.write(case["id"] + "-before.json", self.inventory(ordinal * 100, ordinal * 20))
                after = self.write(case["id"] + "-after.json", self.inventory(ordinal * 100 + 20, ordinal * 20 + 10))
                batch["cache_observation"] = self.write(case["id"] + "-cache.json", {
                    "server_process_id": server["process_id"], "start_time_ticks": server["start_time_ticks"],
                    "endpoint": "http://127.0.0.1:5000",
                    "interval": "before-warmup-through-after-measured-includes-node-get-observation",
                    "started_micros": str(index * 10_000_000 + ordinal * 10000 + 1000),
                    "finished_micros": str(index * 10_000_000 + ordinal * 10000 + 9000), "before": before, "after": after})
                batches.append(batch)
            self.mapping = {}
            self.write("seed-cleanup.json", {"server": self.owner("lsf-seed", builds[variant]["executables"]["server"]["sha256"]),
                                             "server_shutdown": stopped})
            self.suite["runs"].append({"repetition": 1, "variant": variant, "arm": "lsf", "scenario": "cold-restart",
                                      "status": "passed", "reason": None, "data_removed": True,
                                      "started_micros": str(index * 10_000_000), "finished_micros": str((index + 1) * 10_000_000),
                                      "batches": batches, "server_process": self.write("server.json", server),
                                      "configuration": self.write("config.json", self.config("lsf")),
                                      "cleanup": self.write("cleanup.json", {"server": server, "clients": clients, "server_shutdown": stopped}),
                                      "environment_before": host, "environment_after": host,
                                      "lifecycle": {"process_start_to_ready_micros": "100", "process_start_to_first_response_observed_micros": "200",
                                                    "ready_to_first_response_observed_micros": "100",
                                                    "first_response_observation": "parent-received-client-event-upper-bound-includes-client-startup-and-connect",
                                                    "initial_preparation": "included-in-first-call"}})
        self.prefix = ""
        self.save()

    def write(self, name, value):
        data = value if isinstance(value, bytes) else canonical(value) + b"\n"
        for old, new in self.mapping.items():
            data = data.replace(old.encode(), new.encode())
        return super().write(self.prefix + name, data)

    def register(self, path):
        return self.write(path.relative_to(self.root).as_posix(), path.read_bytes())

    @staticmethod
    def cgroups():
        return {"scope": "runner-cgroup-shared", "process_membership": "", "resolution": {
            "status": "unsupported", **dict.fromkeys(("path", "mount_id", "mount_root", "mount_point", "device", "inode"))},
                "errors": {"resolution": "unavailable"}, **dict.fromkeys(("cpu.max", "cpu.stat", "memory.max", "memory.current",
                                                                          "memory.stat", "memory.events", "cpu.pressure", "memory.pressure", "io.pressure"))}

    @staticmethod
    def inventory(hits, misses):
        cache = {name: "0" for name in ("entries maximumEntries sourceBytes maximumSourceBytes metadataBytes maximumMetadataBytes "
                 "compiledImageBytes maximumCompiledImageBytes preparing maximumConcurrentPreparations preparingSourceBytes "
                 "preparingMetadataBytes hits misses evictions invalidations").split()}
        cache.update(available=True, maximumEntries="4", entries="4", hits=str(hits), misses=str(misses))
        return {"schemaVersion": "latent.cli.result.v1", "command": "node get", "category": "success", "error": None,
                "requestDispatched": True, "outcomeKnown": True, "data": {"inventory": {
                    "node": {"id": "optimization-node", "endpoint": "127.0.0.1:5000"}, "cacheSummary": cache,
                    "queueDepth": "0", "cellCapacity": [{"total": 4, "active": 0, "queueDepth": 0}]}}}


class RevisionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))
        self.path = self.fixture.root / "suite.json"

    def test_smoke_replays_every_offer_and_remains_incomplete(self):
        value = validate_suite(self.path)
        self.assertEqual((value["status"], value["validated_attempts"], value["validated_processes"]), ("incomplete", "314", "22"))
        self.assertTrue(value["population_complete"])
        self.assertEqual(value, validate_suite(self.path))

    def test_missing_pair_cannot_be_claimed_complete(self):
        self.fixture.suite["runs"].pop()
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "missing-pair"):
            validate_suite(self.path)

    def test_changed_focused_population_is_rejected(self):
        self.fixture.suite["plan"]["cases"].pop()
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, "population"):
            validate_suite(self.path)

    def test_common_client_source_cannot_differ_after_rehash(self):
        row = self.fixture.suite["identity"]["builds"]["candidate"]["inputs"]["tools/optimization-bench/src/client/proof.rs"]
        self.fixture.replace(row, b"changed client")
        with self.assertRaisesRegex(ValueError, "shared-sources"):
            validate_suite(self.path)

    def test_crossed_server_binary_is_rejected(self):
        row = self.fixture.suite["runs"][1]["server_process"]
        value = json.loads((self.fixture.root / row["path"]).read_bytes())
        value["executable_sha256"] = self.fixture.suite["identity"]["builds"]["control"]["executables"]["server"]["sha256"]
        self.fixture.replace(row, value)
        with self.assertRaisesRegex(ValueError, "executable"):
            validate_suite(self.path)

    def test_rehashed_mixed_cache_without_hits_is_rejected(self):
        batch = self.fixture.suite["runs"][0]["batches"][-1]
        witness = json.loads((self.fixture.root / batch["cache_observation"]["path"]).read_bytes())
        before = json.loads((self.fixture.root / witness["before"]["path"]).read_bytes())
        after = json.loads((self.fixture.root / witness["after"]["path"]).read_bytes())
        after["data"]["inventory"]["cacheSummary"]["hits"] = before["data"]["inventory"]["cacheSummary"]["hits"]
        self.fixture.replace(witness["after"], after)
        # Update the retained nested witness reference too, as a malicious producer could.
        witness["after"] = self.fixture.refs[witness["after"]["path"]]
        self.fixture.replace(batch["cache_observation"], witness)
        with self.assertRaisesRegex(ValueError, "mixed-cache"):
            validate_suite(self.path)

    def test_raw_tamper_and_duplicate_owner_are_rejected(self):
        row = self.fixture.suite["runs"][0]["batches"][0]["attempts"]
        with (self.fixture.root / row["path"]).open("ab") as destination:
            destination.write(b" ")
        with self.assertRaises(ValueError):
            validate_suite(self.path)

    def test_failed_run_remains_failed_and_population_count_unknown(self):
        self.fixture.suite.update(status="failed", reason="collection-failed")
        self.fixture.suite["runs"][1].update(status="failed", reason="collector-failed")
        self.fixture.save()
        value = validate_suite(self.path)
        self.assertEqual(value["status"], "failed")
        self.assertFalse(value["attempt_count_complete"])
        self.assertFalse(value["population_complete"])

    def test_full_population_is_fixed_and_existing_presets_unchanged(self):
        full = plan("full")
        total = sum(item["client_plan"]["warmup_attempts"] + item["client_plan"]["measured_attempts"] for item in full["cases"])
        self.assertEqual(total * full["repetitions"] * 2, 46130)
        from tools.optimization_runner.plans import cases
        self.assertEqual(len(cases("full")), 16)


if __name__ == "__main__":
    unittest.main()

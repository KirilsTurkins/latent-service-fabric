"""Tiny retained artifacts test identity and measurement tamper rejection.

No executable is launched. Population tests stub unrelated acquisition replay;
the source, event, and resource tests exercise their real validators separately.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import identity, runs
from tools.artifact_identity_evidence import suite as evidence_suite
from tools.artifact_identity_evidence.common import Artifacts, canonical, folded, sha256
from tools.artifact_identity_runner.model import BUILD_RECIPE, PROBE, PROBE_DIRECTORY, plan


def owner(pid=101, role="artifact-identity-helper", checksum=None):
    return {"process_id": pid, "start_time_ticks": "100", "role": role,
            "executable_sha256": checksum or sha256(b"helper"),
            "reaped": True, "output_closed": True, "exit_code": 0}


def unavailable_cgroup():
    value = {name: None for name in (
        "cpu.max", "cpu.stat", "memory.max", "memory.current", "memory.stat",
        "memory.events", "cpu.pressure", "memory.pressure", "io.pressure")}
    value.update(scope="runner-cgroup-shared", process_membership="",
                 errors={"resolution": "unavailable"},
                 resolution={"status": "unsupported", "path": None, "mount_id": None,
                             "mount_root": None, "mount_point": None, "device": None, "inode": None})
    return value


def snapshot(pid=201):
    return {"process_id": pid, "start_time_ticks": "100", "rss_bytes": "4096",
            "cpu_user_ticks": "2", "cpu_system_ticks": "1", "threads": 1, "fd_count": 3,
            "read_bytes": "0", "write_bytes": "0"}


def resource_record(mode="normal"):
    binary = {"path": "probe", "sha256": sha256(b"probe"), "bytes": "5"}
    tools = {"heaptrack": {"sha256": sha256(b"heaptrack")}}
    pid = 201 if mode == "normal" else 202
    process = owner(201, "identity-" + mode,
                    binary["sha256"] if mode == "normal" else tools["heaptrack"]["sha256"])
    wrapper = {name: snapshot() for name in ("before", "after", "last_live")}
    wrapper.update(peak_rss_bytes="4096", sample_interval_millis=100,
                   peak_semantics="maximum-observed-rss-not-instantaneous-peak")
    probe = {name: {**snapshot(pid), "observed_ns": observed,
                    "kernel_high_water_rss_bytes": "8192"}
             for name, observed in (("before", "1000"), ("last_live", "2000"), ("completion", "3000"))}
    probe.update(maximum_observed_rss_bytes="4096", kernel_high_water_rss_bytes="8192",
                 sample_interval_millis=100,
                 before_semantics="first-observed-after-ready-not-guaranteed-pre-operation",
                 scope="normal-probe" if mode == "normal" else "heaptrack-instrumented-probe")
    record = {"mode": mode, "process": process,
              "probe_process": {"process_id": pid, "start_time_ticks": "100",
                                "executable_sha256": binary["sha256"], "executable_device": "1",
                                "executable_inode": "2", "owned_process_group": 201,
                                "observed_exited": True, "reaped_by_runner": mode == "normal"},
              "resources": {"probe": probe, "wrapper": wrapper, "cgroup": unavailable_cgroup()}}
    return record, binary, tools


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="latent-artifact-evidence-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.refs = {}

    def retain(self, name, data):
        data = data if isinstance(data, bytes) else canonical(data)
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        ref = {"path": name, "sha256": sha256(data), "bytes": str(len(data))}
        self.refs[name] = ref
        return ref

    def artifacts(self):
        return Artifacts(self.root, list(self.refs.values()))

    def builds(self):
        suite = {"profile": "full", "requested_refs": {"control": "1" * 40, "candidate": "2" * 40},
                 "builds": {}}
        names = ("Cargo.lock", "Cargo.toml", ".cargo/config.toml", "rust-toolchain.toml",
                 "tools/phase0_build_environment.sh", "tools/optimization-bench/Cargo.toml")
        for index, arm in enumerate(("control", "candidate")):
            prefix = f"builds/{arm}/"
            source = {"commit": suite["requested_refs"][arm], "tree": str(index + 3) * 40, "clean": True}
            process = owner(101 + index)
            log = self.retain(prefix + "build.log", b"")
            self.retain(log["path"] + ".process.json", process)
            suite["builds"][arm] = {
                "source_before": source, "source_after": deepcopy(source),
                "binary": self.retain(prefix + "artifact-identity-probe", arm.encode()),
                "inputs": {name: self.retain(prefix + "source/" + name, name.encode()) for name in names},
                "probe_sources": {name: self.retain(prefix + "source/" + name, b"same probe module")
                                  for name in (PROBE, PROBE_DIRECTORY + "/model.rs")},
                "command": ["/bin/bash", "-eu", "-o", "pipefail", "-c", BUILD_RECIPE],
                "log": log, "process": process, "source_path": "/private/source", "target_path": "/private/target",
            }
        return suite

    def event_fixture(self, operation="catalog-open"):
        fixture = {"component_digest": sha256(b"component"), "component_bytes": "9",
                   "route_generation": "1", "revision_id": "revision-owned"}
        record = {"operation": operation, "size": "small", "probe_process": {"process_id": 201}}
        common = {"operation": operation, "boundary": runs.BOUNDARIES[operation], "process_id": 201,
                  "size": "small", "component_digest": fixture["component_digest"],
                  "component_bytes": "9", "operation_count": "1"}
        ready = {**common, "schema": "latent.artifact-identity.ready.v1", "event": "ready",
                 "observation_hold_millis": 100}
        result = {**common, "schema": "latent.artifact-identity.result.v1", "event": "measurement-complete",
                  "elapsed_nanos": "100", "outcome": "passed", "code": None,
                  "release_count": None if operation == "hash" else "1",
                  "deployment_count": "1" if operation == "catalog-open" else None,
                  "route_count": "2" if operation == "catalog-open" else None,
                  "route_generation": "1" if operation == "catalog-open" else None,
                  "revision_id": "revision-owned" if operation == "catalog-open" else None}
        self.retain_events(record, ready, result)
        return record, fixture, ready, result

    def retain_events(self, record, ready, result):
        record["ready"] = self.retain("ready.json", ready)
        record["result"] = self.retain("result.json", result)
        record["log"] = self.retain("probe.log", canonical(ready) + b"\n" + canonical(result) + b"\n")

    def fixture_suite(self):
        suite = self.builds()
        suite["plan"] = plan("smoke")
        component = self.retain("inputs/component.wasm", b"component")
        for name in ("capsule", "contracts"):
            self.retain(f"inputs/{name}.json", {})
        files = {"component.wasm": self.retain("fixtures/small/component.wasm", b"component")}
        for name in ("capsule.json", "contracts.json", "deployment.json", "catalog/COMPLETE",
                     "catalog/metadata", "deployments/catalog.json"):
            files[name] = self.retain("fixtures/small/" + name, {})
        manifest = {"schema": "latent.artifact-identity.fixture.v1", "size": "small",
                    "component_digest": component["sha256"], "component_bytes": component["bytes"],
                    "source_component_digest": component["sha256"], "source_component_bytes": component["bytes"],
                    **{name + "_sha256": files[name + ".json"]["sha256"]
                       for name in ("capsule", "contracts", "deployment")},
                    "tenant": "tests", "service": "tests/service", "deployment_id": "one",
                    "contract": "tests:fixture/api@0.1.0", "function": "echo", "revision_id": "revision",
                    "route_generation": "1", "configuration": deepcopy(identity.CONFIGURATION)}
        files["fixture.json"] = self.retain("fixtures/small/fixture.json", manifest)
        process = owner(301, checksum=suite["builds"]["control"]["binary"]["sha256"])
        log = self.retain("fixtures/small-generation.log", b"")
        self.retain(log["path"] + ".process.json", process)
        suite["fixtures"] = {"small": {
            "root": "fixtures/small", "manifest": manifest, "files": files,
            "generation_process": process, "generation_log": log,
            "command": ["/evidence/" + suite["builds"]["control"]["binary"]["path"], "fixture",
                        "--component", "/evidence/inputs/component.wasm", "--capsule", "/evidence/inputs/capsule.json",
                        "--contracts", "/evidence/inputs/contracts.json", "--output", "/evidence/fixtures/small",
                        "--size", "small"],
        }}
        return suite

    def allocation_fixture(self):
        # Compressed input is provenance only in this focused test. Semantic
        # replay reads the retained interpreted stream without launching zstd.
        tools = {name: {"sha256": sha256(name.encode())} for name in ("heaptrack_print", "zstd")}
        refs = {"raw": self.retain("trace.zst", b"opaque compressed fixture"),
                "report": self.retain("report.txt", b"human rounded report"),
                "interpreted": self.retain("interpreted.heaptrack",
                    b"v 10400 3\nX /probe measure\nI 1000 1000\na 10 0\n+ 0\n+ 0\n- 0\nc 1\n# strings: 0\n# ips: 0\n"),
                "allocations": self.retain("allocations.folded", b"root 2\n"),
                "peak": self.retain("peak.folded", b"root 32\n")}
        for index, name in enumerate(("report", "interpreted", "allocations", "peak")):
            log = refs[name] if name in ("report", "interpreted") else self.retain(name + ".log", b"")
            tool = "zstd" if name == "interpreted" else "heaptrack_print"
            self.retain(log["path"] + ".process.json", owner(400 + index, checksum=tools[tool]["sha256"]))
        record = {"profile_refs": refs, "command": ["heaptrack", "--output", "/out", "/probe", "measure"]}
        return record, {"tools": tools}

    def test_clean_distinct_sources_with_identical_harness_are_accepted(self):
        suite = self.builds()
        identity.build_rows(suite, self.artifacts())

    def test_build_source_change_and_crossed_requested_ref_are_rejected(self):
        for mutation in ("source_after", "requested_ref", "dirty"):
            with self.subTest(mutation=mutation):
                suite = self.builds()
                if mutation == "source_after":
                    suite["builds"]["candidate"]["source_after"]["tree"] = "f" * 40
                elif mutation == "requested_ref":
                    suite["requested_refs"]["candidate"] = "f" * 40
                else:
                    suite["builds"]["candidate"]["source_before"]["clean"] = False
                with self.assertRaises(ValueError):
                    identity.build_rows(suite, self.artifacts())

    def test_rehashed_harness_or_build_control_changes_are_rejected(self):
        for category, name, reason in (
            ("probe_sources", PROBE_DIRECTORY + "/model.rs", "mismatched-measurement-harness"),
            ("inputs", ".cargo/config.toml", "mismatched-build-control"),
        ):
            with self.subTest(category=category):
                suite = self.builds()
                row = suite["builds"]["candidate"][category][name]
                suite["builds"]["candidate"][category][name] = self.retain(row["path"], b"changed bytes")
                with self.assertRaisesRegex(ValueError, reason):
                    identity.build_rows(suite, self.artifacts())

    def test_source_paths_recipe_and_retained_helper_receipt_must_match(self):
        for mutation in ("path", "recipe", "receipt"):
            with self.subTest(mutation=mutation):
                suite = self.builds()
                build = suite["builds"]["candidate"]
                if mutation == "path":
                    build["source_path"] = "/different/source"
                elif mutation == "recipe":
                    build["command"][-1] += " --features different"
                else:
                    build["process"]["process_id"] += 1
                with self.assertRaises(ValueError):
                    identity.build_rows(suite, self.artifacts())

    def test_omitting_same_retained_probe_module_from_both_arms_is_rejected(self):
        suite = self.builds()
        for arm in ("control", "candidate"):
            del suite["builds"][arm]["probe_sources"][PROBE_DIRECTORY + "/model.rs"]
        with self.assertRaisesRegex(ValueError, "omitted-probe-source-artifact"):
            identity.build_rows(suite, self.artifacts())

    def test_fixture_generation_inputs_and_fixed_configuration_are_bound(self):
        suite = self.fixture_suite()
        identity.fixtures(suite, self.artifacts())
        for mutation in ("configuration", "input", "output", "binary"):
            with self.subTest(mutation=mutation):
                suite = self.fixture_suite()
                item = suite["fixtures"]["small"]
                if mutation == "configuration":
                    item["manifest"]["configuration"]["artifacts"]["max_component_bytes"] = 1
                    item["files"]["fixture.json"] = self.retain("fixtures/small/fixture.json", item["manifest"])
                elif mutation == "input":
                    item["command"][3] = "/evidence/inputs/foreign-component.wasm"
                elif mutation == "output":
                    item["command"][9] = "/evidence/fixtures/foreign"
                else:
                    item["command"][0] = "/evidence/" + suite["builds"]["candidate"]["binary"]["path"]
                with self.assertRaisesRegex(ValueError, "changed-fixture-configuration|changed-fixture-command|invalid-fixture-command"):
                    identity.fixtures(suite, self.artifacts())

    def test_success_events_roundtrip_for_all_three_boundaries(self):
        for operation in runs.BOUNDARIES:
            with self.subTest(operation=operation):
                record, fixture, _, result = self.event_fixture(operation)
                self.assertEqual(runs.events(record, fixture, self.artifacts(), 1), result)

    def test_rehashed_semantic_result_cannot_claim_foreign_revision_or_counts(self):
        for name, value in (("revision_id", "foreign-revision"), ("route_count", "1"),
                            ("deployment_count", "2"), ("route_generation", "2")):
            with self.subTest(name=name):
                record, fixture, ready, result = self.event_fixture()
                result[name] = value
                self.retain_events(record, ready, result)
                with self.assertRaisesRegex(ValueError, "probe-semantic-oracle-mismatch"):
                    runs.events(record, fixture, self.artifacts(), 1)

    def test_rehashed_crossed_event_identity_is_rejected(self):
        for name, value in (("process_id", 202), ("component_digest", sha256(b"other")),
                            ("operation_count", "2"), ("boundary", "different-timing-boundary")):
            with self.subTest(name=name):
                record, fixture, ready, result = self.event_fixture()
                ready[name] = result[name] = value
                self.retain_events(record, ready, result)
                with self.assertRaisesRegex(ValueError, "crossed-probe-event"):
                    runs.events(record, fixture, self.artifacts(), 1)

    def test_result_json_must_match_original_raw_log(self):
        record, fixture, _, result = self.event_fixture()
        result["elapsed_nanos"] = "1"
        record["result"] = self.retain("result.json", result)
        with self.assertRaisesRegex(ValueError, "events-unbound-to-probe-log"):
            runs.events(record, fixture, self.artifacts(), 1)

    def test_raw_log_does_not_allow_duplicate_events(self):
        record, fixture, ready, result = self.event_fixture()
        record["log"] = self.retain("probe.log", b"\n".join(map(canonical, (ready, result, result))) + b"\n")
        with self.assertRaisesRegex(ValueError, "extra-probe-event"):
            runs.events(record, fixture, self.artifacts(), 1)

    def test_normal_and_profiled_probe_ownership_are_distinct(self):
        for mode in ("normal", "allocation"):
            record, binary, tools = resource_record(mode)
            key, _ = runs.probe_resources(record, binary, tools)
            self.assertEqual(key[0], 201 if mode == "normal" else 202)
            record["probe_process"]["reaped_by_runner"] = mode != "normal"
            with self.assertRaisesRegex(ValueError, "unowned-or-crossed-probe"):
                runs.probe_resources(record, binary, tools)

    def test_resources_reject_pid_reuse_crossed_binary_and_process_group(self):
        for mutation in ("snapshot", "binary", "group", "not_exited"):
            with self.subTest(mutation=mutation):
                record, binary, tools = resource_record()
                if mutation == "snapshot":
                    record["resources"]["probe"]["completion"]["start_time_ticks"] = "101"
                elif mutation == "binary":
                    record["probe_process"]["executable_sha256"] = sha256(b"other executable")
                elif mutation == "group":
                    record["probe_process"]["owned_process_group"] += 1
                else:
                    record["probe_process"]["observed_exited"] = False
                with self.assertRaises(ValueError):
                    runs.probe_resources(record, binary, tools)

    def test_resources_reject_zero_rss_peaks_below_samples_and_backwards_time(self):
        for mutation in ("zero", "peak", "time"):
            with self.subTest(mutation=mutation):
                record, binary, tools = resource_record()
                resources = record["resources"]["probe"]
                if mutation == "zero":
                    resources["completion"]["rss_bytes"] = "0"
                elif mutation == "peak":
                    resources["maximum_observed_rss_bytes"] = "4095"
                else:
                    resources["completion"]["observed_ns"] = "999"
                with self.assertRaises(ValueError):
                    runs.probe_resources(record, binary, tools)

    def test_same_process_monotonic_resource_counters_cannot_regress(self):
        for counter in ("cpu_user_ticks", "cpu_system_ticks", "read_bytes", "write_bytes", "kernel_high_water_rss_bytes"):
            with self.subTest(counter=counter):
                record, binary, tools = resource_record()
                item = record["resources"]["probe"]
                item["before"][counter] = str(int(item["completion"][counter]) + 1)
                with self.assertRaisesRegex(ValueError, "resource-counter-regressed"):
                    runs.probe_resources(record, binary, tools)

    def test_allocation_events_must_agree_with_exact_folded_totals(self):
        record, suite = self.allocation_fixture()
        replay = runs.allocation(record, suite, self.artifacts())
        self.assertEqual((replay["allocation_count"], replay["peak_live_bytes"]), ("2", "32"))
        for field in ("allocations", "peak"):
            with self.subTest(field=field):
                record, suite = self.allocation_fixture()
                ref = record["profile_refs"][field]
                record["profile_refs"][field] = self.retain(ref["path"], b"root 1\n")
                with self.assertRaisesRegex(ValueError, "allocation-profile-totals-mismatch"):
                    runs.allocation(record, suite, self.artifacts())

    def test_allocation_command_and_decoder_identity_are_bound(self):
        for mutation in ("command", "decoder"):
            with self.subTest(mutation=mutation):
                record, suite = self.allocation_fixture()
                if mutation == "command":
                    record["command"][-1] = "different-operation"
                else:
                    path = "interpreted.heaptrack.process.json"
                    process = owner(401, checksum=sha256(b"not zstd"))
                    self.retain(path, process)
                with self.assertRaisesRegex(ValueError, "crossed-allocation-command|crossed-process-executable"):
                    runs.allocation(record, suite, self.artifacts())

    def test_folded_weights_are_exact_integers_not_rounded_report_text(self):
        ref = self.retain("allocations.folded", b"root;one 9007199254740993\nroot;two 2\n")
        self.assertEqual(folded(self.artifacts().path(ref)), {"rows": "2", "total": "9007199254740995"})
        ref = self.retain("allocations.folded", b"root 1.1M\n")
        with self.assertRaises(ValueError):
            folded(self.artifacts().path(ref))

    def test_fixed_population_has_all_operations_modes_and_alternates_pairs(self):
        smoke = evidence_suite.population("smoke")
        full = evidence_suite.population("full")
        self.assertEqual(len(smoke), 12)
        self.assertEqual(len(full), 252)
        self.assertEqual(len(set(full)), 252)
        self.assertEqual(full[:2], [(1, "control", "small", "hash", "normal"),
                                   (1, "candidate", "small", "hash", "normal")])
        self.assertEqual(full[36:38], [(2, "candidate", "small", "hash", "normal"),
                                      (2, "control", "small", "hash", "normal")])
        self.assertEqual(full[-1], (7, "candidate", "64m", "catalog-open", "allocation"))

    def test_population_gate_rejects_missing_duplicate_or_reordered_attempts(self):
        rows = [dict(zip(("pair", "arm", "size", "operation", "mode"), key))
                for key in evidence_suite.population("smoke")]
        suite = {"schema": "latent.artifact-identity.suite.v1", "profile": "smoke", "plan": plan("smoke"),
                 "requested_refs": {}, "status": "passed", "reason": None, "elapsed_nanos": "100",
                 "environment": {}, "tools": {}, "builds": {arm: {"source_before": {}} for arm in ("control", "candidate")},
                 "fixtures": {}, "runs": rows, "artifacts": [self.retain("unrelated.txt", b"retained")],
                 "cleanup": {"owned_worktree_removed": True}}
        path = self.root / "suite.json"
        with patch.object(evidence_suite, "environment"), patch.object(evidence_suite, "build_rows"), \
                patch.object(evidence_suite, "fixtures", return_value={}), \
                patch.object(evidence_suite, "run") as replay:
            replay.side_effect = [((300 + index, "100"), {"test_metric": 1}) for index in range(12)]
            path.write_bytes(canonical(suite))
            self.assertEqual(evidence_suite.validate_suite(path)["validated_runs"], "12")
            for mutation in ("missing", "duplicate", "order"):
                with self.subTest(mutation=mutation):
                    changed = deepcopy(suite)
                    if mutation == "missing":
                        changed["runs"].pop()
                    elif mutation == "duplicate":
                        changed["runs"][1] = changed["runs"][0]
                    else:
                        changed["runs"][0], changed["runs"][1] = changed["runs"][1], changed["runs"][0]
                    replay.side_effect = [((300 + index, "100"), {"test_metric": 1}) for index in range(12)]
                    path.write_bytes(canonical(changed))
                    with self.assertRaisesRegex(ValueError, "incomplete-run-population|changed-run-order-or-population"):
                        evidence_suite.validate_suite(path)


if __name__ == "__main__":
    unittest.main()

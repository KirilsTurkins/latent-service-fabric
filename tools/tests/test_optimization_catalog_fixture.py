"""Actual dirty debug graphs: protocol regressions, never release qualification."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.catalog import fixtures, model, parse, policy, sampler
from tools.optimization_evidence.common import EvidenceError, sha256

ROOT = Path(__file__).parent / "fixtures/catalog_diagnostic"


def loaded():
    manifest = json.loads((ROOT / "manifest.json").read_bytes())
    result = {}
    for row in manifest["files"]:
        body = (ROOT / row["path"]).read_bytes()
        if row["gzip"]:
            body = gzip.decompress(body)
        if sha256(body) != row["original_sha256"] or str(len(body)) != row["original_bytes"]:
            raise AssertionError("original diagnostic bytes changed")
        result[row["original_path"]] = body
    return result


def replay(value, fixture):
    if value["identity"].get("qualifying") is not False:
        raise AssertionError("diagnostic qualification changed")
    if value["fixture_template"] != fixture.template():
        raise AssertionError("actual fixture template crossed")
    policy.owners(value["configured_runtimes"], value["runtime_threads_after_join"], value["catalog_owners_released"])
    selected = value["plan"]
    state = parse.Replay(value, selected, value["identity"], fixture)
    mode = selected["mode"]
    if mode == "reopen":
        state.reopen(16)
    else:
        state.checkpoint("empty", 0)
        previous = 0
        for count in ([16] if mode == "allocation" else model.scales("smoke")):
            state.publish(previous, count)
            state.checkpoint("artifact-only", count)
            state.apply(previous, count)
            state.checkpoint("post-publication-idle", count)
            if mode == "allocation":
                state.allocation()
            else:
                state.normal(count)
            state.checkpoint("after-resolver-output-drop", count)
            previous = count
        if mode == "initial":
            state.update(16)
    state.checkpoint("before-shutdown", 16)
    if state.position != len(state.rows):
        raise EvidenceError("unplanned-actual-diagnostic-row")
    state.operations.complete(value["operations"], model.counts("smoke", mode))
    if value["final_verification"] != state.verification():
        raise EvidenceError("actual-diagnostic-final-verification")
    policy.compiler(value["final_compiler"], final=True)
    policy.cleanup(value["shutdown"]["cleanup"], final=True)
    return state


class ActualCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = loaded()
        read = lambda name: json.loads(cls.files["echo/" + name])
        cls.fixture = fixtures.normalize(cls.files["echo/echo-capsule.wasm"], read("capsule.json"),
                                         read("contracts.json"), read("deployment.json"))
        cls.raw = {mode: json.loads(cls.files[mode + "/catalog.json"]) for mode in ("initial", "reopen", "allocation")}

    def test_actual_initial_reopen_and_allocation_functional_graphs(self):
        for mode, commands in (("initial", 604), ("reopen", 7), ("allocation", 98)):
            with self.subTest(mode=mode):
                state = replay(deepcopy(self.raw[mode]), self.fixture)
                self.assertEqual(state.operations.commands, commands)
                self.assertEqual(state.verification()["full_fetch_attempts"], "0")

    def test_selected_revision_attributes_and_miss_reason_are_bound(self):
        for case, field in (("default-success", "attributes_digest"), ("named-success", "revision"), ("route-miss", "message")):
            value = deepcopy(self.raw["initial"])
            row = next(row for row in value["samples"] if row["kind"] == "resolve-chunk" and row["case"] == case)
            outcome = row["observations"][0]
            outcome["result" if "result" in outcome else "error"][field] = "crossed"
            with self.subTest(case=case), self.assertRaises(EvidenceError):
                replay(value, self.fixture)

    def test_old_pin_cannot_observe_updated_attributes_or_skip_policy(self):
        for remove in (False, True):
            value = deepcopy(self.raw["initial"])
            rows = value["samples"]
            if remove:
                rows[:] = [row for row in rows if row.get("label") != "update-new-policy"]
            else:
                old = next(row for row in rows if row.get("label") == "update-old-resolve-after")
                new = next(row for row in rows if row.get("label") == "update-new-resolve")
                old["result"] = deepcopy(new["result"])
            with self.subTest(remove=remove), self.assertRaises(EvidenceError):
                replay(value, self.fixture)

    def test_numeric_boolean_compiler_forgery_and_hidden_fetch_reject(self):
        for field, item in (("maximum_jobs", True), ("jobs_started", False)):
            value = deepcopy(self.raw["initial"])
            row = value["samples"][0]
            row["compiler"][field] = row["preparation"]["snapshot"]["compiler"][field] = item
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                replay(value, self.fixture)
        value = deepcopy(self.raw["initial"])
        value["samples"][0]["verification"]["full_fetch_attempts"] = "1"
        with self.assertRaises(EvidenceError):
            replay(value, self.fixture)

    def test_frame_requires_actual_calls_and_full_result_checks(self):
        for field, item in (("frame_invocations", "0"), ("validated", "63"), ("preflight_calls", "0"),
                            ("full_result_equality", False), ("contained_calls", "1")):
            value = deepcopy(self.raw["allocation"])
            row = next(row for row in value["samples"] if row["kind"] == "allocation-frame")
            row[field] = item
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                replay(value, self.fixture)

    def test_native_runtime_counts_and_released_flags_have_closed_types(self):
        for key, field, item in (("configured_runtimes", "control", True),
                ("runtime_threads_after_join", "invocation", False),
                ("catalog_owners_released", "artifacts", 1)):
            value = deepcopy(self.raw["initial"])
            value[key][field] = item
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                replay(value, self.fixture)

    def test_actual_source_sampler_rows_keep_clock_identity(self):
        from io import BytesIO
        for mode in ("initial", "reopen"):
            value = self.raw[mode]
            receipt = value["sampler"]
            rows = sampler.read(BytesIO(self.files[mode + "/sampler.jsonl"]), mode,
                pid=int(receipt["process_id"]), start_ticks=int(receipt["start_time_ticks"]), elapsed_nanos=int(value["elapsed_nanos"]))
            self.assertEqual(len(rows), int(receipt["samples"]))
            self.assertLessEqual(rows[0][1], int(value["before_node_memory"]["collector_started_nanos"]))

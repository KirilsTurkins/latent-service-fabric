"""Small resource collection regressions; these synthetic inputs are not performance evidence."""
from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_render import consumption, outcome, rendered
from tools.phase3_resource_profile import PROFILES
from tools.phase3_resource_storage import failure_storage, storage_snapshot
from tools.phase3_resource_web import configure, observed_summary, renderer_memory, warm_cache_observed
from tools.phase3_web_scenario import MEDIA


class StorageTests(unittest.TestCase):
    def test_failed_run_retains_finite_on_disk_stage_counts_not_active_owner_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "data/provider-blobs-unit/staging"
            for name in ("0001", "0002"):
                (staging / name).mkdir(parents=True)
                (staging / name / "data").write_bytes(b"same")
            observed = failure_storage(root)
            self.assertTrue(observed["available"])
            self.assertEqual(observed["snapshot"]["directoryCounts"]["data/provider-blobs-unit/staging"], 2)
            self.assertEqual(observed["snapshot"]["logicalBytes"], 8)
            self.assertFalse(failure_storage(root / "missing")["available"])

    def test_actual_files_and_hardlinks_have_separate_logical_and_inode_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "packages").mkdir()
            original = root / "packages/component"
            original.write_bytes(b"real-small-file")
            os.link(original, root / "packages/alias")
            measured = storage_snapshot(root, time.monotonic() + 5)
            self.assertEqual(measured["files"], 2)
            self.assertEqual(measured["uniqueInodes"], 1)
            self.assertEqual(measured["logicalBytes"], 30)
            self.assertEqual(measured["uniqueInodeLogicalBytes"], 15)
            self.assertEqual(measured["groups"]["packages"], {"files": 2, "logicalBytes": 30})
            for limits in ({"maximum_files": 1}, {"maximum_bytes": 1}):
                with self.assertRaises(WorkflowError):
                    storage_snapshot(root, time.monotonic() + 5, **limits)
            with self.assertRaisesRegex(WorkflowError, "storage-deadline"):
                storage_snapshot(root, time.monotonic() - 1)

    @unittest.skipUnless(os.name == "posix", "POSIX link ownership")
    def test_storage_scan_refuses_links_to_unowned_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "unowned").symlink_to("/etc/passwd")
            with self.assertRaises(WorkflowError):
                storage_snapshot(root, time.monotonic() + 5)


class RenderIdentityTests(unittest.TestCase):
    def test_consumption_retains_measured_usage_and_missing_is_not_zero(self):
        measured = {key: "0" for key in ("cpuFuel", "peakMemoryBytes", "wallTimeMicros", "childCalls",
            "outboundRequests", "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes",
            "logBytes", "effectCount")}
        measured["peakMemoryBytes"] = "12582912"
        value = {"category": "success", "outcomeKnown": True, "requestDispatched": True,
                 "data": {"activationId": "measured-render", "consumption": measured}}
        self.assertEqual(outcome(value)["consumption"], measured)
        self.assertIsNone(consumption({}))
        for bad in ({**measured, "peakMemoryBytes": True}, {**measured, "peakMemoryBytes": "-1"},
                    {**measured, "peakMemoryBytes": str(2**64)}, {"peakMemoryBytes": "7"},
                    {**measured, "rssBytes": "9"}):
            with self.assertRaises(WorkflowError):
                consumption({"consumption": bad})
        result = {"category": "success", "consumption": measured}
        campaign = {"configuration": {"cells": [{"maximumMemoryBytes": 268435456}]},
                    "calls": [{"heat": heat, "result": result} for heat in
                              ("cold", "warm", "failure", "recovery", "post-overload")],
                    "cancellations": [result], "cycles": [{"arrivals": [
                        {"disposition": "completed", "result": result}]}],
                    "overload": [result, {"category": "transport-failure", "consumption": None}]}
        observed = renderer_memory(campaign)
        self.assertEqual(observed["peakBytes"]["cold"]["maximum"], 12582912)
        self.assertEqual(observed["peakBytes"]["overload"]["unavailableCount"], 1)
        self.assertIsNone(observed["javaScriptAllocatorLiveBytes"])
        for peak in (None, "0", "268435457"):
            changed = copy.deepcopy(campaign)
            changed["calls"][0]["result"]["consumption"] = None if peak is None else {
                **measured, "peakMemoryBytes": peak}
            with self.assertRaises(WorkflowError):
                renderer_memory(changed)

    def test_success_requires_actual_selected_html_and_not_a_success_status_alone(self):
        record = {"componentDigest": "sha256:" + "a" * 64,
                  "assets": [{"path": "/app.js", "mediaType": "text/javascript"}]}
        html = '<div ngh="0">workflow-operator</div><script src="/_lsf/assets/pub/app.js"></script>'
        payload = [{"status": 200, "body-base64": base64.b64encode(html.encode()).decode()}]
        value = {"category": "success", "outcomeKnown": True, "data": {
            "payload": {"encoding": "base64", "mediaType": MEDIA,
                        "data": base64.b64encode(json.dumps(payload).encode()).decode()},
            "resolvedRevision": {"publicationId": "pub", "releaseDigest": record["componentDigest"]}}}
        observed = rendered(value, record, "pub")
        self.assertEqual(observed["htmlBytes"], len(html))
        self.assertEqual(observed["selectedPublication"], "pub")
        for field, changed in (("outcomeKnown", False), ("category", "transport-failure")):
            with self.assertRaises(WorkflowError):
                rendered({**value, field: changed}, record, "pub")
        foreign = copy.deepcopy(value)
        foreign["data"]["resolvedRevision"]["publicationId"] = "foreign"
        with self.assertRaises(WorkflowError):
            rendered(foreign, record, "pub")
        with self.assertRaises(WorkflowError):
            rendered(value, record, "different-publication")


class WorkflowTests(unittest.TestCase):
    def test_unavailable_preparation_metrics_are_not_zero_or_full_population(self):
        observed = observed_summary([3, None, 5])
        self.assertEqual((observed["minimum"], observed["maximum"], observed["count"]), (3, 5, 2))
        self.assertEqual((observed["sampleCount"], observed["unavailableCount"]), (3, 1))
        unavailable = observed_summary([None])
        self.assertIsNone(unavailable["maximum"])
        self.assertEqual(unavailable["unavailableCount"], 1)

    @unittest.skipUnless(sys.platform == "linux", "owned Linux protected process")
    def test_protected_child_descriptors_are_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as temporary, owned_cancellation() as cancellation:
            executable = Path(sys.executable).resolve()
            child = "import ctypes,json,time; assert ctypes.CDLL(None).prctl(4,0,0,0,0)==0; print(json.dumps({'ready':True}),flush=True); time.sleep(30)"
            script = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
            process = Process([str(executable), "-c", script], Path(temporary), dict(os.environ), cancellation)
            try:
                self.assertEqual(process.line(time.monotonic() + 5), {"ready": True})
                probe = Probe(process, file_identity(executable))
                observed = probe.sample()
                self.assertEqual(observed["observedProcesses"], 2)
                descendant = next(row for row in observed["processTree"] if row["processId"] != probe.pid)
                self.assertGreater(descendant["rssBytes"], 0)
                if "descriptors" in descendant["unavailable"]:
                    self.assertIsNone(descendant["handles"])
                    self.assertIsNone(observed["metrics"]["handles"])
                    self.assertIsNone(observed["metrics"]["listeners"])
                else:
                    self.assertGreater(descendant["handles"], 0)
            finally:
                process.close()
            self.assertTrue(process.owner.finished)

    def test_web_preparation_budgets_its_observer_without_changing_runtime_limits(self):
        for name in ("web-smoke", "web-campaign"):
            settings = {"workers": {"runtime": 1, "control": 1}, "cells": [{}], "catalogs": {},
                        "cache": {}, "audit": {}, "securityProfile": "external-capsule-v1"}
            with patch("tools.phase3_resource_web.configure_angular_node", return_value=("config", settings)), \
                    patch("tools.phase3_resource_web.replace_config") as write:
                _path, actual = configure(None, None, None, None, PROFILES[name])
                self.assertEqual(actual["workers"], {"runtime": PROFILES[name]["cells"], "control": 2})
                self.assertEqual(actual["cache"], {"entries": 2, "preparations": 1})
                self.assertEqual(actual["securityProfile"], "external-capsule-v1")
                write.assert_called_once_with("config", actual)
                with self.assertRaisesRegex(WorkflowError, "observer-control-budget"):
                    configure(None, None, None, None, {**PROFILES[name], "controlJobs": 1})

    def test_warm_cache_claim_needs_a_measured_hit_not_a_native_cache_label(self):
        before = {"hits": "0", "entries": "1", "misses": "1", "sourceBytes": "32",
                  "compiledImageBytes": "64", "metadataBytes": "16"}
        after = {**before, "hits": "1"}
        result = warm_cache_observed(before, after)
        self.assertEqual(result["scope"], "in-memory-prepared-cache-not-native-disk-cache")
        for changed in (before, {**after, "misses": "2"}, {**after, "compiledImageBytes": "0"}):
            with self.assertRaises(WorkflowError):
                warm_cache_observed(before, changed)

    def test_expensive_matrix_is_manual_and_failed_receipts_are_retained(self):
        source = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
        self.assertIn('run_phase3_resources:\n', source)
        option = source.split('run_phase3_resources:\n', 1)[1].split('\n\n', 1)[0]
        self.assertIn('default: false', option)
        step = source.split('- name: Execute the bounded Phase 3 resource matrix\n', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.run_phase3_resources", step)
        self.assertIn('tools/run_phase3_resource_acceptance.py', step)
        self.assertIn('CARGO_TARGET_DIR: ${{ github.workspace }}/target/phase3-resource', step)
        retention = source.split('- name: Retain immutable Phase 3 resource attempts\n', 1)[1].split('\n  oci-registry:', 1)[0]
        self.assertIn("if: always() && github.event_name == 'workflow_dispatch' && inputs.run_phase3_resources", retention)
        self.assertIn('phase3-resource-matrix/*.sha256', retention)


if __name__ == "__main__":
    unittest.main()

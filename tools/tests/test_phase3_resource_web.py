"""Small resource collection regressions; these synthetic inputs are not performance evidence."""
from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_render import rendered
from tools.phase3_resource_profile import PROFILES
from tools.phase3_resource_storage import storage_snapshot
from tools.phase3_resource_web import configure, warm_cache_observed
from tools.phase3_web_scenario import MEDIA


class StorageTests(unittest.TestCase):
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

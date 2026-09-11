"""Original cleanup bytes and bounded negative cases; no workload execution."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest
from unittest.mock import patch

from tools.optimization_evidence.common import canonical, read_json
from tools.optimization_kubernetes import cleanup_completion_evidence as completion
from tools.optimization_kubernetes import transport_evidence as transport


FIXTURE = Path(__file__).parent / "fixtures" / "kubernetes-cleanup-completion-03"
WORKER = "9243d49a2cf84e8a6402e55d8b406d75bd0212afc88f550ea1bea262680cba83"


class CleanupCompletionTests(unittest.TestCase):
    def setUp(self):
        self.value = read_json(FIXTURE / "recovery.json")
        self.original = read_json(FIXTURE / "original-cleanup.json")
        self.suite = {"owner": self.value["owner"], "run_id": self.value["run_id"], "profile": "smoke",
            "source": self.value["source"], "source_after": self.value["source"], "failure": None,
            "groups": [None] * 6, "clients": [None], "cleanup": self.original,
            "namespace": self.original["namespace"], "namespace_uid": self.original["namespace_uid"],
            "started_nanos": "251232167286919", "finished_nanos": "251459669840880"}
        self.bootstrap = {"nodes": {"worker": {"container_id": WORKER,
            "image_id": "sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"}}}

    def completed(self, value=None, directory=FIXTURE):
        with patch("subprocess.Popen", side_effect=AssertionError("retained helper must stay inert")):
            completion._completed(value or self.value, self.suite, directory, self.bootstrap)

    def test_actual_seven_original_calls_prove_runtime_and_remote_absence(self):
        self.completed()
        self.assertEqual(self.value["new_guest_invokes"], 0)
        self.assertEqual(self.value["cleanup"]["pods"], self.original["pods"])
        self.assertGreater(int(self.value["started_nanos"]), int(self.suite["finished_nanos"]))

    def test_corrupt_original_transport_bytes_fail(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(FIXTURE / "cleanup.json", root / "cleanup.json")
            raw = (FIXTURE / "api.ndjson").read_bytes()
            self.assertIn(b'"response_bytes":"4607"', raw)
            (root / "api.ndjson").write_bytes(raw.replace(b'"response_bytes":"4607"', b'"response_bytes":"4606"', 1))
            with self.assertRaises(ValueError):
                self.completed(directory=root)

    def test_missing_runtime_absence_or_hidden_call_is_rejected(self):
        original = transport.validate(FIXTURE / "api.ndjson", worker_container_id=WORKER,
            started_nanos=self.value["started_nanos"], finished_nanos=self.value["finished_nanos"])
        for kind in ("owned-container", "extra-call"):
            with self.subTest(kind=kind):
                journal = deepcopy(original)
                if kind == "owned-container":
                    journal["rows"][3]["stdout"] = canonical({"containers": [{"labels": {
                        "io.kubernetes.pod.namespace": self.suite["namespace"]}}]})
                else:
                    journal["rows"].append(deepcopy(journal["rows"][-1]))
                with patch.object(transport, "validate", return_value=journal), self.assertRaisesRegex(
                        ValueError, "runtime-remains|new-call-population"):
                    self.completed()

    def original_journal(self):
        rows = [None] * 2642
        for line in (FIXTURE / "original-runtime.ndjson").read_bytes().splitlines(keepends=True):
            raw = transport._line(line)
            decoded, start, end = transport._exec(raw, WORKER, int(self.suite["started_nanos"]),
                int(self.suite["finished_nanos"]), owner=self.suite["owner"], recovered_smoke03=raw["ordinal"] == 2641)
            rows[raw["ordinal"]] = {"raw": raw, "started_nanos": str(start), "finished_nanos": str(end), **decoded}
        # This fixture tests the four selected rows. Production transport.validate
        # independently verifies this digest over all 2,642 original journal rows.
        return {"sha256": transport.SMOKE03_JOURNAL_SHA256, "rows": rows,
                "recovered_cleanup": {"ordinal": 2641}}

    def test_actual_original_warning_binds_exited_container_and_original_deletes(self):
        journal = self.original_journal()
        expected = {row["uid"]: row["name"] for row in self.original["pods"]}
        used = set()
        completion._original_runtime(self.suite, journal, used, expected)
        self.assertEqual(used, {2638, 2639, 2640, 2641})
        self.assertEqual(journal["rows"][2641]["raw"]["failure"], "EvidenceError")
        self.assertTrue(journal["rows"][2641]["stderr"])
        changed = deepcopy(journal)
        changed["rows"][2641]["cleanup_log_owner"]["pod_uid"] = "wrong-owner"
        with self.assertRaisesRegex(ValueError, "original-warning-owner"):
            completion._original_runtime(self.suite, changed, set(), expected)

    def test_no_automatic_cleanup_completion_for_normal_or_missing_sidecar(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            normal = deepcopy(self.suite)
            normal["cleanup"]["errors"] = []
            self.assertIsNone(completion.load(root, normal))
            with self.assertRaisesRegex(ValueError, "missing-sidecar"):
                completion.load(root, self.suite)
            (root / "cleanup-completion").mkdir()
            with self.assertRaisesRegex(ValueError, "unexpected-sidecar"):
                completion.load(root, normal)

    def test_scope_and_zero_invokes_are_not_inferred_from_recovery_status(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "cleanup-completion"
            directory.mkdir()
            for field, changed, reason in (("new_guest_invokes", 1, "outcome"),
                                            ("run_id", "smoke-04", "historical-scope")):
                value = deepcopy(self.value)
                value[field] = changed
                (directory / "recovery.json").write_bytes(canonical(value))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                    completion.load(root, self.suite)

    def test_recovery_cannot_relabel_original_finished_clock(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "cleanup-completion"
            directory.mkdir()
            value = deepcopy(self.value)
            value["started_nanos"] = str(int(self.suite["finished_nanos"]) - 1)
            (directory / "recovery.json").write_bytes(canonical(value))
            shutil.copyfile(FIXTURE / "original-cleanup.json", root / "cleanup.json")
            # Only original artifact IO is substituted here, to isolate the clock
            # rejection; end-to-end replay binds the full original suite hash.
            with patch.object(completion, "verify_artifact"), self.assertRaisesRegex(ValueError, "separate-clock"):
                completion.load(root, self.suite)


if __name__ == "__main__":
    unittest.main()

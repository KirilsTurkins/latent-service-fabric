"""A numeric kernel-tail witness must not become a physical-retirement claim."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import qualify_host_stream_kernel as reference


class HostStreamKernelReference(unittest.TestCase):
    def rows(self):
        observation = {"matchingRows": 1, "state": "ESTAB", "inodeMatched": True,
                       "memory": {name: 0 for name in reference.observer.MEMORY.values()},
                       "retirementProven": False, "toolSha256": "a" * 64}
        rows = [{"stage": stage, "observation": copy.deepcopy(observation),
                 "hostMemoryBytes": 114688 if i < 2 else 0, "poolConnections": 1 if i < 2 else 0}
                for i, stage in enumerate(reference.STAGES)]
        for row in rows[2:]:
            row["observation"].update(state="FIN-WAIT-2", inodeMatched=False, memory=None)
        return rows

    def output(self, rows):
        return ("test " + reference.provider.KERNEL_CASE + " ... ok\n"
                + "\n".join("KERNEL_OWNER_OBSERVATION " + json.dumps(row) for row in rows)
                + "\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 25 filtered out; finished in 0.1s\n").encode()

    def test_exact_kernel_tail_witness_keeps_all_physical_qualification_false(self):
        rows = self.rows()
        self.assertEqual(reference.outcomes(self.output(rows), 26), rows)
        self.assertTrue(all(r["observation"]["retirementProven"] is False for r in rows))

    def test_unknown_private_unbounded_or_forged_retirement_fields_are_rejected(self):
        for kind in ("extra", "private-memory", "state", "true-retirement", "owner-bound", "boolean-count", "barrier"):
            rows = self.rows()
            if kind == "extra": rows[0]["credential"] = "private-sentinel"
            elif kind == "private-memory": rows[0]["observation"]["memory"]["credential"] = "private-sentinel"
            elif kind == "state": rows[0]["observation"]["state"] = "unknown"
            elif kind == "true-retirement": rows[0]["observation"]["retirementProven"] = True
            elif kind == "owner-bound": rows[0]["hostMemoryBytes"] = 1024 * 1024 + 1
            elif kind == "boolean-count": rows[0]["observation"]["matchingRows"] = True
            else: rows.pop()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                reference.outcomes(self.output(rows), 26)

    def test_fd_absence_or_missing_case_cannot_substitute_for_actual_tail(self):
        rows = self.rows()
        rows[2]["observation"].update(matchingRows=0, state="absent")
        with self.assertRaisesRegex(ValueError, "tail-witness"):
            reference.outcomes(self.output(rows), 26)
        raw = self.output(self.rows())
        for changed in (raw.replace(b"1 passed", b"0 passed"), raw.replace(b"25 filtered", b"26 filtered"),
                        raw.replace(reference.provider.KERNEL_CASE.encode(), b"unknown"), raw + b"x" * 65536):
            with self.assertRaises(ValueError): reference.outcomes(changed, 26)

    def test_wrong_platform_or_changed_source_refuses_before_any_build_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "not-created"
            with patch.object(reference.artifacts, "require_source"), \
                    patch.object(reference.sys, "platform", "unsupported"), \
                    patch.object(reference, "run_owned", side_effect=AssertionError("no native process")), \
                    self.assertRaisesRegex(ValueError, "linux-required"):
                reference.qualify(reference.provider.provider.ROOT, output, "a" * 40)
            self.assertFalse(output.exists())
            with patch.object(reference.artifacts, "require_source"), \
                    patch.object(reference.sys, "platform", "linux"), \
                    patch.object(reference.platform, "machine", return_value="x86_64"), \
                    patch.object(reference.platform, "release", return_value="6.18.0-reference"), \
                    patch.object(reference, "snapshot", side_effect=ValueError("changed-source")), \
                    patch.object(reference, "run_owned", side_effect=AssertionError("no native process")), \
                    self.assertRaisesRegex(ValueError, "changed-source"):
                reference.qualify(reference.provider.provider.ROOT, output, "a" * 40)
            self.assertFalse(output.exists())

    def test_actual_cargo_json_errors_keep_only_bounded_codes_and_primary_source_spans(self):
        row = {"reason": "compiler-message", "message": {"level": "error", "code": {"code": "E0277"},
               "message": "cannot add-assign `u32` to `usize`", "rendered": "private-sentinel",
               "children": [{"message": "private-sentinel"}], "spans": [
                   {"file_name": "crates/latent-streams/src/tests/kernel.rs", "line_start": 168,
                    "column_start": 26, "is_primary": True, "text": ["private-sentinel"]}]}}
        raw = (json.dumps({"reason": "compiler-artifact", "private": "private-sentinel"}) + "\n" + json.dumps(row)).encode()
        result = reference.compiler_diagnostics(raw, Path.cwd())
        self.assertEqual(result["errors"], [{"code": "E0277", "message": "cannot add-assign `u32` to `usize`",
            "spans": [{"file": "crates/latent-streams/src/tests/kernel.rs", "line": 168, "column": 26}]}])
        self.assertNotIn("private-sentinel", json.dumps(result))
        for kind in ("path", "count", "message", "code"):
            changed = copy.deepcopy(row)
            if kind == "path": changed["message"]["spans"][0]["file_name"] = "../private"
            elif kind == "message": changed["message"]["message"] = "x" * 2049
            elif kind == "code": changed["message"]["code"]["code"] = "unknown"
            raw = ("\n".join([json.dumps(changed)] * (17 if kind == "count" else 1))).encode()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                reference.compiler_diagnostics(raw, Path.cwd())

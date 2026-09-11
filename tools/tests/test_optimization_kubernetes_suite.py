"""Bounded suite index parsing, without claiming these small files are campaigns."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.optimization_evidence.common import EvidenceError, canonical, sha256
from tools.optimization_kubernetes import evidence, model, replay


class SuiteIndexTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.suite = {"schema": model.PREFIX + "suite.v1", "profile": "smoke", "failure": None, "groups": []}
        self.groups = []
        for group in model.groups("smoke", 0):
            identity = {"pair": 0, "group": group["ordinal"], "arm": group["arm"], "density": group["density"]}
            value = {**identity, "opaque_original": ["byte-preserved", {"raw": "unchanged"}]}
            data = canonical(value) + b"\r\n"
            name = f"group-0-{group['ordinal']}.json"
            (self.root / name).write_bytes(data)
            self.suite["groups"].append({**identity, "artifact": {"path": name, "bytes": str(len(data)), "sha256": sha256(data)}})
            self.groups.append(value)

    def load(self, suite=None):
        (self.root / "suite.json").write_bytes(canonical(self.suite if suite is None else suite) + b"\n")
        return replay.load_suite(self.root)

    def test_exact_group_bytes_resolve_without_rewriting_any_original(self):
        result = self.load()
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        self.assertEqual(result["groups"], self.groups)
        self.assertEqual(self.load()["groups"], self.groups)
        evidence._suite_index(self.root, result)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})

    def test_component_gate_rebinds_original_index_after_expansion(self):
        expanded = self.load()
        evidence._suite_index(self.root, expanded)
        path = self.root / "group-0-0.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(EvidenceError):
            evidence._suite_index(self.root, expanded)

    def test_missing_extra_reordered_or_boolean_identity_rejects(self):
        mutations = []
        for change in (lambda rows: rows.pop(), lambda rows: rows.append(rows[0]),
                       lambda rows: rows.reverse(), lambda rows: rows[0].update(pair=False),
                       lambda rows: rows[0].update(extra=True)):
            value = deepcopy(self.suite)
            change(value["groups"])
            mutations.append(value)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                self.load(value)

    def test_wrong_path_bytes_or_rehashed_crossed_sidecar_rejects(self):
        for key, value in (("path", "../group-0-0.json"), ("bytes", "0"), ("sha256", "sha256:" + "0"*64)):
            changed = deepcopy(self.suite)
            changed["groups"][0]["artifact"][key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                self.load(changed)
        value = {**self.groups[0], "arm": "native"}
        data = canonical(value)
        path = self.root / "group-0-0.json"
        path.write_bytes(data)
        self.suite["groups"][0]["artifact"].update(bytes=str(len(data)), sha256=sha256(data))
        with self.assertRaises(EvidenceError):
            self.load()

    def test_failed_inline_original_cannot_be_relabelled_as_completed_index(self):
        self.suite.update(failure={"type": "EvidenceError", "reason": "retained-failure"}, groups=self.groups)
        with self.assertRaises(EvidenceError):
            self.load()
        self.suite["failure"] = None
        with self.assertRaises(EvidenceError):
            self.load()


if __name__ == "__main__":
    unittest.main()

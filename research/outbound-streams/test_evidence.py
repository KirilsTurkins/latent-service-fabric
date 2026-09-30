"""Receipt completeness regressions; a checksum is not an execution attestation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import run


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        here = self.root / "research/outbound-streams"
        (here / "evidence").mkdir(parents=True)
        (here / "example_test.go").write_text("func TestExample(t *testing.T) {}\n")
        (here / "extra.go").write_text("package streams\n")
        (here / "test_evidence.py").write_text("    def test_case(self): pass\n")
        (here / "evidence/deepening-negative.json").write_text("{}")
        commands = [{"id": i, "exitCode": 0, "argv": []} for i in run.COMMANDS]
        commands[4]["argv"] = ["go", "test", "-race", "-count=1", "-timeout=30s", "-json", "."]
        self.receipt = {"formatVersion": 2, "status": "passed", "profile": "native",
                        "sources": run.source_manifest(True, self.root), "commands": commands,
                        "testResults": [{"name": "TestExample", "result": "pass"}],
                        "topLevelGoTests": 1, "goCasesIncludingSubtests": 1, "pythonContractTests": 1}

    def test_complete_profile_is_accepted(self):
        run.verify_receipt(self.receipt, self.root)

    def test_source_subset_added_source_and_changed_bytes_are_rejected(self):
        partial = copy.deepcopy(self.receipt)
        partial["sources"].pop(next(iter(partial["sources"])))
        with self.assertRaises(ValueError):
            run.verify_receipt(partial, self.root)
        new = self.root / "research/outbound-streams/new.go"
        new.write_text("new compile input")
        with self.assertRaises(ValueError):
            run.verify_receipt(self.receipt, self.root)
        new.unlink()
        (self.root / "research/outbound-streams/extra.go").write_text("changed")
        with self.assertRaises(ValueError):
            run.verify_receipt(self.receipt, self.root)

    def test_missing_duplicate_skipped_and_forged_test_cases_are_rejected(self):
        for results in ([], self.receipt["testResults"] * 2,
                        [{"name": "TestExample", "result": "skip"}],
                        [{"name": "TestUnrelated", "result": "pass"}]):
            with self.subTest(results=results):
                changed = copy.deepcopy(self.receipt)
                changed["testResults"] = results
                with self.assertRaises(ValueError):
                    run.verify_receipt(changed, self.root)

    def test_missing_commands_false_exit_status_and_weakened_race_profile_are_rejected(self):
        for mutation in (lambda r: r["commands"].pop(),
                         lambda r: r["commands"][0].update(exitCode=False),
                         lambda r: r["commands"][4].update(argv=["go", "test", "."])):
            changed = copy.deepcopy(self.receipt)
            mutation(changed)
            with self.assertRaises(ValueError):
                run.verify_receipt(changed, self.root)

    def test_historical_failed_and_wrong_profile_receipts_are_rejected(self):
        for key, value in (("formatVersion", 1), ("status", "failed"), ("profile", "invented"),
                           ("pythonContractTests", 0), ("topLevelGoTests", 0)):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.receipt)
                changed[key] = value
                with self.assertRaises(ValueError):
                    run.verify_receipt(changed, self.root)

    def test_duplicate_json_keys_and_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"status":"failed","status":"passed"}', object_pairs_hook=run.unique_json)
        changed = copy.deepcopy(self.receipt)
        changed["sources"] = {"../outside": "0" * 64}
        with self.assertRaises(ValueError):
            run.verify_receipt(changed, self.root)


if __name__ == "__main__":
    unittest.main()

"""Baseline coverage-slot guard, automatically discovered by validate_contracts.sh."""

import copy
import json
from pathlib import Path
import unittest

from tools.ci_lane_inventory import workflow_errors

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tools/tests/fixtures/ci_lane_baseline.json"


def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def synthetic_workflow():
    # Only a model fixture. The separate repository test reads the actual YAML.
    value = {"concurrency": {"cancel-in-progress": True}, "jobs": {}}
    for name, spec in baseline()["jobs"].items():
        value["jobs"][name] = {
            "name": "CI result" if name == "result" else name,
            "needs": spec["needs"], "if": spec["if"],
            "steps": [{"name": step["name"], "if": step["if"], "run": "synthetic"}
                      for step in spec["commands"]]
                     + [{"name": step["name"], "if": step["if"], "uses": "synthetic"}
                        for step in spec.get("conditional_actions", [])],
        }
    return value


class InventoryTests(unittest.TestCase):
    def test_complete_model_matches(self):
        self.assertEqual(workflow_errors(synthetic_workflow(), baseline()), ())

    def test_missing_renamed_and_unregistered_required_command_fail(self):
        for edit in ("delete", "rename", "add", "duplicate"):
            with self.subTest(edit=edit):
                model = synthetic_workflow()
                steps = model["jobs"]["rust"]["steps"]
                if edit == "delete":
                    del steps[0]
                elif edit == "rename":
                    steps[0]["name"] = "Renamed"
                elif edit == "add":
                    steps.append({"name": "Unregistered", "run": "synthetic"})
                else:
                    steps.append(copy.deepcopy(steps[0]))
                self.assertIn("rust:command-inventory-drift", workflow_errors(model, baseline()))

    def test_late_phase2_and_provider_slots_cannot_disappear(self):
        for fragment in ("NATS triggers", "Vault secrets", "Phase 2 delivery", "S3 blobs"):
            with self.subTest(fragment=fragment):
                model = synthetic_workflow()
                steps = model["jobs"]["rust"]["steps"]
                model["jobs"]["rust"]["steps"] = [s for s in steps if fragment not in s["name"]]
                self.assertTrue(workflow_errors(model, baseline()))

    def test_renderer_setup_and_execution_remain_conditional(self):
        for fragment in ("qualified Angular build runtime", "component composer", "browser hydration"):
            with self.subTest(fragment=fragment):
                model = synthetic_workflow()
                step = next(s for s in model["jobs"]["rust"]["steps"] if fragment in s["name"])
                del step["if"]
                self.assertTrue(workflow_errors(model, baseline()))

    def test_final_result_remains_unconditional_and_complete(self):
        for edit in ("if", "name", "needs"):
            with self.subTest(edit=edit):
                model = synthetic_workflow()
                model["jobs"]["result"][edit] = "changed"
                self.assertTrue(workflow_errors(model, baseline()))

    def test_unknown_missing_or_malformed_job_fails(self):
        for edit in ("unknown", "missing", "malformed"):
            with self.subTest(edit=edit):
                model = synthetic_workflow()
                if edit == "unknown":
                    model["jobs"]["new-job"] = {}
                elif edit == "missing":
                    del model["jobs"]["contracts"]
                else:
                    model["jobs"]["contracts"] = None
                self.assertTrue(workflow_errors(model, baseline()))

    def test_cancellation_and_manual_catalog_scope_remain(self):
        model = synthetic_workflow()
        model["concurrency"]["cancel-in-progress"] = False
        self.assertIn("superseded-run-cancellation-missing", workflow_errors(model, baseline()))
        model = synthetic_workflow()
        model["jobs"]["catalog"]["steps"][-1]["if"] = ""
        self.assertTrue(workflow_errors(model, baseline()))

    def test_unknown_schema_is_rejected(self):
        spec = baseline()
        spec["schema"] = "future"
        with self.assertRaises(ValueError):
            workflow_errors(synthetic_workflow(), spec)


class RepositoryInventoryTests(unittest.TestCase):
    def test_current_workflow_has_no_unmapped_required_slots(self):
        # PyYAML is already pinned by tools/requirements.lock. Do not skip a
        # missing dependency/file: required CI inventory validation fails closed.
        import yaml
        spec = baseline()
        workflow = yaml.safe_load((ROOT / spec["workflow_path"]).read_text(encoding="utf-8"))
        self.assertEqual(workflow_errors(workflow, spec), ())


if __name__ == "__main__":
    unittest.main()

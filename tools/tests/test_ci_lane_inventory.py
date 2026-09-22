"""Structural regressions for the bounded CI lane integration."""

import copy
import json
from pathlib import Path
import unittest

from tools import ci_suite_inventory
from tools.ci_lane_inventory import inventory_errors, workflow_errors

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tools/tests/fixtures/ci_lane_baseline.json"


def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def synthetic_workflow():
    spec = baseline()
    jobs = {name: {"steps": []} for name in spec["required_jobs"]}
    jobs["rust"] = {
        "needs": spec["rust"]["needs"],
        "if": spec["rust"]["if"],
        "steps": [
            {"name": "Check selected renderer prerequisites before building",
             "if": spec["rust"]["renderer_condition"], "run": "preflight"},
            {"name": "Set up the qualified Angular build runtime",
             "if": spec["rust"]["renderer_condition"], "uses": "node"},
            {"name": "Set up the pinned component composer",
             "if": spec["rust"]["renderer_condition"], "uses": "wasm-tools"},
            {"name": spec["rust"]["prepared_step"],
             "if": spec["rust"]["renderer_condition"],
             "run": "\n".join(spec["rust"]["prepared_command_fragments"])},
            {"name": spec["rust"]["lane_step"], "id": spec["rust"]["lane_id"],
             "run": "\n".join(spec["rust"]["lane_command_fragments"])},
            *({"name": name, "run": "physical"} for name in spec["rust"]["physical_after"]),
        ],
    }
    jobs["catalog"] = {"steps": [{
        "name": spec["catalog"]["manual_step"],
        "if": spec["catalog"]["manual_if"],
        "run": "catalog",
    }]}
    jobs["result"] = {
        "name": "CI result", "if": "always()", "needs": spec["result_needs"], "steps": []
    }
    return {
        "concurrency": {"cancel-in-progress": True},
        "on": {"workflow_dispatch": {"inputs": {
            "ci_lane_workers": {"type": "choice", "options": ["1", "2"], "default": "2"}
        }}},
        "jobs": jobs,
    }


class InventoryTests(unittest.TestCase):
    def test_complete_model_matches(self):
        self.assertEqual(workflow_errors(synthetic_workflow(), baseline()), ())

    def test_lane_is_single_bounded_owner_with_reviewed_command(self):
        for edit in ("missing", "duplicate", "workers"):
            with self.subTest(edit=edit):
                model = synthetic_workflow()
                steps = model["jobs"]["rust"]["steps"]
                lane = next(step for step in steps if step.get("id") == "integration_lanes")
                if edit == "missing":
                    steps.remove(lane)
                elif edit == "duplicate":
                    steps.append(copy.deepcopy(lane))
                else:
                    lane["run"] = lane["run"].replace("--workers", "--not-workers")
                self.assertTrue(workflow_errors(model, baseline()))

    def test_old_serial_renderer_and_provider_slots_cannot_return(self):
        model = synthetic_workflow()
        model["jobs"]["rust"]["steps"].append({
            "name": baseline()["rust"]["removed_serial_steps"][0], "run": "old"
        })
        self.assertTrue(workflow_errors(model, baseline()))

    def test_renderer_preparation_remains_conditionally_selected(self):
        for name in ("Set up the qualified Angular build runtime",
                     "Set up the pinned component composer",
                     "Prepare immutable browser lane component"):
            with self.subTest(name=name):
                model = synthetic_workflow()
                step = next(s for s in model["jobs"]["rust"]["steps"] if s.get("name") == name)
                step["if"] = ""
                self.assertTrue(workflow_errors(model, baseline()))

    def test_physical_qualification_stays_after_bounded_lanes(self):
        model = synthetic_workflow()
        steps = model["jobs"]["rust"]["steps"]
        lane = next(i for i, step in enumerate(steps) if step.get("id") == "integration_lanes")
        physical = next(i for i, step in enumerate(steps)
                        if step.get("name") == "Validate bounded Phase 2 delivery and resource workflows")
        steps.insert(lane, steps.pop(physical))
        self.assertTrue(workflow_errors(model, baseline()))

    def test_worker_choice_is_explicitly_one_or_two(self):
        for options in (["2"], ["1", "2", "3"], [1, 2]):
            with self.subTest(options=options):
                model = synthetic_workflow()
                model["on"]["workflow_dispatch"]["inputs"]["ci_lane_workers"]["options"] = options
                self.assertIn("lane-worker-selection-drift", workflow_errors(model, baseline()))

    def test_final_result_and_superseded_cancellation_remain_fail_closed(self):
        model = synthetic_workflow()
        model["concurrency"]["cancel-in-progress"] = False
        self.assertIn("superseded-run-cancellation-missing", workflow_errors(model, baseline()))
        model = synthetic_workflow()
        model["jobs"]["result"]["if"] = "success()"
        self.assertIn("ci-result-contract", workflow_errors(model, baseline()))

    def test_manual_catalog_scope_is_unchanged(self):
        model = synthetic_workflow()
        model["jobs"]["catalog"]["steps"][0]["if"] = ""
        self.assertIn("catalog:manual-scope-drift", workflow_errors(model, baseline()))

    def test_current_suite_inventory_supplies_exact_lane_contracts(self):
        self.assertEqual(inventory_errors(ci_suite_inventory.load(), baseline()), ())

    def test_inventory_drift_is_rejected(self):
        data = copy.deepcopy(ci_suite_inventory.load())
        data["selections"]["s3-blobs"]["runner"] = "unknown"
        self.assertTrue(inventory_errors(data, baseline()))

    def test_unknown_schema_is_rejected(self):
        spec = baseline()
        spec["schema"] = "future"
        with self.assertRaises(ValueError):
            workflow_errors(synthetic_workflow(), spec)


class RepositoryInventoryTests(unittest.TestCase):
    def test_current_workflow_has_the_bounded_lane_contract(self):
        import yaml
        spec = baseline()
        workflow = yaml.safe_load((ROOT / spec["workflow_path"]).read_text(encoding="utf-8"))
        self.assertEqual(workflow_errors(workflow, spec), ())
        self.assertEqual(inventory_errors(ci_suite_inventory.load(), spec), ())


if __name__ == "__main__":
    unittest.main()

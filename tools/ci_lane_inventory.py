"""Structural guard for the bounded CI lane rollout.

Exact run-block text remains owned by tools/ci/commands.json. This module checks
the architectural invariants that matter specifically to #431: one shared Rust
producer, one co-located bounded lane coordinator, exact inventory ownership,
renderer gating, exclusive late physical qualification, cancellation, and the
unconditional final result.
"""
from __future__ import annotations

from typing import Any


SCHEMA = "lsf.ci-lane-baseline.v2"


def _steps(job: object) -> list[dict[str, Any]]:
    if not isinstance(job, dict) or not isinstance(job.get("steps", []), list):
        return []
    return [step for step in job["steps"] if isinstance(step, dict)]


def workflow_errors(workflow: dict[str, Any], baseline: dict[str, Any]) -> tuple[str, ...]:
    if baseline.get("schema") != SCHEMA:
        raise ValueError("unsupported-lane-baseline")
    errors: list[str] = []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return ("missing-workflow-jobs",)
    if set(jobs) != set(baseline["required_jobs"]):
        errors.append("job-inventory-mismatch")
    concurrency = workflow.get("concurrency")
    if not isinstance(concurrency, dict) or concurrency.get("cancel-in-progress") is not True:
        errors.append("superseded-run-cancellation-missing")

    result = jobs.get("result")
    if (not isinstance(result, dict) or result.get("name") != "CI result"
            or result.get("if") != "always()"
            or set(result.get("needs", [])) != set(baseline["result_needs"])):
        errors.append("ci-result-contract")

    rust = jobs.get("rust")
    spec = baseline["rust"]
    if not isinstance(rust, dict):
        errors.append("rust:missing-job")
        return tuple(errors)
    needs = rust.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    if needs != spec["needs"] or rust.get("if") != spec["if"]:
        errors.append("rust:selection-drift")
    steps = _steps(rust)
    names = [step.get("name") for step in steps]

    lanes = [step for step in steps if step.get("id") == spec["lane_id"]]
    if len(lanes) != 1:
        errors.append("rust:lane-owner-count")
    else:
        lane = lanes[0]
        command = lane.get("run", "")
        if (lane.get("name") != spec["lane_step"] or not isinstance(command, str)
                or any(fragment not in command for fragment in spec["lane_command_fragments"])):
            errors.append("rust:lane-command-drift")

    prepared = [step for step in steps if step.get("name") == spec["prepared_step"]]
    if (len(prepared) != 1 or prepared[0].get("if") != spec["renderer_condition"]
            or any(fragment not in prepared[0].get("run", "")
                   for fragment in spec["prepared_command_fragments"])):
        errors.append("rust:prepared-renderer-drift")

    for name in spec["renderer_actions"]:
        matches = [step for step in steps if step.get("name") == name and "uses" in step]
        if len(matches) != 1 or matches[0].get("if") != spec["renderer_condition"]:
            errors.append("rust:renderer-prerequisite-drift:" + name)

    for name in spec["renderer_run_steps"]:
        matches = [step for step in steps if step.get("name") == name and "run" in step]
        if len(matches) != 1 or matches[0].get("if") != spec["renderer_condition"]:
            errors.append("rust:renderer-prerequisite-drift:" + name)

    for name in spec["removed_serial_steps"]:
        if name in names:
            errors.append("rust:serialized-integration-still-present:" + name)

    lane_index = next((i for i, step in enumerate(steps) if step.get("id") == spec["lane_id"]), -1)
    for name in spec["physical_after"]:
        positions = [i for i, step in enumerate(steps) if step.get("name") == name]
        if len(positions) != 1 or positions[0] <= lane_index:
            errors.append("rust:physical-order-drift:" + name)

    catalog = jobs.get("catalog")
    catalog_steps = _steps(catalog)
    manual = [step for step in catalog_steps if step.get("name") == baseline["catalog"]["manual_step"]]
    if len(manual) != 1 or manual[0].get("if") != baseline["catalog"]["manual_if"]:
        errors.append("catalog:manual-scope-drift")

    triggers = workflow.get("on", workflow.get(True, {}))
    dispatch = triggers.get("workflow_dispatch", {}) if isinstance(triggers, dict) else {}
    inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
    workers = inputs.get("ci_lane_workers") if isinstance(inputs, dict) else None
    if (not isinstance(workers, dict) or workers.get("type") != "choice"
            or workers.get("default") != "2" or workers.get("options") != ["1", "2"]):
        errors.append("lane-worker-selection-drift")
    return tuple(errors)


def inventory_errors(data: dict[str, Any], baseline: dict[str, Any]) -> tuple[str, ...]:
    if baseline.get("schema") != SCHEMA:
        raise ValueError("unsupported-lane-baseline")
    errors: list[str] = []
    rows = {row.get("id"): row for row in data.get("suites", []) if isinstance(row, dict)}
    selections = data.get("selections", {})
    for key in baseline["inventory"]["provider_selections"]:
        selected = selections.get(key) if isinstance(selections, dict) else None
        if not isinstance(selected, dict):
            errors.append("inventory:missing-provider-selection:" + key)
            continue
        row = rows.get(selected.get("suite"))
        if (selected.get("runner") != "provider-owner" or not selected.get("names")
                or len(selected["names"]) != len(set(selected["names"]))
                or not isinstance(row, dict) or row.get("recipe") != "workspace-all-features"
                or not set(selected["names"]) <= set(row.get("expectedIgnored", []))):
            errors.append("inventory:provider-selection-drift:" + key)

    browser_key = baseline["inventory"]["browser_selection"]
    browser = selections.get(browser_key) if isinstance(selections, dict) else None
    if (not isinstance(browser, dict) or browser.get("runner") != "ci_rust_artifacts"
            or not browser.get("names")):
        errors.append("inventory:browser-selection-drift")

    contracts = data.get("processContracts", {})
    contract = contracts.get(baseline["inventory"]["renderer_process_contract"]) if isinstance(contracts, dict) else None
    if (not isinstance(contract, dict) or not contract.get("suiteIds")
            or set(contract.get("prerequisites", {}).get("artifacts", []))
            != {"test-manifest", "component", "private-renderer"}):
        errors.append("inventory:renderer-process-contract-drift")
    return tuple(errors)

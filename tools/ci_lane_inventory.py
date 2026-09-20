"""Coverage-slot drift guard for the lane rollout; not a suite classifier.

The immutable source/blob identity in the snapshot identifies the original full
commands. This guard checks top-level slots, dependencies and triggering
conditions. It intentionally does NOT claim test-discovery completeness, verify
command semantics inside a slot, or replace the exact suite inventory (#427).
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def workflow_errors(workflow: dict[str, Any], baseline: dict[str, Any]) -> tuple[str, ...]:
    if baseline.get("schema") != "lsf.ci-lane-baseline.v1":
        raise ValueError("unsupported-lane-baseline")
    errors = []
    actual = workflow.get("jobs", {})
    expected = baseline["jobs"]
    if not isinstance(actual, dict):
        return ("missing-workflow-jobs",)
    if set(actual) != set(expected):
        errors.append("job-inventory-mismatch")
    concurrency = workflow.get("concurrency", {})
    if not isinstance(concurrency, dict) or concurrency.get("cancel-in-progress") is not True:
        errors.append("superseded-run-cancellation-missing")
    for name, spec in expected.items():
        job = actual.get(name)
        if not isinstance(job, dict):
            errors.append(f"{name}:missing-job")
            continue
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or Counter(needs) != Counter(spec["needs"]):
            errors.append(f"{name}:dependency-drift")
        if job.get("if", "") != spec["if"]:
            errors.append(f"{name}:selection-drift")
        steps = job.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            errors.append(f"{name}:invalid-steps")
            continue
        commands = [step for step in steps if "run" in step]
        names = [step.get("name") for step in commands]
        if (any(not isinstance(value, str) for value in names)
                or Counter(names) != Counter(step["name"] for step in spec["commands"])):
            errors.append(f"{name}:command-inventory-drift")
            continue
        by_name = {step["name"]: step for step in commands}
        for step in spec["commands"]:
            if by_name[step["name"]].get("if", "") != step["if"]:
                errors.append(f"{name}:{step['name']}:selection-drift")
        for action in spec.get("conditional_actions", []):
            matches = [step for step in steps if step.get("name") == action["name"] and "uses" in step]
            if len(matches) != 1 or matches[0].get("if", "") != action["if"]:
                errors.append(f"{name}:{action['name']}:prerequisite-drift")
    result = actual.get("result", {})
    if not isinstance(result, dict) or result.get("name") != "CI result":
        errors.append("required-check-name-changed")
    return tuple(errors)

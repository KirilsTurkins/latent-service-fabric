"""Structural guard for the bounded CI lane rollout.

Exact run-block text is owned by tools/ci/contracts/. This module checks
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


# Comprehensive workflow contracts complement (not replace) the lane-specific
# invariants above. Every parsed field participates in equality. Only executable
# action revisions are omitted; the independent action validator owns pin policy.
def workflow_model(text: str) -> dict[str, Any]:
    """Parse bounded, unambiguous YAML with YAML 1.2 booleans (not YAML 1.1 'on')."""
    import copy
    import re
    import yaml
    from tools import workflow_action_yaml

    from tools.validate_workflow_actions import MAX_WORKFLOW_BYTES
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_WORKFLOW_BYTES:
        raise ValueError("workflow-byte-limit")
    workflow_action_yaml.references(text)  # Existing duplicate/merge/size guards.
    for event in yaml.parse(text, Loader=yaml.BaseLoader):
        if isinstance(event, yaml.events.AliasEvent) or getattr(event, "tag", None):
            raise ValueError("unsupported-workflow-alias-or-tag")
        # YAML 1.1 octal/sexagesimal and nonfinite scalars are ambiguous across
        # consumers. Require quoting rather than silently interpreting them.
        if (isinstance(event, yaml.events.ScalarEvent) and event.style is None
                and re.fullmatch(r"[+-]?(?:0[0-9_]+|0[xob][0-9a-fA-F_]+|[0-9][0-9_]*:[0-9_:]+|\.(?:inf|nan))",
                                 event.value, re.IGNORECASE)):
            raise ValueError("ambiguous-workflow-number-requires-quotes")

    class Loader(yaml.SafeLoader):
        pass

    Loader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
    for key, resolvers in Loader.yaml_implicit_resolvers.items():
        Loader.yaml_implicit_resolvers[key] = [
            (tag, pattern) for tag, pattern in resolvers
            if tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}
        ]
    Loader.add_implicit_resolver("tag:yaml.org,2002:bool",
                                 re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"), list("tTfF"))
    model = yaml.load(text, Loader=Loader)

    return validate_workflow_model(model)


def validate_workflow_model(model: Any) -> dict[str, Any]:
    """Validate expected/observed JSON shape without discarding unknown fields."""
    import json
    import re

    def json_value(value: Any) -> None:
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("non-string-workflow-key")
            for item in value.values():
                json_value(item)
        elif isinstance(value, list):
            for item in value:
                json_value(item)
        elif value is not None and type(value) not in {str, int, float, bool}:
            raise ValueError("non-json-workflow-value")

    json_value(model)
    json.dumps(model, allow_nan=False)
    if not isinstance(model, dict) or not isinstance(model.get("jobs"), dict) or not model["jobs"]:
        raise ValueError("missing-workflow-jobs")
    for job_id, job in model["jobs"].items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job_id) or not isinstance(job, dict):
            raise ValueError("invalid-workflow-job")
        if "uses" in job and (not isinstance(job["uses"], str) or not job["uses"]):
            raise ValueError("invalid-reusable-workflow-identity")
        if "uses" in job and "steps" in job:
            raise ValueError("ambiguous-workflow-job")
        if "steps" in job:
            if not isinstance(job["steps"], list) or not job["steps"]:
                raise ValueError("empty-or-invalid-workflow-steps")
            ids = set()
            commands = set()
            for step in job["steps"]:
                if not isinstance(step, dict) or ("run" in step) == ("uses" in step):
                    raise ValueError("ambiguous-workflow-step")
                if "uses" in step and (not isinstance(step["uses"], str) or not step["uses"]):
                    raise ValueError("invalid-step-action-identity")
                if "id" in step:
                    identity = step["id"]
                    if (not isinstance(identity, str)
                            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", identity) or identity in ids):
                        raise ValueError("duplicate-or-invalid-step-id")
                    ids.add(identity)
                if "run" in step:
                    name = step.get("id", step.get("name"))
                    if not isinstance(name, str) or not name or name in commands:
                        raise ValueError("duplicate-or-unnamed-required-command")
                    if not isinstance(step["run"], str) or not step["run"].strip():
                        raise ValueError("empty-or-invalid-required-command")
                    commands.add(name)
        elif "uses" not in job:
            raise ValueError("missing-workflow-job-execution")
    return model


def structural_workflow(model: dict[str, Any]) -> dict[str, Any]:
    """Retain unknown fields, all inheritance and list order; strip only pins."""
    import copy
    import re

    result = copy.deepcopy(model)

    def identity(config: dict[str, Any]) -> None:
        if "uses" not in config:
            return
        value = config["uses"]
        if not isinstance(value, str):
            raise ValueError("invalid-action-reference")
        if value.startswith(("./", "$/")):
            return  # A local path is itself the invocation identity.
        target, separator, revision = value.rpartition("@")
        pattern = r"sha256:[0-9a-fA-F]{64}" if value.startswith("docker://") else r"[0-9a-fA-F]{40}"
        if not separator or not target or re.fullmatch(pattern, revision) is None:
            raise ValueError("mutable-or-invalid-action-revision")
        config["uses"] = target

    for job in result["jobs"].values():
        identity(job)  # Reusable workflows are executable action references too.
        for step in job.get("steps", []):
            identity(step)
    return result


def run_commands(path: str, model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The established command identity/shape, also assembled from expectations.

    Legacy names remain lossless historical identities. New steps should have an
    explicit id; changing a display name on an id-bearing step does not rename its
    command. Inheritance is fully protected by the surrounding structural model.
    """
    result = {}
    for job, config in model["jobs"].items():
        for step in config.get("steps", []):
            if "run" not in step:
                continue
            name = step.get("id", step.get("name"))
            if not isinstance(name, str) or not name or not isinstance(step["run"], str):
                raise ValueError("unnamed-or-invalid-required-command")
            key = f"{path}:{job}:{name}"
            if key in result:
                raise ValueError("duplicate-required-command")
            result[key] = {"workflow": path, "job": job, "name": name,
                           "jobIf": config.get("if", "success()"),
                           "stepIf": step.get("if", "success()"),
                           "workingDirectory": step.get("working-directory", "."),
                           "shell": step.get("shell", "default"), "run": step["run"].rstrip()}
    return result


def result_contract_errors(workflow: dict[str, Any]) -> tuple[str, ...]:
    """The protected result cannot be re-baselined into a conditional success."""
    from tools import ci_suite_inventory as registry

    result = workflow.get("jobs", {}).get("result", {})
    needs = result.get("needs", [])
    if (result.get("name") != "CI result" or result.get("if") != "always()"
            or not isinstance(needs, list) or not all(isinstance(job, str) for job in needs)
            or len(needs) != len(registry.ALL_JOBS)
            or set(needs) != registry.ALL_JOBS or result.get("continue-on-error", False) is not False):
        return ("ci-result-topology",)
    checks = [step for step in result.get("steps", []) if "run" in step]
    if (len(checks) != 1 or checks[0].get("run", "").strip() != "python3 tools/ci_result.py"
            or not isinstance(checks[0].get("if", "success()"), str)
            or checks[0].get("if", "success()") not in {"success()", "always()"}
            or checks[0].get("continue-on-error", False) is not False
            or not isinstance(checks[0].get("env", {}), dict)
            or checks[0].get("env", {}).get("CI_JOB_RESULTS") != "${{ toJSON(needs) }}"):
        return ("ci-result-execution",)
    return ()

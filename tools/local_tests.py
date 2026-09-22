"""One local entry point over the registered CI suite and prepared-artifact contracts."""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys

from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_discovery as discovery
from tools import ci_suite_inventory as registry
from tools import phase3_security_artifacts as security
from tools.build_process import BuildProcessError, run_bounded
from tools.owned_test_process import run_owned as owned_run
from tools.test_run import FAILURE_SCHEMA, ProcessFailure, TestRun, digest as file_digest

REPO = Path(__file__).resolve().parents[1]
SELECTION_PREFIX = "selection."
PROCESS_PREFIX = "process."
ANGULAR_PROCESS = PROCESS_PREFIX + "angular-renderer"
MAX_REPORT = 64 * 1024
MAX_BUILD_OUTPUT = 32 * 1024 * 1024
REPORT_KEYS = {
    "schemaVersion", "suite", "runId", "outcome", "category", "reason", "stage",
    "evidenceKind", "source", "fixtures", "child", "elapsedMs", "timings",
    "startupMs", "teardownMs", "cleanupFailures", "logTail", "reproduction",
}
REPRODUCTION_KEYS = {
    "suite", "cases", "recipe", "mode", "web", "observed", "fixtureOnly",
    "preflight", "fault", "source", "fixtures",
}


class LocalTestError(Exception):
    def __init__(self, reason: str, code: int = 3, state: str = "not-run") -> None:
        super().__init__(reason)
        self.code = code
        self.state = state


def _data(repo: Path) -> dict:
    return registry.load(repo / "tools/ci/suites.json")


def _rows(data: dict) -> dict[str, dict]:
    return {row["id"]: row for row in data["suites"]}


def _selection_id(name: str) -> str:
    return SELECTION_PREFIX + name


def identities(repo: Path) -> list[str]:
    data = _data(repo)
    return sorted([*(row["id"] for row in data["suites"]),
                   *(_selection_id(name) for name in data["selections"]),
                   ANGULAR_PROCESS])


def _resolve(repo: Path, key: str) -> tuple[dict, dict, dict | None, str | None]:
    data = _data(repo)
    rows = _rows(data)
    if key.startswith(SELECTION_PREFIX):
        name = key.removeprefix(SELECTION_PREFIX)
        selection = data["selections"].get(name)
        if selection is None:
            raise LocalTestError(f"unknown suite selection: {key}")
        return data, rows[selection["suite"]], selection, name
    row = rows.get(key)
    if row is None:
        raise LocalTestError(f"unknown suite: {key}")
    return data, row, None, None


def _platform() -> str:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine, machine)
    return f"{sys.platform}-{machine}"


def _inventory_path(repo: Path, path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else repo / path


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _selected_cases(row: dict, selection: dict | None, case: str | None) -> tuple[list[str], list[str]]:
    if selection is not None:
        available = list(selection["names"])
        ignored = available if selection["ignored"] else []
        if case is None:
            return available, ignored
        if case not in available:
            raise LocalTestError("exact case is not registered by this selection; substring filters are not accepted")
        if len(available) != 1:
            raise LocalTestError("registered multi-case selections are atomic; use the owner suite ID for one exact case")
        return [case], [case] if selection["ignored"] else []
    if row["mode"] == "custom":
        available = list(row.get("expectedCustomCases", []))
        if case is not None and case not in available:
            raise LocalTestError("exact case is not registered by this custom harness")
        return ([case] if case is not None else available), []
    available = list(row.get("expectedCases", []))
    ignored_all = set(row.get("expectedIgnored", []))
    if case is not None:
        if case not in available:
            raise LocalTestError("exact case is not registered by this suite; substring filters are not accepted")
        return [case], [case] if case in ignored_all else []
    return [name for name in available if name not in ignored_all], []


def _angular_cases(data: dict) -> list[str]:
    rows = _rows(data)
    policy = data["processContracts"].get("angular-renderer")
    if not isinstance(policy, dict) or not policy.get("suiteIds"):
        raise LocalTestError("registered angular-renderer process contract is unavailable")
    cases: list[str] = []
    for key in policy["suiteIds"]:
        row = rows.get(key)
        if not isinstance(row, dict) or row.get("mode") != "libtest":
            raise LocalTestError("angular-renderer suite contract is unavailable")
        selected = list(row.get("expectedIgnored", []))
        if row["target"] == "latentd":
            selected = [name for name in selected if "actual_angular_http_" in name]
        if not selected:
            raise LocalTestError("angular-renderer suite has no registered prepared cases")
        cases.extend(selected)
    if len(cases) != len(set(cases)):
        raise LocalTestError("angular-renderer process contains duplicate cases")
    return cases


def _angular_component(repo: Path) -> Path:
    return repo / "examples/renderer-profile/dist/runtime/application.wasm"


def _angular_plan(repo: Path, data: dict, case: str | None, context: str,
                  inventory: Path | None) -> dict:
    if case is not None:
        raise LocalTestError("the angular-renderer process is an atomic registered integration; do not narrow it with --case")
    policy = data["processContracts"].get("angular-renderer")
    if not isinstance(policy, dict):
        raise LocalTestError("registered angular-renderer process contract is unavailable")
    rows = _rows(data)
    owners = [rows[key] for key in policy["suiteIds"]]
    recipes = {row["recipe"] for row in owners}
    if len(recipes) != 1:
        raise LocalTestError("angular-renderer owner recipes disagree")
    recipe_name = recipes.pop()
    recipe = data["recipes"].get(recipe_name)
    if not isinstance(recipe, dict) or not recipe.get("build"):
        raise LocalTestError("angular-renderer preparation recipe is unavailable")
    cases = _angular_cases(data)
    component = _angular_component(repo)
    private = component.parent / "renderer.wasm"
    inventory_state = inventory is not None and inventory.is_file() and not inventory.is_symlink()
    component_state = (component.is_file() and not component.is_symlink()
                       and private.is_file() and not private.is_symlink())
    state = "present" if inventory_state and component_state else "missing"
    prepared_path = str(inventory or Path("target/local-tests/angular-renderer.jsonl"))
    prepare_command = ["python3", "tools/test.py", "prepare", "--suite", ANGULAR_PROCESS,
                       "--inventory", prepared_path]
    run_command = ["python3", "tools/test.py", "run", "--suite", ANGULAR_PROCESS,
                   "--inventory", prepared_path]
    stable = {
        "suite": ANGULAR_PROCESS,
        "ownerSuites": policy["suiteIds"],
        "recipe": recipe_name,
        "recipeDefinition": recipe,
        "processContract": policy,
        "cases": cases,
        "runner": "run_angular_renderer_tests",
    }
    return {
        "schemaVersion": "latent.local-test-plan.v2",
        "suite": ANGULAR_PROCESS,
        "ownerSuite": list(policy["suiteIds"]),
        "selection": None,
        "purpose": data["boundaries"]["product"],
        "boundary": "product",
        "classification": "ordinary correctness",
        "resourceClass": "runtime-bounded",
        "platforms": policy["platforms"],
        "prerequisites": policy["prerequisites"],
        "recipe": recipe_name,
        "recipeDefinition": recipe,
        "preparation": {
            "state": state,
            "input": "source-matched Cargo inventory plus prepared Angular public/private renderer WASM",
            "buildCommand": recipe["build"],
            "commands": [
                ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                ["npm", "run", "build"],
                ["python3", "tools/build_angular_renderer.py"],
            ],
            "component": str(component.relative_to(repo)),
            "command": prepare_command,
        },
        "runner": "run_angular_renderer_tests",
        "mode": "process",
        "runSupported": True,
        "blocker": None,
        "cases": cases,
        "selectedIgnoredCases": list(cases),
        "requiredCaseCount": len(cases),
        "case": None,
        "runCommand": run_command,
        "cleanup": "remove only target/local-tests output and generated renderer-profile node_modules/dist when desired; the maintained runner owns test children",
        "timeoutSeconds": policy["timeoutSeconds"],
        "recipeIdentity": _hash(stable),
        "context": context,
    }


def plan_suite(repo: Path, key: str, case: str | None = None,
               context: str = "local", inventory: Path | None = None) -> dict:
    data = _data(repo)
    if key == ANGULAR_PROCESS:
        return _angular_plan(repo, data, case, context, inventory)
    data, row, selection, selection_name = _resolve(repo, key)
    cases, selected_ignored = _selected_cases(row, selection, case)
    recipe = data["recipes"].get(row["recipe"])
    if not isinstance(recipe, dict):
        raise LocalTestError("registered suite recipe is unavailable")
    runner = selection["runner"] if selection is not None else (
        "ci-suite-discovery" if row["mode"] != "custom" else "custom-owner")
    workspace_recipe = recipe.get("build")
    run_supported = row["mode"] == "libtest"
    blocker = None
    if row["mode"] == "compile-only":
        run_supported = False
        blocker = "compile-only suite has no executable correctness cases"
    elif row["mode"] == "custom":
        run_supported = False
        blocker = "custom harness keeps its registered owner; no libtest fallback is permitted"
    elif not cases:
        run_supported = False
        blocker = "all registered cases are opt-in; choose one exact --case or a registered selection"
    if selection is not None and runner not in {"ci_rust_artifacts"}:
        run_supported = False
        blocker = f"selection execution remains owned by {runner}; this entry point will not bypass its fixture/service owner"
    if selection_name == "browser-boundary":
        run_supported = False
        blocker = "browser-boundary needs renderer-lane browser/component preparation; use the maintained lane owner instead of a bare Cargo harness"
    resource_class = selection["resourceClass"] if selection is not None else row["resourceClass"]
    qualification = row["boundary"] == "qualification" or resource_class.startswith("physical")
    preparation_state = "not-provided"
    if inventory is not None:
        preparation_state = "present" if inventory.is_file() and not inventory.is_symlink() else "missing"
    prepared_path = str(inventory or Path("target/local-tests") / (key + ".jsonl"))
    prepare_command = ["python3", "tools/test.py", "prepare", "--suite", key]
    run_command = ["python3", "tools/test.py", "run", "--suite", key]
    if case is not None:
        prepare_command += ["--case", case]
        run_command += ["--case", case]
    prepare_command += ["--inventory", prepared_path]
    run_command += ["--inventory", prepared_path]
    stable = {
        "suite": key, "ownerSuite": row["id"], "selection": selection_name,
        "recipe": row["recipe"], "recipeDefinition": recipe, "mode": row["mode"],
        "cases": cases, "ignoredCases": selected_ignored, "runner": runner,
    }
    return {
        "schemaVersion": "latent.local-test-plan.v2",
        "suite": key,
        "ownerSuite": row["id"],
        "selection": selection_name,
        "purpose": data["boundaries"][row["boundary"]],
        "boundary": row["boundary"],
        "classification": "explicit qualification" if qualification else "ordinary correctness",
        "resourceClass": resource_class,
        "platforms": row["platforms"],
        "prerequisites": row["prerequisites"],
        "recipe": row["recipe"],
        "recipeDefinition": recipe,
        "preparation": {
            "state": preparation_state,
            "input": "successful source-matched Cargo artifact inventory",
            "buildCommand": workspace_recipe,
            "command": prepare_command,
        },
        "runner": runner,
        "mode": row["mode"],
        "runSupported": run_supported,
        "blocker": blocker,
        "cases": cases,
        "selectedIgnoredCases": selected_ignored,
        "requiredCaseCount": len(cases),
        "case": case,
        "runCommand": run_command,
        "cleanup": "remove only the local inventory/output you created; test owners retain responsibility for their private fixtures",
        "timeoutSeconds": selection["timeoutSeconds"] if selection else row["timeoutSeconds"],
        "recipeIdentity": _hash(stable),
        "context": context,
    }


def _safe_env() -> dict[str, str]:
    names = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "SystemRoot", "WINDIR",
             "TEMP", "TMP", "TMPDIR")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", LC_ALL="C",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_TERMINAL_PROMPT="0")
    return env


def _bridge(run: TestRun):
    def execute(args: list[str], *, cwd: Path, env: dict[str, str],
                timeout: int, maximum: int) -> tuple[int, bytes]:
        result = run.command(args, cwd=cwd, env=env, timeout=timeout, maximum=maximum, check=False)
        if result.returncode is None:
            raise ProcessFailure("assertion-failure", "child-exit-unobserved", result)
        return result.returncode, result.output
    return execute


def _generic_prepared(repo: Path, plan: dict, inventory: Path, run: TestRun | None = None):
    _, row, selection, _ = _resolve(repo, plan["suite"])
    group = discovery.Group(row["id"], row["manifest"], row["target"], row["kind"], row["source"])
    try:
        prepared = security.read_inventory(inventory, repo, (group,))[row["id"]]
    except (OSError, ValueError, TypeError, KeyError, artifacts.ArtifactError) as error:
        raise LocalTestError(f"prepared Cargo inventory is invalid: {error}") from None
    if run is not None:
        run.artifact("test-manifest", inventory, artifacts.MAX_INVENTORY_BYTES)
        run.artifact("test-executable", prepared.executable, 1024 * 1024 * 1024)
    base = dict(os.environ)
    try:
        environment = artifacts.cargo_environment(
            repo, prepared, base, execute=_bridge(run) if run is not None else None)
    except (OSError, ValueError, artifacts.ArtifactError, ProcessFailure) as error:
        if isinstance(error, ProcessFailure):
            raise
        raise LocalTestError(f"prepared Rust runtime is unavailable: {error}") from None
    if row["mode"] == "compile-only":
        return row, selection, prepared, environment, frozenset(), frozenset()
    if row["mode"] == "custom":
        if row.get("listContract") == "custom-list":
            if run is None:
                status, raw = artifacts.run_owned([str(prepared.executable), "--list"], cwd=prepared.package,
                                                  env=environment, timeout=30, maximum=1024 * 1024)
            else:
                result = run.command([str(prepared.executable), "--list"], cwd=prepared.package,
                                     env=environment, timeout=30, maximum=1024 * 1024, check=False)
                status, raw = result.returncode, result.output
            if status:
                raise LocalTestError("custom harness listing failed")
            discovery.validate_custom_listing(raw, row["expectedCustomCases"])
        return row, selection, prepared, environment, frozenset(), frozenset()
    listed = []
    for args in (["--list"], ["--ignored", "--list"]):
        if run is None:
            status, raw = artifacts.run_owned([str(prepared.executable), *args], cwd=prepared.package,
                                              env=environment, timeout=30, maximum=1024 * 1024)
        else:
            result = run.command([str(prepared.executable), *args], cwd=prepared.package,
                                 env=environment, timeout=30, maximum=1024 * 1024, check=False)
            status, raw = result.returncode, result.output
        if status:
            raise LocalTestError("prepared suite discovery failed")
        listed.append(security.listing(raw))
    available, ignored = listed
    try:
        discovery.validate_cases(row, available, ignored, _data(repo)["selections"])
    except (ValueError, artifacts.ArtifactError) as error:
        raise LocalTestError(f"prepared suite discovery changed: {error}") from None
    expected = set(plan["cases"])
    if not expected <= available:
        raise LocalTestError("prepared suite is missing one or more selected cases")
    ignored_selected = expected & ignored
    if ignored_selected != set(plan["selectedIgnoredCases"]):
        raise LocalTestError("prepared suite ignore state differs from the registered selection")
    return row, selection, prepared, environment, available, ignored


def _angular_groups(data: dict) -> tuple[discovery.Group, ...]:
    rows = _rows(data)
    policy = data["processContracts"]["angular-renderer"]
    return tuple(discovery.Group(rows[key]["id"], rows[key]["manifest"], rows[key]["target"],
                                 rows[key]["kind"], rows[key]["source"])
                 for key in policy["suiteIds"])


def _wasm_prepared(path: Path) -> bool:
    try:
        if not path.is_file() or path.is_symlink() or not 8 <= path.stat().st_size <= 32 * 1024 * 1024:
            return False
        with path.open("rb") as source:
            return source.read(4) == b"\\0asm"
    except OSError:
        return False


def _validate_angular_inventory(repo: Path, inventory: Path) -> dict:
    if not inventory.is_file() or inventory.is_symlink():
        raise LocalTestError("prepared Cargo inventory is missing; run the reported prepare command")
    try:
        return security.read_inventory(inventory, repo, _angular_groups(_data(repo)))
    except (OSError, ValueError, TypeError, KeyError, artifacts.ArtifactError) as error:
        raise LocalTestError(f"prepared Angular Cargo inventory is invalid: {error}") from None


def _validate_angular_assets(repo: Path) -> tuple[Path, Path]:
    component = _angular_component(repo)
    private = component.parent / "renderer.wasm"
    if not _wasm_prepared(component) or not _wasm_prepared(private):
        raise LocalTestError("prepared Angular public/private renderer WASM is missing or invalid; run the reported prepare command")
    return component, private


def validate_prepared(repo: Path, plan: dict, inventory: Path) -> None:
    if plan["suite"] == ANGULAR_PROCESS:
        _validate_angular_inventory(repo, inventory)
        _validate_angular_assets(repo)
        return
    if not inventory.is_file() or inventory.is_symlink():
        raise LocalTestError("prepared Cargo inventory is missing; run the reported prepare command")
    _generic_prepared(repo, plan, inventory)


def prerequisite_check(repo: Path, plan: dict, inventory: Path | None) -> dict:
    problems: list[str] = []
    if _platform() not in plan["platforms"]:
        problems.append(f"unsupported platform {_platform()}; supported: {', '.join(plan['platforms'])}")
    if plan["suite"] == ANGULAR_PROCESS:
        for tool in plan["prerequisites"]["tools"]:
            if shutil.which(tool) is None:
                problems.append(f"missing execution tool: {tool}")
        if inventory is None or not inventory.is_file() or inventory.is_symlink():
            problems.append("prepared Cargo inventory is missing")
        else:
            try:
                _validate_angular_inventory(repo, inventory)
            except LocalTestError as error:
                problems.append(str(error))
        try:
            _validate_angular_assets(repo)
        except LocalTestError as error:
            problems.append(str(error))
            for tool in ("cargo", "node", "npm", "wasm-tools"):
                if shutil.which(tool) is None:
                    problems.append(f"missing preparation tool: {tool}")
    elif inventory is None or not inventory.is_file() or inventory.is_symlink():
        problems.append("prepared Cargo inventory is missing")
    elif not problems:
        try:
            validate_prepared(repo, plan, inventory)
        except LocalTestError as error:
            problems.append(str(error))
    return {
        "suite": plan["suite"],
        "state": "ready" if not problems else "needs-preparation",
        "problems": problems,
        "prerequisites": plan["prerequisites"],
        "prepareCommand": plan["preparation"]["command"],
        "runSupported": plan["runSupported"],
        "blocker": plan["blocker"],
    }


def _prepare_inventory(repo: Path, plan: dict, inventory: Path, validator) -> bool:
    if inventory.exists():
        validator(repo, inventory)
        return True
    command = plan["preparation"]["buildCommand"]
    if not command:
        raise LocalTestError("this registered recipe has no Cargo artifact preparation command")
    if not shutil.which(command[0]):
        raise LocalTestError(f"missing preparation tool: {command[0]}")
    inventory.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["CARGO_TARGET_DIR"] = str((repo / "target").resolve())
    try:
        preparation_timeout = min(3600, max(1800, plan["timeoutSeconds"] * 2))
        result = run_bounded(command, repo, environment,
                             preparation_timeout, MAX_BUILD_OUTPUT)
    except BuildProcessError as error:
        raise LocalTestError(f"preparation process failed: {error}") from None
    if result.stderr:
        print(result.stderr.decode("utf-8", errors="replace")[-16000:], file=sys.stderr, end="")
    try:
        with inventory.open("xb") as destination:
            destination.write(result.stdout)
    except FileExistsError:
        raise LocalTestError("prepared inventory appeared concurrently; validate it before reuse") from None
    try:
        validator(repo, inventory)
    except Exception:
        try:
            inventory.unlink()
        except OSError:
            pass
        raise
    return False


def _validate_generic_inventory(repo: Path, inventory: Path, plan: dict) -> None:
    validate_prepared(repo, plan, inventory)


def _prepare_step(command: list[str], cwd: Path, environment: dict[str, str], timeout: int) -> None:
    if shutil.which(command[0]) is None:
        raise LocalTestError(f"missing preparation tool: {command[0]}")
    try:
        result = run_bounded(command, cwd, environment, timeout, MAX_BUILD_OUTPUT)
    except BuildProcessError as error:
        raise LocalTestError(f"preparation process failed: {error}") from None
    if result.stdout:
        print(result.stdout.decode("utf-8", errors="replace")[-16000:], end="")
    if result.stderr:
        print(result.stderr.decode("utf-8", errors="replace")[-16000:], file=sys.stderr, end="")


def _prepare_angular(repo: Path, plan: dict, inventory: Path) -> dict:
    inventory_reused = _prepare_inventory(repo, plan, inventory, _validate_angular_inventory)
    component = _angular_component(repo)
    private = component.parent / "renderer.wasm"
    component_valid = _wasm_prepared(component)
    private_valid = _wasm_prepared(private)
    assets_reused = component_valid and private_valid
    if not assets_reused:
        if component.exists() and not component_valid:
            raise LocalTestError("incompatible generated Angular application.wasm already exists; remove examples/renderer-profile/dist and prepare again")
        if private.exists() and not private_valid:
            raise LocalTestError("incompatible generated Angular renderer.wasm already exists; remove examples/renderer-profile/dist and prepare again")
        profile = repo / "examples/renderer-profile"
        environment = dict(os.environ)
        environment["CARGO_TARGET_DIR"] = str((repo / "target").resolve())
        _prepare_step(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                      profile, environment, 420)
        _prepare_step(["npm", "run", "build"], profile, environment, 420)
        _prepare_step([sys.executable, "tools/build_angular_renderer.py"], repo, environment, 900)
    validate_prepared(repo, plan, inventory)
    return {
        "suite": plan["suite"], "state": "prepared",
        "reused": inventory_reused and assets_reused,
        "inventory": str(inventory),
        "component": str(component),
        "buildCommand": plan["preparation"]["buildCommand"],
        "preparationCommands": plan["preparation"]["commands"],
    }


def prepare(repo: Path, plan: dict, inventory: Path) -> dict:
    if _platform() not in plan["platforms"]:
        raise LocalTestError(f"unsupported platform {_platform()}")
    if plan["suite"] == ANGULAR_PROCESS:
        return _prepare_angular(repo, plan, inventory)
    validator = lambda root, path: _validate_generic_inventory(root, path, plan)
    reused = _prepare_inventory(repo, plan, inventory, validator)
    return {"suite": plan["suite"], "state": "prepared", "reused": reused,
            "inventory": str(inventory), "buildCommand": plan["preparation"]["buildCommand"]}


def _execute_selection(run: TestRun, repo: Path, plan: dict, inventory: Path,
                       name: str) -> None:
    suite = artifacts.SUITES.get(name)
    if suite is None:
        raise ProcessFailure("invalid-fixture", "selection-is-not-owned-by-ci-rust-artifacts")
    if suite.platforms and sys.platform not in suite.platforms:
        raise ProcessFailure("unavailable-environment", "unsupported-suite-platform")
    if plan["case"] is not None and set(plan["cases"]) != set(suite.names):
        raise ProcessFailure("invalid-fixture", "registered-selection-cannot-be-broadened-or-narrowed")
    try:
        prepared = artifacts.read_inventory(inventory, repo, suite)
    except (OSError, ValueError, TypeError, artifacts.ArtifactError) as error:
        raise ProcessFailure("invalid-fixture", "prepared-cargo-artifact-invalid") from error
    run.artifact("test-manifest", inventory, artifacts.MAX_INVENTORY_BYTES)
    run.artifact("test-executable", prepared.executable, 1024 * 1024 * 1024)
    run.mark("execution")
    result = run.command(
        [sys.executable, "tools/ci_rust_artifacts.py",
         "--inventory", str(inventory), "--suite", name],
        cwd=repo, env=dict(os.environ), timeout=plan["timeoutSeconds"],
        maximum=artifacts.MAX_OUTPUT_BYTES, check=False,
    )
    print(result.output.decode("utf-8", errors="replace"), end="")
    if result.returncode:
        raise ProcessFailure("assertion-failure", "registered-selection-runner-failed", result)


def _execute_suite(run: TestRun, repo: Path, plan: dict, inventory: Path) -> None:
    row, selection, prepared, environment, available, ignored = _generic_prepared(
        repo, plan, inventory, run)
    if selection is not None:
        raise ProcessFailure("invalid-fixture", "unexpected-selection-owner")
    if row["mode"] != "libtest":
        raise ProcessFailure("unavailable-environment", "suite-execution-keeps-its-custom-or-compile-only-owner")
    run.mark("execution")
    if plan["case"] is not None:
        case = plan["case"]
        command = [str(prepared.executable), case, "--exact"]
        if case in ignored:
            command.append("--ignored")
        command.append("--test-threads=1")
        result = run.command(command, cwd=prepared.package, env=environment,
                             timeout=plan["timeoutSeconds"], maximum=artifacts.MAX_OUTPUT_BYTES,
                             check=False)
        print(result.output.decode("utf-8", errors="replace"), end="")
        if result.returncode:
            raise ProcessFailure("assertion-failure", "selected-test-failed", result)
        try:
            security.validate_result(result.output, case)
        except artifacts.ArtifactError as error:
            raise ProcessFailure("assertion-failure", str(error), result) from error
        return
    active = available - ignored
    if set(plan["cases"]) != set(active) or not active:
        raise ProcessFailure("invalid-fixture", "active-suite-selection-changed")
    resource = _data(repo)["resourceClasses"][row["resourceClass"]]["testThreads"]
    threads = resource if type(resource) is int else 1
    result = run.command([str(prepared.executable), f"--test-threads={threads}"],
                         cwd=prepared.package, env=environment,
                         timeout=plan["timeoutSeconds"], maximum=artifacts.MAX_OUTPUT_BYTES,
                         check=False)
    print(result.output.decode("utf-8", errors="replace"), end="")
    if result.returncode:
        raise ProcessFailure("assertion-failure", "selected-suite-failed", result)
    matches = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;",
                         result.output, re.MULTILINE)
    expected = [(str(len(active)).encode(), b"0", str(len(ignored)).encode())]
    if matches != expected:
        raise ProcessFailure("assertion-failure", "selected-suite-result-mismatch", result)


def _diagnostic_from_output(output: bytes) -> str | None:
    for line in reversed(output.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("suite") == "angular-renderer":
            diagnostic = value.get("diagnostic")
            if isinstance(diagnostic, str):
                return diagnostic
    return None


def _execute_angular_process(repo: Path, plan: dict, inventory: Path,
                             fault: str | None) -> tuple[int, dict]:
    validate_prepared(repo, plan, inventory)
    command = [
        sys.executable, "tools/run_angular_renderer_tests.py",
        "--test-manifest", str(inventory),
        "--component", str(_angular_component(repo)),
        "--diagnostic-root", str(repo / "target/test-diagnostics"),
    ]
    if fault is not None:
        command += ["--inject-failure", fault]
    try:
        result = owned_run(
            command, cwd=repo, env=dict(os.environ),
            timeout=plan["timeoutSeconds"] + 30, maximum=8 * 1024 * 1024,
        )
    except ProcessFailure as error:
        code = {
            "unavailable-environment": 3,
            "cancelled": 130,
            "infrastructure-timeout": 124,
            "output-overflow": 125,
        }.get(error.category, 1)
        return code, {
            "schemaVersion": FAILURE_SCHEMA,
            "suite": ANGULAR_PROCESS,
            "outcome": "not-run" if error.category == "unavailable-environment" else "failed",
            "category": error.category,
            "reason": error.reason,
        }
    print(result.output.decode("utf-8", errors="replace"), end="")
    code = result.returncode if result.returncode is not None and result.returncode >= 0 else (
        128 - result.returncode if result.returncode is not None else 1)
    return code, {
        "schemaVersion": "latent.local-test-result.v1",
        "suite": ANGULAR_PROCESS,
        "outcome": "passed" if code == 0 else "failed",
        "fault": fault,
        "diagnostic": _diagnostic_from_output(result.output),
    }


def execute(repo: Path, plan: dict, inventory: Path,
            fault: str | None = None) -> tuple[int, dict]:
    if not plan["runSupported"]:
        raise LocalTestError(plan["blocker"] or "registered suite is not executable through this entry point")
    if _platform() not in plan["platforms"]:
        raise LocalTestError(f"unsupported platform {_platform()}; supported: {', '.join(plan['platforms'])}")
    if plan["suite"] == ANGULAR_PROCESS:
        return _execute_angular_process(repo, plan, inventory, fault)
    if fault is not None:
        raise LocalTestError("--fault is supported only by process.angular-renderer")
    reproduction = {
        "suite": plan["suite"], "cases": plan["cases"], "recipe": plan["recipe"],
        "mode": plan["mode"],
    }
    run = TestRun(plan["suite"], {"timeoutSeconds": plan["timeoutSeconds"]}, repo=repo,
                  reproduction=reproduction)
    captured = io.StringIO()
    error: BaseException | None = None
    try:
        with redirect_stdout(captured):
            with run:
                run.source_identity()
                if plan["selection"] is not None:
                    _execute_selection(run, repo, plan, inventory, plan["selection"])
                else:
                    _execute_suite(run, repo, plan, inventory)
    except BaseException as caught:
        error = caught
    diagnostics = captured.getvalue()
    if diagnostics:
        print(diagnostics, file=sys.stderr, end="")
    record = run.record or {
        "schemaVersion": FAILURE_SCHEMA, "suite": plan["suite"],
        "outcome": "failed", "category": "assertion-failure",
        "reason": type(error).__name__ if error else "missing-run-record",
    }
    if error is None:
        return 0, record
    if isinstance(error, ProcessFailure):
        code = {
            "unavailable-environment": 3,
            "cancelled": 130,
            "infrastructure-timeout": 124,
            "output-overflow": 125,
        }.get(error.category, 1)
        return code, record
    if isinstance(error, KeyboardInterrupt):
        return 130, record
    if isinstance(error, LocalTestError):
        return error.code, record
    return 1, record


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise LocalTestError("duplicate failure-record key")
        value[key] = item
    return value


def read_failure(path: Path) -> dict:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPORT:
            raise LocalTestError("failure record must be a bounded regular file")
        with path.open("rb") as source:
            raw = source.read(MAX_REPORT + 1)
    except OSError:
        raise LocalTestError("failure record is unavailable") from None
    if len(raw) > MAX_REPORT:
        raise LocalTestError("failure record exceeds the bounded diagnostic size")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise LocalTestError("failure record is not valid bounded JSON") from None
    if not isinstance(value, dict) or value.get("schemaVersion") != FAILURE_SCHEMA:
        raise LocalTestError("unsupported failure record; expected latent.test-run.v1")
    if set(value) - REPORT_KEYS:
        raise LocalTestError("failure record contains unknown fields")
    reproduction = value.get("reproduction")
    if not isinstance(reproduction, dict) or set(reproduction) - REPRODUCTION_KEYS:
        raise LocalTestError("failure record has an unsafe reproduction selection")
    if value.get("outcome") not in {"failed", "not-run"}:
        raise LocalTestError("only a failed or not-run diagnostic can be reproduced")
    suite = reproduction.get("suite")
    cases = reproduction.get("cases")
    recipe = reproduction.get("recipe")
    if not isinstance(suite, str) or not isinstance(cases, list) or not cases or not isinstance(recipe, str):
        raise LocalTestError("failure record lacks an exact suite/case/recipe selection")
    if len(cases) > 256 or len(cases) != len(set(cases)) or not all(isinstance(case, str) for case in cases):
        raise LocalTestError("failure record case selection is invalid")
    return value


def _source(repo: Path) -> dict:
    env = _safe_env()
    try:
        status, head = artifacts.run_owned(
            ["git", "--no-optional-locks", "-c", "gc.auto=0", "rev-parse", "--verify", "HEAD"],
            cwd=repo, env=env, timeout=15, maximum=256)
        if status:
            raise LocalTestError("Git source identity is unavailable")
        revision = head.decode("ascii").strip()
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision) is None:
            raise LocalTestError("Git source identity is invalid")
        status, dirty = artifacts.run_owned(
            ["git", "--no-optional-locks", "-c", "gc.auto=0", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo, env=env, timeout=15, maximum=65536)
        if status:
            raise LocalTestError("Git source state is unavailable")
        return {"revision": revision, "dirty": bool(dirty.strip()), "observed": True}
    except (OSError, artifacts.ArtifactError, UnicodeError):
        raise LocalTestError("Git source identity is unavailable") from None


def _fixture_digest(path: Path, maximum: int) -> str:
    try:
        return file_digest(path, maximum)
    except (OSError, ProcessFailure):
        raise LocalTestError("prepared fixture identity is unavailable") from None


def _angular_fixture_identities(repo: Path, inventory: Path) -> dict[str, str]:
    prepared = _validate_angular_inventory(repo, inventory)
    component, private = _validate_angular_assets(repo)
    identities = {
        "test-manifest": _fixture_digest(inventory, artifacts.MAX_INVENTORY_BYTES),
        "component": _fixture_digest(component, 32 * 1024 * 1024),
        "private-renderer": _fixture_digest(private, 32 * 1024 * 1024),
    }
    for role, artifact in prepared.items():
        identities[role] = _fixture_digest(artifact.executable, 1024 * 1024 * 1024)
    return identities


def _source_match(repo: Path, reproduction: dict, allow_changed: bool) -> bool:
    current = _source(repo)
    recorded_source = reproduction.get("source")
    exact = (isinstance(recorded_source, dict)
             and recorded_source.get("observed") is True
             and recorded_source.get("dirty") is False
             and current.get("dirty") is False
             and recorded_source.get("revision") == current.get("revision"))
    if not exact and not allow_changed:
        raise LocalTestError("source checkout is not an exact reproduction; pass --allow-changed-checkout for a labelled rerun")
    return exact


def reproduce(repo: Path, report: Path, inventory: Path, allow_changed: bool) -> tuple[int, dict]:
    record = read_failure(report)
    reproduction = record["reproduction"]
    cases = reproduction["cases"]
    angular = reproduction["suite"] == "angular-renderer"
    key = ANGULAR_PROCESS if angular else reproduction["suite"]
    case = None if angular or len(cases) != 1 else cases[0]
    plan = plan_suite(repo, key, case, inventory=inventory)
    validate_prepared(repo, plan, inventory)
    if plan["cases"] != cases or plan["recipe"] != reproduction["recipe"]:
        raise LocalTestError("recorded suite/case/recipe no longer matches the registered contract")
    fixtures = reproduction.get("fixtures")
    if not isinstance(fixtures, dict):
        raise LocalTestError("failure record has no prepared fixture identities")
    manifest_identity = _fixture_digest(inventory, artifacts.MAX_INVENTORY_BYTES)
    if fixtures.get("test-manifest") != manifest_identity:
        raise LocalTestError("prepared artifact inventory does not match the recorded failure")
    if angular:
        current_fixtures = _angular_fixture_identities(repo, inventory)
        for role, identity in current_fixtures.items():
            if fixtures.get(role) != identity:
                raise LocalTestError(f"prepared Angular fixture {role} does not match the recorded failure")
    elif "test-executable" in fixtures:
        _, _, prepared, _, _, _ = _generic_prepared(repo, plan, inventory)
        if fixtures["test-executable"] != _fixture_digest(prepared.executable, 1024 * 1024 * 1024):
            raise LocalTestError("prepared test executable does not match the recorded failure")
    exact = _source_match(repo, reproduction, allow_changed)
    fault = None
    if angular:
        recorded_fault = reproduction.get("fault", "none")
        if recorded_fault not in {"none", "after-discovery"}:
            raise LocalTestError("failure record contains an unsupported Angular fault selector")
        fault = None if recorded_fault == "none" else recorded_fault
    code, result = execute(repo, plan, inventory, fault=fault)
    return code, {"reproduction": "same-input-selection" if exact else "changed-input-rerun",
                  "result": result}


def delegate(repo: Path, command: str, args: argparse.Namespace) -> int:
    if command == "preview":
        path = repo / "tools/preview_ci.py"
        if not path.is_file():
            raise LocalTestError("optional prerequisite #339 is not available: tools/preview_ci.py")
        argv = ["--base", args.base]
        argv += ["--worktree"] if args.worktree else ["--head", args.head]
        argv += ["--output", args.output]
    else:
        path = repo / "tools/check_tool_versions.py"
        if not path.is_file():
            raise LocalTestError("optional prerequisite #338 is not available: tools/check_tool_versions.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scoped = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr == "add_argument"
                     and any(isinstance(value, ast.Constant) and value.value == "--scope" for value in node.args)
                     for node in ast.walk(tree))
        if not scoped:
            raise LocalTestError("optional prerequisite #338 has no scoped interface; refusing an all-SDK fallback")
        argv = ["--scope", args.scope, "--report-all", "--output", args.output]
    status, output = artifacts.run_owned([sys.executable, str(path), *argv], cwd=repo,
                                         env=_safe_env(), timeout=120, maximum=MAX_REPORT)
    print(output.decode("utf-8", errors="replace"), end="")
    return status if status >= 0 else min(255, 128 - status)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = result.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", allow_abbrev=False)
    listing.add_argument("--output", choices=("human", "json"), default="human")
    for name in ("explain", "plan", "check"):
        child = commands.add_parser(name, allow_abbrev=False)
        child.add_argument("--suite", required=True)
        child.add_argument("--case")
        child.add_argument("--inventory", type=Path)
        child.add_argument("--context", choices=("local", "ci"), default="local")
        child.add_argument("--output", choices=("human", "json"), default="human")
    for name in ("prepare", "run"):
        child = commands.add_parser(name, allow_abbrev=False)
        child.add_argument("--suite", required=True)
        child.add_argument("--case")
        child.add_argument("--inventory", type=Path, required=True)
        child.add_argument("--context", choices=("local", "ci"), default="local")
        if name == "run":
            child.add_argument("--fault", choices=("after-discovery",))
        child.add_argument("--output", choices=("human", "json"), default="human")
    replay = commands.add_parser("reproduce", allow_abbrev=False)
    replay.add_argument("report", type=Path)
    replay.add_argument("--inventory", type=Path, required=True)
    replay.add_argument("--allow-changed-checkout", action="store_true")
    replay.add_argument("--output", choices=("human", "json"), default="human")
    preview = commands.add_parser("preview", allow_abbrev=False)
    preview.add_argument("--base", required=True)
    group = preview.add_mutually_exclusive_group()
    group.add_argument("--head", default="HEAD")
    group.add_argument("--worktree", action="store_true")
    preview.add_argument("--output", choices=("human", "json"), default="human")
    doctor = commands.add_parser("doctor", allow_abbrev=False)
    doctor.add_argument("--scope", choices=("all", "python", "go", "typescript", "java", "dotnet", "c"), required=True)
    doctor.add_argument("--output", choices=("human", "json"), default="human")
    return result


def emit(value: object, output: str) -> None:
    if output == "json":
        print(json.dumps(value, sort_keys=True))
    else:
        print(json.dumps(value, sort_keys=True, indent=2))


def main(argv: list[str] | None = None, *, repo: Path = REPO) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in {"preview", "doctor"}:
            return delegate(repo, args.command, args)
        if args.command == "list":
            emit([plan_suite(repo, key) for key in identities(repo)], args.output)
            return 0
        if args.command == "reproduce":
            inventory = _inventory_path(repo, args.inventory)
            code, result = reproduce(repo, args.report, inventory, args.allow_changed_checkout)
            emit(result, args.output)
            return code
        inventory = _inventory_path(repo, args.inventory)
        plan = plan_suite(repo, args.suite, args.case, args.context, inventory)
        if args.command in {"plan", "explain"}:
            emit(plan, args.output)
            return 0
        if args.command == "check":
            result = prerequisite_check(repo, plan, inventory)
            emit(result, args.output)
            return 0 if result["state"] == "ready" else 3
        if args.command == "prepare":
            result = prepare(repo, plan, inventory)
            emit(result, args.output)
            return 0
        code, result = execute(repo, plan, inventory, fault=getattr(args, "fault", None))
        emit(result, args.output)
        return code
    except LocalTestError as error:
        emit({"state": error.state, "reason": str(error), "exitCode": error.code}, args.output)
        return error.code
    except (OSError, ValueError, TypeError, KeyError, RecursionError, artifacts.ArtifactError) as error:
        emit({"state": "not-run", "reason": f"invalid or unavailable local inputs: {error}",
              "exitCode": 3}, args.output)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

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
from tools.build_process import BuildProcessError, run_bounded_result as run_bounded
from tools.owned_test_process import run_owned as owned_run
from tools.test_run import FAILURE_SCHEMA, ProcessFailure, TestRun, case_digest, digest as file_digest, redact

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
    "requiredCaseCount", "completedCaseCount", "completedCaseDigest",
}
REPRODUCTION_KEYS = {
    "suite", "cases", "recipe", "mode", "web", "observed", "fixtureOnly",
    "preflight", "fault", "source", "fixtures", "recipeIdentity",
    "caseSelection", "caseSetDigest", "requiredCaseCount",
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
    try:
        return [case for cases in registry.process_cases(data, "angular-renderer").values() for case in cases]
    except (KeyError, TypeError, ValueError) as error:
        raise LocalTestError(f"registered angular-renderer case contract is unavailable: {error}") from None



def _target_root(repo: Path) -> Path:
    target = Path(os.environ.get("CARGO_TARGET_DIR", str(repo / "target")))
    if not target.is_absolute():
        target = repo / target
    target = target.resolve()
    if target == repo.resolve() or target == Path(target.anchor):
        raise LocalTestError("CARGO_TARGET_DIR must identify a dedicated generated-output directory")
    return target


def _fixture_path(repo: Path, value: str) -> Path:
    if value.startswith("{target}/"):
        return _target_root(repo) / value.removeprefix("{target}/")
    return repo / value


def _fixtures_for(repo: Path, plan: dict) -> dict[str, dict]:
    data = _data(repo)
    owner = (data["processContracts"]["angular-renderer"] if plan["suite"] == ANGULAR_PROCESS
             else _rows(data)[plan["ownerSuite"]])
    return registry.fixture_recipes(data, owner, plan["cases"])


def _fixture_environment(repo: Path, plan: dict) -> dict[str, str]:
    return {spec["environment"]: str(_fixture_path(repo, spec["path"]))
            for recipe in _fixtures_for(repo, plan).values() for spec in recipe["outputs"].values()
            if "environment" in spec}


def _fixture_presence(repo: Path, recipes: dict[str, dict]) -> bool:
    return all((path := _fixture_path(repo, spec["path"])).is_file() and not path.is_symlink()
               for recipe in recipes.values() for spec in recipe["outputs"].values())


def _validate_fixture_recipe(repo: Path, name: str, recipe: dict) -> dict[str, str]:
    identities = {}
    documents = {}
    for role, spec in recipe["outputs"].items():
        path = _fixture_path(repo, spec["path"])
        if not path.is_file() or path.is_symlink():
            raise LocalTestError(f"prepared fixture is missing or linked: {role}")
        try:
            identities[role] = file_digest(path, spec["maximumBytes"])
            if spec["kind"] == "wasm":
                if not _wasm_prepared(path):
                    raise LocalTestError(f"prepared WASM fixture is invalid: {role}")
            else:
                # All JSON fixture inputs have small committed per-role limits.
                with path.open("rb") as source:
                    raw = source.read(spec["maximumBytes"] + 1)
                if (len(raw) > spec["maximumBytes"]
                        or "sha256:" + hashlib.sha256(raw).hexdigest() != identities[role]):
                    raise LocalTestError(f"prepared JSON fixture changed while reading: {role}")
                documents[role] = json.loads(raw, object_pairs_hook=_unique_object)
                if not isinstance(documents[role], dict):
                    raise LocalTestError(f"prepared JSON fixture is invalid: {role}")
        except (OSError, ValueError, ProcessFailure) as error:
            if isinstance(error, LocalTestError):
                raise
            raise LocalTestError(f"prepared fixture is unreadable or incompatible: {role}") from None
    if name == "echo-capsule":
        component = identities["echo-component"]
        if (documents["echo-capsule"].get("component", {}).get("digest") != component
                or documents["echo-build"].get("contentDigest") != component):
            raise LocalTestError("prepared echo component, capsule and build identities disagree")
    return identities


def _fixture_identities(repo: Path, plan: dict) -> dict[str, str]:
    identities = {}
    for name, recipe in _fixtures_for(repo, plan).items():
        identities.update(_validate_fixture_recipe(repo, name, recipe))
    return identities


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
    fixtures = registry.fixture_recipes(data, policy, cases)
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
            "commands": [step["argv"] for fixture in fixtures.values() for step in fixture["commands"]],
            "fixtureRecipes": fixtures,
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
        "recipeIdentity": registry.process_recipe_identity(data, "angular-renderer"),
        "context": context,
        "targetDirectory": str(_target_root(repo)),
    }



def plan_suite(repo: Path, key: str, case: str | None = None,
               context: str = "local", inventory: Path | None = None) -> dict:
    if context not in {"local", "ci"}:
        raise LocalTestError("unknown execution context")
    data = _data(repo)
    if key == ANGULAR_PROCESS:
        return _angular_plan(repo, data, case, context, inventory)
    data, row, selection, selection_name = _resolve(repo, key)
    cases, selected_ignored = _selected_cases(row, selection, case)
    # An owner ID must not bypass a named probe's resource, observation or
    # provider-lifecycle contract. A single-case owned selection can be delegated
    # unchanged; an atomic multi-case/service selection cannot be narrowed here.
    overlaps = [(name, selected) for name, selected in data["selections"].items()
                if selected["suite"] == row["id"] and set(cases).intersection(selected["names"])]
    if selection is None and case is not None:
        owned = [(name, selected) for name, selected in overlaps
                 if selected["names"] == [case] and selected.get("executionOnly") is True]
        if len(owned) == 1:
            selection_name, selection = owned[0]
    recipe = data["recipes"].get(row["recipe"])
    if not isinstance(recipe, dict):
        raise LocalTestError("registered suite recipe is unavailable")
    fixtures = registry.fixture_recipes(data, row, cases)
    runner = selection["runner"] if selection is not None else (
        "ci-suite-discovery" if row["mode"] != "custom" else "custom-owner")
    run_supported = row["mode"] == "libtest"
    blocker = None
    if row["mode"] == "compile-only":
        run_supported, blocker = False, "compile-only suite has no executable correctness cases"
    elif row["mode"] == "custom":
        run_supported, blocker = False, "custom harness keeps its registered owner; no libtest fallback is permitted"
    elif not cases:
        run_supported, blocker = False, "all registered cases are opt-in; choose one exact --case or a registered selection"
    elif selection is not None and (runner != "ci_rust_artifacts" or selection.get("executionOnly") is not True):
        run_supported = False
        blocker = f"selection execution remains owned by {runner}; its fixture/service preparation is not an execution-only local contract"
    elif selection is None and not fixtures and (row["boundary"] != "host" or selected_ignored):
        run_supported = False
        blocker = "this runtime/opt-in suite requires its maintained prepared-input owner; a bare harness could build or omit prerequisites"
    if selection is None and case is not None and overlaps and not fixtures:
        if any(selected.get("executionOnly") is not True for _, selected in overlaps):
            run_supported = False
            blocker = "the exact case belongs to an owned fixture/service selection; selecting its Cargo owner does not bypass that contract"
    resource_class = selection["resourceClass"] if selection is not None else row["resourceClass"]
    qualification = row["boundary"] == "qualification" or resource_class.startswith("physical")
    # Preserve a sensitive case's classification even when execution is blocked.
    if any(selected["resourceClass"].startswith("physical") for _, selected in overlaps):
        qualification = True
    preparation_state = "not-provided"
    if inventory is not None:
        preparation_state = ("present" if inventory.is_file() and not inventory.is_symlink()
                             and _fixture_presence(repo, fixtures) else "missing")
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
        "fixtureRecipes": fixtures, "resourceClass": resource_class,
        "executionSelection": selection,
    }
    return {
        "schemaVersion": "latent.local-test-plan.v2", "suite": key, "ownerSuite": row["id"],
        "selection": selection_name, "purpose": data["boundaries"][row["boundary"]],
        "boundary": row["boundary"],
        "classification": "explicit qualification" if qualification else "ordinary correctness",
        "resourceClass": resource_class, "platforms": row["platforms"],
        "prerequisites": row["prerequisites"], "recipe": row["recipe"], "recipeDefinition": recipe,
        "preparation": {
            "state": preparation_state,
            "input": "successful same-checkout Cargo artifact inventory and registered immutable fixtures",
            "buildCommand": recipe.get("build"),
            "fixtureRecipes": fixtures,
            "commands": [step["argv"] for fixture in fixtures.values() for step in fixture["commands"]],
            "command": prepare_command,
        },
        "runner": runner, "mode": row["mode"], "runSupported": run_supported, "blocker": blocker,
        "cases": cases, "selectedIgnoredCases": selected_ignored, "requiredCaseCount": len(cases),
        "case": case, "runCommand": run_command,
        "cleanup": "remove only the local inventory and generated fixture outputs you created; the maintained runner owns its test children",
        "timeoutSeconds": selection["timeoutSeconds"] if selection else row["timeoutSeconds"],
        "recipeIdentity": _hash(stable), "context": context,
        "targetDirectory": str(_target_root(repo)),
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
        prepared = security.read_inventory(inventory, repo, (group,), target=_target_root(repo))[row["id"]]
        artifacts.validate_recipe(inventory, repo, [row], plan["recipeDefinition"])
        if not os.access(prepared.executable, os.X_OK):
            raise LocalTestError("prepared test executable is not executable")
    except (OSError, ValueError, TypeError, KeyError, artifacts.ArtifactError) as error:
        raise LocalTestError(f"prepared Cargo inventory is invalid: {error}") from None
    # Read-only checks must not launch even `--list`: reproduction identities and
    # source checks precede any executable supplied by an artifact inventory.
    if run is None:
        return row, selection, prepared, {}, frozenset(), frozenset()
    run.artifact("test-manifest", inventory, artifacts.MAX_INVENTORY_BYTES)
    run.artifact("test-executable", prepared.executable, 1024 * 1024 * 1024)
    environment = run.execution_environment(dict(
        os.environ, CARGO_TARGET_DIR=str(_target_root(repo)),
        **_fixture_environment(repo, plan)))
    environment.update(TMPDIR=str(run.root), TMP=str(run.root), TEMP=str(run.root))
    try:
        environment = artifacts.cargo_environment(
            repo, prepared, environment, execute=_bridge(run), target=_target_root(repo))
    except (OSError, ValueError, artifacts.ArtifactError) as error:
        raise ProcessFailure("unavailable-environment", "prepared-rust-runtime-unavailable") from error
    if row["mode"] != "libtest":
        return row, selection, prepared, environment, frozenset(), frozenset()
    run.mark("discovery")
    listed = []
    for args in (["--list"], ["--ignored", "--list"]):
        result = run.command([str(prepared.executable), *args], cwd=prepared.package,
                             env=environment, timeout=30, maximum=artifacts.MAX_LIST_BYTES,
                             check=False)
        if result.returncode:
            raise ProcessFailure("assertion-failure", "prepared-suite-discovery-failed", result)
        listed.append(security.listing(result.output))
    available, ignored = listed
    try:
        discovery.validate_cases(row, available, ignored, _data(repo)["selections"])
    except (ValueError, artifacts.ArtifactError) as error:
        raise ProcessFailure("invalid-fixture", "prepared-suite-discovery-changed") from error
    expected = set(plan["cases"])
    if not expected <= available or expected & ignored != set(plan["selectedIgnoredCases"]):
        raise ProcessFailure("invalid-fixture", "prepared-suite-selection-changed")
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
            return source.read(4) == b"\0asm"
    except OSError:
        return False


def _validate_angular_inventory(repo: Path, inventory: Path) -> dict:
    if not inventory.is_file() or inventory.is_symlink():
        raise LocalTestError("prepared Cargo inventory is missing; run the reported prepare command")
    try:
        prepared = security.read_inventory(
            inventory, repo, _angular_groups(_data(repo)), target=_target_root(repo))
        data = _data(repo)
        rows = [_rows(data)[key] for key in prepared]
        artifacts.validate_recipe(inventory, repo, rows, data["recipes"][rows[0]["recipe"]])
        if not all(os.access(item.executable, os.X_OK) for item in prepared.values()):
            raise LocalTestError("prepared Angular test executable is not executable")
        return prepared
    except (OSError, ValueError, TypeError, KeyError, artifacts.ArtifactError) as error:
        raise LocalTestError(f"prepared Angular Cargo inventory is invalid: {error}") from None


def _validate_angular_assets(repo: Path) -> tuple[Path, Path]:
    component = _angular_component(repo)
    private = component.parent / "renderer.wasm"
    if not _wasm_prepared(component) or not _wasm_prepared(private):
        raise LocalTestError("prepared Angular public/private renderer WASM is missing or invalid; run the reported prepare command")
    return component, private


def validate_prepared(repo: Path, plan: dict, inventory: Path) -> None:
    import shlex
    hint = shlex.join(plan["preparation"]["command"])
    try:
        if not inventory.is_file() or inventory.is_symlink():
            raise LocalTestError("prepared Cargo inventory is missing or linked")
        if plan["suite"] == ANGULAR_PROCESS:
            _validate_angular_inventory(repo, inventory)
        else:
            _generic_prepared(repo, plan, inventory)
        _fixture_identities(repo, plan)
    except LocalTestError as error:
        raise LocalTestError(f"{error}; prepare with: {hint}") from None


def prerequisite_check(repo: Path, plan: dict, inventory: Path | None) -> dict:
    problems: list[str] = []
    if _platform() not in plan["platforms"]:
        problems.append(f"unsupported platform {_platform()}; supported: {', '.join(plan['platforms'])}")
    if not plan["runSupported"]:
        problems.append(plan["blocker"])
    # These are existence checks, not a substitute for the scoped version doctor.
    execution_tools = {"git", "rustc"}
    if plan["suite"] == ANGULAR_PROCESS:
        execution_tools.update(plan["prerequisites"]["tools"])
    for tool in sorted(execution_tools):
        if shutil.which(tool) is None:
            problems.append(f"missing execution tool: {tool}")
    if inventory is None:
        problems.append("prepared Cargo inventory is missing")
    else:
        try:
            validate_prepared(repo, plan, inventory)
        except LocalTestError as error:
            problems.append(str(error))
    preparation_tools = {plan["preparation"]["buildCommand"][0]} if plan["preparation"]["buildCommand"] else set()
    for recipe in _fixtures_for(repo, plan).values():
        preparation_tools.update(recipe["tools"])
    return {
        "suite": plan["suite"], "state": "ready" if not problems else "needs-preparation",
        "problems": problems, "prerequisites": plan["prerequisites"],
        "missingPreparationTools": sorted(tool for tool in preparation_tools if shutil.which(tool) is None),
        "prepareCommand": plan["preparation"]["command"], "runSupported": plan["runSupported"],
        "blocker": plan["blocker"],
        "validation": "read-only artifact checks; exact harness discovery occurs inside the owned run",
    }


def _prepare_inventory(repo: Path, plan: dict, inventory: Path, validator) -> bool:
    if inventory.is_symlink():
        raise LocalTestError("prepared inventory must not be a symlink")
    if inventory.exists():
        validator(repo, inventory)
        return True
    command = plan["preparation"]["buildCommand"]
    if not command:
        raise LocalTestError("this registered recipe has no Cargo artifact preparation command")
    destination = inventory.parent.resolve() / inventory.name
    if destination.is_relative_to(repo.resolve()) and not destination.is_relative_to(_target_root(repo)):
        raise LocalTestError("an in-checkout inventory must be inside the generated target directory")
    inventory.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, CARGO_TARGET_DIR=str(_target_root(repo)))
    result = _prepare_step(command, repo, environment,
                           min(3600, max(1800, plan["timeoutSeconds"] * 2)))
    try:
        with inventory.open("xb") as destination:
            destination.write(result.stdout)
    except FileExistsError:
        raise LocalTestError("prepared inventory appeared concurrently; validate it before reuse") from None
    try:
        validator(repo, inventory)
    except BaseException:
        inventory.unlink(missing_ok=True)
        raise
    return False


def _validate_generic_inventory(repo: Path, inventory: Path, plan: dict) -> None:
    _generic_prepared(repo, plan, inventory)


def _prepare_step(command: list[str], cwd: Path, environment: dict[str, str], timeout: int):
    if shutil.which(command[0]) is None:
        raise LocalTestError(f"missing preparation tool: {command[0]}")
    try:
        result = run_bounded(command, cwd, environment, timeout, MAX_BUILD_OUTPUT)
    except BuildProcessError as error:
        code = {"command-deadline": 124, "command-output-limit": 125}.get(error.reason, 1)
        raise LocalTestError(f"preparation process failed: {error.reason}", code, "failed") from None
    secrets = tuple(value for key, value in environment.items()
                    if re.search(r"(?i)(secret|password|token|credential|api.?key)", key) and len(value) >= 4)
    if result.stderr:
        print(redact(result.stderr.decode("utf-8", errors="replace"), secrets=secrets)[-16000:],
              file=sys.stderr, end="")
    if result.returncode:
        if result.stdout:
            print(redact(result.stdout.decode("utf-8", errors="replace"), secrets=secrets)[-16000:],
                  file=sys.stderr, end="")
        raise LocalTestError("preparation command exited unsuccessfully",
                             _exit_code(result.returncode), "failed")
    return result


def _prepare_angular(repo: Path, plan: dict, inventory: Path) -> dict:
    # The same fixture recipe dispatcher is used for runtime and Angular inputs.
    return _prepare_registered(repo, plan, inventory)


def prepare(repo: Path, plan: dict, inventory: Path) -> dict:
    if _platform() not in plan["platforms"]:
        raise LocalTestError(f"unsupported platform {_platform()}")
    if not plan["runSupported"]:
        raise LocalTestError(plan["blocker"] or "selection has no maintained execution-only owner")
    return _prepare_registered(repo, plan, inventory)


def _execute_selection(run: TestRun, repo: Path, plan: dict, inventory: Path, name: str) -> None:
    suite = artifacts.SUITES.get(name)
    if suite is None or set(plan["cases"]) != set(suite.names):
        raise ProcessFailure("invalid-fixture", "registered-selection-cannot-be-broadened-or-narrowed")
    # Use the maintained owner directly. Its CLI needs Actions source metadata;
    # a local run instead observes Git through TestRun, without inventing GITHUB_SHA.
    environment = run.execution_environment(dict(
        os.environ, CARGO_TARGET_DIR=str(_target_root(repo)), **_fixture_environment(repo, plan)))
    environment.update(TMPDIR=str(run.root), TMP=str(run.root), TEMP=str(run.root))
    run.mark("execution")
    try:
        artifacts.run_suite(repo, inventory, suite, environment,
                            execute=_bridge(run), target=_target_root(repo))
    except artifacts.ArtifactError as error:
        raise ProcessFailure("assertion-failure", str(error), run.last) from error
    run.complete_cases(plan["cases"])


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
        if result.returncode:
            raise ProcessFailure("assertion-failure", "selected-test-failed", result)
        try:
            security.validate_result(result.output, case)
        except artifacts.ArtifactError as error:
            raise ProcessFailure("assertion-failure", str(error), result) from error
        run.complete_cases([case])
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
    if result.returncode:
        raise ProcessFailure("assertion-failure", "selected-suite-failed", result)
    matches = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;",
                         result.output, re.MULTILINE)
    expected = [(str(len(active)).encode(), b"0", str(len(ignored)).encode())]
    if matches != expected:
        raise ProcessFailure("assertion-failure", "selected-suite-result-mismatch", result)
    # A matching summary alone must not hide duplicated/missing named results.
    outcomes = [line for line in result.output.decode("utf-8", errors="strict").splitlines()
                if line.startswith("test ") and not line.startswith("test result:")]
    passed = [line[5:-7] for line in outcomes if line.endswith(" ... ok")]
    if len(passed) != len(active) or set(passed) != set(active):
        raise ProcessFailure("assertion-failure", "selected-suite-case-results-mismatch", result)
    run.complete_cases(plan["cases"])


def _test_run_summary(output: bytes) -> dict | None:
    summaries = []
    for line in output.decode("utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line, object_pairs_hook=_unique_object)
        except (ValueError, LocalTestError):
            continue
        if isinstance(value, dict) and value.get("suite") == "angular-renderer":
            summaries.append(value)
    return summaries[0] if len(summaries) == 1 else None




def _execute_angular_process(run: TestRun, repo: Path, plan: dict, inventory: Path,
                             fault: str | None) -> None:
    diagnostic_root = run.root / "angular-diagnostics"
    command = [sys.executable, "tools/run_angular_renderer_tests.py",
               "--test-manifest", str(inventory), "--component", str(_angular_component(repo)),
               "--diagnostic-root", str(diagnostic_root)]
    if fault is not None:
        command += ["--inject-failure", fault]
    environment = run.execution_environment(dict(os.environ, CARGO_TARGET_DIR=str(_target_root(repo))))
    run.mark("execution")
    result = run.command(command, cwd=repo, env=environment,
                         timeout=plan["timeoutSeconds"] + 15,
                         maximum=8 * 1024 * 1024, check=False)
    summary = _test_run_summary(result.output)
    if summary is None:
        raise ProcessFailure("assertion-failure", "angular-owner-result-missing", result)
    name = summary.get("diagnostic")
    if (not isinstance(name, str) or re.fullmatch(r"angular-renderer-[0-9a-f]{32}\.json", name) is None
            or name != "angular-renderer-" + str(summary.get("runId")) + ".json"):
        raise ProcessFailure("invalid-fixture", "angular-owner-diagnostic-invalid", result)
    try:
        record = _read_record(diagnostic_root / name)
    except LocalTestError as error:
        raise ProcessFailure("invalid-fixture", "angular-owner-diagnostic-unavailable", result) from error
    reproduction = record.get("reproduction", {})
    if (record.get("suite") != "angular-renderer" or record.get("runId") != summary.get("runId")
            or record.get("outcome") != summary.get("outcome")
            or record.get("source") != run.source
            or record.get("fixtures") != run.fixture_ids
            or reproduction.get("recipeIdentity") != plan["recipeIdentity"]
            or reproduction.get("caseSetDigest") != case_digest(plan["cases"])
            or reproduction.get("requiredCaseCount") != len(plan["cases"])):
        raise ProcessFailure("invalid-fixture", "angular-owner-result-identity-mismatch", result)
    if result.returncode or record.get("outcome") != "passed":
        category = record.get("category")
        if category not in {"assertion-failure", "invalid-fixture", "unavailable-environment",
                            "cancelled", "infrastructure-timeout", "output-overflow"}:
            category = "assertion-failure"
        error = ProcessFailure(category, "angular-owner-failed", result)
        child = record.get("child", {})
        # The owner CLI returns 1; preserve an independently recorded inner
        # failing libtest status without changing the observed parent result.
        if type(child.get("exit")) is int and 0 < child["exit"] <= 255:
            error.selected_exit_code = child["exit"]
        elif type(child.get("signal")) is int and 0 < child["signal"] < 128:
            error.selected_exit_code = 128 + child["signal"]
        raise error
    if (record.get("requiredCaseCount") != len(plan["cases"])
            or record.get("completedCaseCount") != len(plan["cases"])
            or record.get("completedCaseDigest") != case_digest(plan["cases"])
            or record.get("cleanupFailures") != []
            or record.get("child", {}).get("cleanupAcknowledged") is not True):
        raise ProcessFailure("assertion-failure", "angular-owner-case-completion-mismatch", result)
    run.complete_cases(plan["cases"])


def execute(repo: Path, plan: dict, inventory: Path, fault: str | None = None) -> tuple[int, dict]:
    if not plan["runSupported"]:
        raise LocalTestError(plan["blocker"] or "registered selection is not executable")
    if _platform() not in plan["platforms"]:
        raise LocalTestError(f"unsupported platform {_platform()}")
    if fault is not None and (plan["suite"] != ANGULAR_PROCESS or fault != "after-discovery"):
        raise LocalTestError("--fault is supported only by process.angular-renderer")
    validate_prepared(repo, plan, inventory)
    reproduction = {"suite": plan["suite"], "recipe": plan["recipe"],
                    "recipeIdentity": plan["recipeIdentity"], "mode": plan["mode"]}
    if fault:
        reproduction["fault"] = fault
    run = TestRun(plan["suite"], {"timeoutSeconds": plan["timeoutSeconds"] + 30},
                  repo=repo, reproduction=reproduction)
    captured = io.StringIO()
    error: BaseException | None = None
    try:
        with redirect_stdout(captured):
            with run:
                run.declare_cases(plan["cases"])
                run.source_identity()
                run.artifact("test-manifest", inventory, artifacts.MAX_INVENTORY_BYTES)
                run.fixture_ids.update(_fixture_identities(repo, plan))
                if plan["suite"] == ANGULAR_PROCESS:
                    for role, artifact in _validate_angular_inventory(repo, inventory).items():
                        run.artifact(role, artifact.executable, 1024 * 1024 * 1024)
                    _execute_angular_process(run, repo, plan, inventory, fault)
                else:
                    _, _, prepared, _, _, _ = _generic_prepared(repo, plan, inventory)
                    run.artifact("test-executable", prepared.executable, 1024 * 1024 * 1024)
                    if plan["selection"] is not None:
                        _execute_selection(run, repo, plan, inventory, plan["selection"])
                    else:
                        _execute_suite(run, repo, plan, inventory)
    except BaseException as caught:
        error = caught
    diagnostics = captured.getvalue()
    if diagnostics:
        print(redact(diagnostics, secrets=run.secrets), file=sys.stderr, end="")
    record = run.record or {"schemaVersion": FAILURE_SCHEMA, "suite": plan["suite"],
                            "outcome": "failed", "category": "assertion-failure",
                            "reason": type(error).__name__ if error else "missing-run-record"}
    if error is None:
        return 0, record
    if isinstance(error, ProcessFailure):
        special = {"unavailable-environment": 3, "cancelled": 130,
                   "infrastructure-timeout": 124, "output-overflow": 125}
        code = special.get(error.category)
        if code is None:
            result = error.result
            code = getattr(error, "selected_exit_code", None) or (
                _exit_code(result.returncode) if result is not None and result.returncode else 1)
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
    value = _read_record(path)
    if value.get("outcome") not in {"failed", "not-run"}:
        raise LocalTestError("only a failed or not-run diagnostic can be reproduced")
    reproduction = value.get("reproduction")
    if not isinstance(reproduction, dict) or set(reproduction) - REPRODUCTION_KEYS:
        raise LocalTestError("failure record has an unsafe reproduction selection")
    suite = reproduction.get("suite")
    if (not isinstance(suite, str) or re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,95}", suite) is None
            or value.get("suite") != suite):
        raise LocalTestError("failure record suite identity is invalid")
    for field in ("recipe", "mode"):
        if not isinstance(reproduction.get(field), str):
            raise LocalTestError("failure record lacks an exact suite/case/recipe selection")
    cases = reproduction.get("cases")
    if cases is not None:
        if (not isinstance(cases, list) or not 1 <= len(cases) <= 128
                or not all(isinstance(case, str) and re.fullmatch(r"[A-Za-z0-9_:.-]{1,256}", case)
                           for case in cases)
                or len(set(cases)) != len(cases)):
            raise LocalTestError("failure record case selection is invalid")
        if "caseSelection" in reproduction:
            raise LocalTestError("failure record contains ambiguous case selection")
    elif reproduction.get("caseSelection") != "registered":
        raise LocalTestError("failure record lacks an exact suite/case/recipe selection")
    count = reproduction.get("requiredCaseCount")
    if type(count) is not int or not 1 <= count <= 10000:
        raise LocalTestError("failure record lacks the complete required-case count")
    for field in ("recipeIdentity", "caseSetDigest"):
        if not _is_digest(reproduction.get(field)):
            raise LocalTestError("failure record lacks a bound recipe/case identity; repeat the run with current tooling")
    if cases is not None and (count != len(cases) or reproduction["caseSetDigest"] != case_digest(cases)):
        raise LocalTestError("failure record case identity does not match its exact selection")
    if value.get("requiredCaseCount") != count:
        raise LocalTestError("failure record case counts disagree")
    source = reproduction.get("source")
    if (not isinstance(source, dict) or set(source) != {"revision", "dirty", "observed"}
            or type(source.get("observed")) is not bool
            or type(source.get("dirty")) is not bool
            or not isinstance(source.get("revision"), str)
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source["revision"]) is None
            or value.get("source") != source):
        raise LocalTestError("failure record has no consistent observed source identity")
    fixtures = reproduction.get("fixtures")
    if (not isinstance(fixtures, dict) or not 1 <= len(fixtures) <= 64
            or not all(isinstance(role, str) and re.fullmatch(r"[a-z0-9_.-]{1,96}", role)
                       and _is_digest(identity) for role, identity in fixtures.items())
            or value.get("fixtures") != fixtures):
        raise LocalTestError("failure record has no consistent prepared fixture identities")
    # These options belong to other owners. Silently discarding them would be a
    # different experiment, even if no command or environment were replayed.
    if any(key in reproduction for key in ("web", "observed", "fixtureOnly")):
        raise LocalTestError("failure record contains unsupported owner options")
    angular = suite in {"angular-renderer", ANGULAR_PROCESS}
    if "preflight" in reproduction and (not angular or reproduction["preflight"] is not False):
        raise LocalTestError("preflight-only failure cannot be reproduced as a test run")
    if "fault" in reproduction and (not angular or reproduction["fault"] not in {"none", "after-discovery"}):
        raise LocalTestError("failure record contains an unsupported fault selector")
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
            ["git", "--no-optional-locks", "-c", "gc.auto=0", "status", "--porcelain", "--untracked-files=normal"],
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
    angular = reproduction["suite"] in {"angular-renderer", ANGULAR_PROCESS}
    key = ANGULAR_PROCESS if angular else reproduction["suite"]
    cases = reproduction.get("cases")
    case = cases[0] if cases is not None and len(cases) == 1 and not angular else None
    plan = plan_suite(repo, key, case, inventory=inventory)
    if (not plan["runSupported"] or reproduction["recipe"] != plan["recipe"]
            or reproduction["mode"] != plan["mode"]
            or reproduction["recipeIdentity"] != plan["recipeIdentity"]
            or reproduction["caseSetDigest"] != case_digest(plan["cases"])
            or reproduction["requiredCaseCount"] != len(plan["cases"])
            or cases is not None and cases != plan["cases"]):
        raise LocalTestError("recorded suite/case/recipe no longer matches the registered contract")
    # Reject a changed checkout before running even --list from a prepared binary.
    exact = _source_match(repo, reproduction, allow_changed)
    validate_prepared(repo, plan, inventory)
    current = {"test-manifest": _fixture_digest(inventory, artifacts.MAX_INVENTORY_BYTES),
               **_fixture_identities(repo, plan)}
    if angular:
        for role, artifact in _validate_angular_inventory(repo, inventory).items():
            current[role] = _fixture_digest(artifact.executable, 1024 * 1024 * 1024)
    else:
        _, _, prepared, _, _, _ = _generic_prepared(repo, plan, inventory)
        current["test-executable"] = _fixture_digest(prepared.executable, 1024 * 1024 * 1024)
    if current != reproduction["fixtures"]:
        raise LocalTestError("prepared fixture identities do not match the recorded failure")
    fault = reproduction.get("fault")
    code, result = execute(repo, plan, inventory, fault=None if fault == "none" else fault)
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
    except KeyboardInterrupt:
        emit({"state": "cancelled", "reason": "interrupted", "exitCode": 130}, args.output)
        return 130
    except LocalTestError as error:
        emit({"state": error.state, "reason": redact(str(error)), "exitCode": error.code}, args.output)
        return error.code
    except (OSError, ValueError, TypeError, KeyError, RecursionError, artifacts.ArtifactError) as error:
        emit({"state": "not-run", "reason": f"invalid or unavailable local inputs: {error}",
              "exitCode": 3}, args.output)
        return 3



def _exit_code(returncode: int | None) -> int:
    if returncode is None:
        return 1
    return min(255, 128 - returncode) if returncode < 0 else returncode


def _prepare_registered(repo: Path, plan: dict, inventory: Path) -> dict:
    recipes = _fixtures_for(repo, plan)
    missing = []
    for name, recipe in recipes.items():
        if _fixture_presence(repo, {name: recipe}):
            _validate_fixture_recipe(repo, name, recipe)
        else:
            missing.append((name, recipe))
    required = {plan["preparation"]["buildCommand"][0]} if not inventory.exists() else set()
    for _, recipe in missing:
        required.update(recipe["tools"])
    unavailable = sorted(tool for tool in required if shutil.which(tool) is None)
    if unavailable:
        raise LocalTestError("missing preparation tools: " + ", ".join(unavailable))
    validator = (_validate_angular_inventory if plan["suite"] == ANGULAR_PROCESS
                 else lambda root, path: _validate_generic_inventory(root, path, plan))
    inventory_reused = _prepare_inventory(repo, plan, inventory, validator)
    environment = dict(os.environ, CARGO_TARGET_DIR=str(_target_root(repo)))
    for name, recipe in missing:
        for spec in recipe["outputs"].values():
            path = _fixture_path(repo, spec["path"])
            if path.is_symlink():
                raise LocalTestError("generated fixture output must not be a symlink")
            path.parent.mkdir(parents=True, exist_ok=True)
        for step in recipe["commands"]:
            command = [value.replace("{target}", str(_target_root(repo))) for value in step["argv"]]
            if command[0] == "python3":
                command[0] = sys.executable
            result = _prepare_step(command, repo / step["cwd"], environment, step["timeoutSeconds"])
            # Logs belong on stderr; --output json remains one parseable result.
            if result.stdout:
                print(redact(result.stdout.decode("utf-8", errors="replace"))[-16000:],
                      file=sys.stderr, end="")
        _validate_fixture_recipe(repo, name, recipe)
    validate_prepared(repo, plan, inventory)
    return {"suite": plan["suite"], "state": "prepared", "reused": inventory_reused and not missing,
            "inventory": str(inventory), "buildCommand": plan["preparation"]["buildCommand"],
            "fixtureRecipes": list(recipes), "targetDirectory": str(_target_root(repo))}


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _read_record(path: Path) -> dict:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REPORT:
            raise LocalTestError("failure record must be a bounded regular file")
        with path.open("rb") as source:
            raw = source.read(MAX_REPORT + 1)
    except OSError:
        raise LocalTestError("failure record is unavailable") from None
    if len(raw) > MAX_REPORT:
        raise LocalTestError("failure record exceeds the bounded diagnostic size")
    def invalid_constant(_):
        raise LocalTestError("non-finite failure-record value")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise LocalTestError("failure record is not valid bounded JSON") from None
    if not isinstance(value, dict) or value.get("schemaVersion") != FAILURE_SCHEMA:
        raise LocalTestError("unsupported failure record; expected latent.test-run.v1")
    if set(value) - REPORT_KEYS:
        raise LocalTestError("failure record contains unknown fields")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

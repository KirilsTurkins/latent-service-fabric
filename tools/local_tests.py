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
from tools.test_run import FAILURE_SCHEMA, ProcessFailure, TestRun, digest as file_digest

REPO = Path(__file__).resolve().parents[1]
SELECTION_PREFIX = "selection."
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
                   *(_selection_id(name) for name in data["selections"])])


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


def plan_suite(repo: Path, key: str, case: str | None = None,
               context: str = "local", inventory: Path | None = None) -> dict:
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


def validate_prepared(repo: Path, plan: dict, inventory: Path) -> None:
    if not inventory.is_file() or inventory.is_symlink():
        raise LocalTestError("prepared Cargo inventory is missing; run the reported prepare command")
    _generic_prepared(repo, plan, inventory)


def prerequisite_check(repo: Path, plan: dict, inventory: Path | None) -> dict:
    problems: list[str] = []
    if _platform() not in plan["platforms"]:
        problems.append(f"unsupported platform {_platform()}; supported: {', '.join(plan['platforms'])}")
    if inventory is None or not inventory.is_file() or inventory.is_symlink():
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


def prepare(repo: Path, plan: dict, inventory: Path) -> dict:
    if _platform() not in plan["platforms"]:
        raise LocalTestError(f"unsupported platform {_platform()}")
    if inventory.exists():
        validate_prepared(repo, plan, inventory)
        return {"suite": plan["suite"], "state": "prepared", "reused": True,
                "inventory": str(inventory)}
    command = plan["preparation"]["buildCommand"]
    if not command:
        raise LocalTestError("this registered recipe has no Cargo artifact preparation command")
    if not shutil.which(command[0]):
        raise LocalTestError(f"missing preparation tool: {command[0]}")
    inventory.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["CARGO_TARGET_DIR"] = str((repo / "target").resolve())
    try:
        result = run_bounded(command, repo, environment,
                             max(900, plan["timeoutSeconds"]), MAX_BUILD_OUTPUT)
    except BuildProcessError as error:
        raise LocalTestError(f"preparation process failed: {error}") from None
    if result.stderr:
        print(result.stderr.decode("utf-8", errors="replace")[-16000:], file=sys.stderr, end="")
    if result.returncode:
        raise LocalTestError(f"preparation command exited {result.returncode}", code=1, state="failed")
    try:
        with inventory.open("xb") as destination:
            destination.write(result.stdout)
    except FileExistsError:
        raise LocalTestError("prepared inventory appeared concurrently; validate it before reuse") from None
    try:
        validate_prepared(repo, plan, inventory)
    except Exception:
        try:
            inventory.unlink()
        except OSError:
            pass
        raise
    return {"suite": plan["suite"], "state": "prepared", "reused": False,
            "inventory": str(inventory), "buildCommand": command}


def _execute_selection(run: TestRun, repo: Path, plan: dict, inventory: Path,
                       name: str) -> None:
    suite = artifacts.SUITES.get(name)
    if suite is None:
        raise ProcessFailure("invalid-fixture", "selection-is-not-owned-by-ci-rust-artifacts")
    if suite.platforms and sys.platform not in suite.platforms:
        raise ProcessFailure("unavailable-environment", "unsupported-suite-platform")
    try:
        prepared = artifacts.read_inventory(inventory, repo, suite)
    except (OSError, ValueError, TypeError, artifacts.ArtifactError) as error:
        raise ProcessFailure("invalid-fixture", "prepared-cargo-artifact-invalid") from error
    run.artifact("test-manifest", inventory, artifacts.MAX_INVENTORY_BYTES)
    run.artifact("test-executable", prepared.executable, 1024 * 1024 * 1024)
    try:
        environment = artifacts.cargo_environment(repo, prepared, dict(os.environ), execute=_bridge(run))
    except artifacts.ArtifactError as error:
        raise ProcessFailure("unavailable-environment", str(error)) from error
    command = [str(prepared.executable), suite.filter, "--ignored"]
    if suite.exact:
        command.append("--exact")
    run.mark("discovery")
    listed = run.command([*command, "--list"], cwd=prepared.package, env=environment,
                         timeout=30, maximum=artifacts.MAX_LIST_BYTES, check=False)
    if listed.returncode:
        raise ProcessFailure("assertion-failure", "libtest-list-failed", listed)
    try:
        artifacts.validate_listing(listed.output, suite)
    except artifacts.ArtifactError as error:
        raise ProcessFailure("invalid-fixture", str(error), listed) from error
    run.mark("execution")
    if plan["case"] is not None:
        execution = [str(prepared.executable), plan["case"], "--exact", "--ignored", "--test-threads=1"]
    else:
        execution = [*command, "--test-threads=1"]
    if suite.observation_schema is not None:
        execution.append("--show-output")
    result = run.command(execution, cwd=prepared.package, env=environment,
                         timeout=suite.timeout, maximum=artifacts.MAX_OUTPUT_BYTES, check=False)
    print(result.output.decode("utf-8", errors="replace"), end="")
    if result.returncode:
        raise ProcessFailure("assertion-failure", "ignored-libtest-failed", result)
    if plan["case"] is not None:
        try:
            security.validate_result(result.output, plan["case"])
        except artifacts.ArtifactError as error:
            raise ProcessFailure("assertion-failure", str(error), result) from error
    else:
        expected = len(suite.names)
        match = re.search(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;",
                          result.output, re.MULTILINE)
        if match is None or tuple(int(value) for value in match.groups()) != (expected, 0, 0):
            raise ProcessFailure("assertion-failure", "ignored-libtest-result-mismatch", result)
    if suite.observation_schema == artifacts.METADATA_SCHEMA:
        try:
            artifacts.validate_metadata_observations(result.output)
        except artifacts.ArtifactError as error:
            raise ProcessFailure("assertion-failure", str(error), result) from error


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


def execute(repo: Path, plan: dict, inventory: Path) -> tuple[int, dict]:
    if not plan["runSupported"]:
        raise LocalTestError(plan["blocker"] or "registered suite is not executable through this entry point")
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


def reproduce(repo: Path, report: Path, inventory: Path, allow_changed: bool) -> tuple[int, dict]:
    record = read_failure(report)
    reproduction = record["reproduction"]
    cases = reproduction["cases"]
    case = cases[0] if len(cases) == 1 else None
    plan = plan_suite(repo, reproduction["suite"], case, inventory=inventory)
    validate_prepared(repo, plan, inventory)
    if plan["cases"] != cases or plan["recipe"] != reproduction["recipe"]:
        raise LocalTestError("recorded suite/case/recipe no longer matches the registered contract")
    fixtures = reproduction.get("fixtures")
    if not isinstance(fixtures, dict) or fixtures.get("test-manifest") != file_digest(
            inventory, artifacts.MAX_INVENTORY_BYTES):
        raise LocalTestError("prepared artifact inventory does not match the recorded failure")
    current = _source(repo)
    recorded_source = reproduction.get("source")
    exact = (isinstance(recorded_source, dict)
             and recorded_source.get("observed") is True
             and recorded_source.get("dirty") is False
             and current.get("dirty") is False
             and recorded_source.get("revision") == current.get("revision"))
    if not exact and not allow_changed:
        raise LocalTestError("source checkout is not an exact reproduction; pass --allow-changed-checkout for a labelled rerun")
    code, result = execute(repo, plan, inventory)
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
        code, result = execute(repo, plan, inventory)
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

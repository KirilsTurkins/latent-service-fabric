"""Local test interface; legacy native inventory is planning-only until #427/#428.

This adapter intentionally does not invent native recipe/prerequisite metadata,
classify changed files, validate native artifacts, or dispatch GitHub Actions.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import signal
import subprocess
import sys

from tools import ci_rust_artifacts as artifacts
from tools.local_test_support import (
    LocalTestError, MAX_CASES, MAX_JSON, bounded_read, decode, digest, environment,
    host_identity, reproduce_selection, source_identity, validate_report, write_report,
)

REPO = Path(__file__).resolve().parents[1]
TOOLING = "tooling-artifacts"
MODULE = "tools.tests.test_ci_rust_artifacts"
TEST_SOURCE = "tools/tests/test_ci_rust_artifacts.py"
MARKER = b"LSF_LOCAL_TEST_RESULT="
NATIVE_BLOCKER = ("native execution requires the shared suite/recipe and prepared-artifact "
                  "interfaces from #427/#428; a Cargo JSON inventory is not a validated prepared manifest")


def suite_ids() -> list[str]:
    return sorted([TOOLING, *artifacts.SUITES])


def tooling_cases(repo: Path) -> list[str]:
    """Read declarations without importing tests or running their setup code.

    The child verifies parity against unittest's real loader before execution.
    Dynamic/inherited/custom discovery cannot silently expand this selection.
    """
    source = repo / TEST_SOURCE
    if not source.is_file():
        raise LocalTestError(f"missing checked-out test source: {TEST_SOURCE}")
    data = bounded_read(source)
    if len(data) > MAX_JSON:
        raise LocalTestError("tooling test source exceeds planning bound")
    tree = ast.parse(data, filename=TEST_SOURCE)
    cases = []
    for item in tree.body:
        if isinstance(item, ast.ClassDef) and any(
            isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name)
            and base.value.id == "unittest" and base.attr == "TestCase" for base in item.bases
        ):
            for method in item.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith("test"):
                    cases.append(f"{MODULE}.{item.name}.{method.name}")
    if not 0 < len(cases) <= MAX_CASES or len(set(cases)) != len(cases):
        raise LocalTestError("empty, duplicate or oversized tooling case inventory")
    return sorted(cases)


def plan_suite(repo: Path, suite: str, case: str | None = None, context: str = "local") -> dict:
    if suite not in suite_ids():
        raise LocalTestError("unknown suite; use python3 tools/test.py list")
    if suite == TOOLING:
        cases = tooling_cases(repo)
        plan = {
            "suite": suite, "purpose": "Artifact-runner selection and owned-process regression tests",
            "harness": "python-unittest", "platforms": ["linux", "darwin"],
            "classification": "ordinary correctness", "cost": "small; not a timing guarantee",
            "prerequisites": ["Python standard library", "Git checkout", "checked-out test sources"],
            "recipe": "source-only-python-unittest", "features": [], "fixtures": "source-only",
            "preparation": "no external prepared artifacts; prepare checks the source-only inputs",
            "ready": sys.platform in {"linux", "darwin"},
            "blockers": [] if sys.platform in {"linux", "darwin"} else [
                "this adapter is supported only on Linux and macOS"],
            "command": ["<python>", "tools/local_python_suite.py"], "timeout_seconds": 60,
            "owner": TEST_SOURCE,
        }
    else:
        declared = artifacts.SUITES[suite]
        if not isinstance(declared, artifacts.Suite):
            raise LocalTestError("unsupported shared harness contract; no libtest fallback is permitted")
        cases = sorted(declared.names)
        # Only report what the existing owner actually declares. In particular,
        # do not manufacture platform, fixture, qualification or cost metadata.
        plan = {
            "suite": suite, "purpose": f"Declared ignored libtests in {declared.manifest}",
            "harness": "rust-libtest", "platforms": [],
            "classification": "not declared by legacy owner; requires #427",
            "cost": "not declared; no timing guarantee", "prerequisites": [NATIVE_BLOCKER],
            "recipe": None, "features": None, "fixtures": None,
            "preparation": "unavailable until shared #427/#428 integration",
            "ready": False, "blockers": [NATIVE_BLOCKER], "command": None,
            "timeout_seconds": 300, "owner": "tools/ci_rust_artifacts.py",
            "legacy_selection": {"manifest": declared.manifest, "target": declared.target,
                                 "source": declared.source, "filter": declared.filter,
                                 "exact": declared.exact, "ignored": True},
        }
    if not cases or len(cases) > MAX_CASES:
        raise LocalTestError("empty or oversized shared case selection")
    if case is not None and case not in cases:
        raise LocalTestError("exact case is not declared by the selected suite; no substring fallback")
    plan["selected_case"] = case
    plan["cases"] = [case] if case is not None else cases
    plan["required_case_count"] = len(plan["cases"])
    if plan["command"] is not None and case is not None:
        plan["command"] = [*plan["command"], "--case", case]
    plan["prepare_command"] = ["python3", "tools/test.py", "prepare", "--suite", suite]
    if case is not None:
        plan["prepare_command"] += ["--case", case]
    # Host/Actions metadata is explicitly outside command/selection identity.
    plan["recipe_identity"] = digest(plan)
    plan["context"] = context
    plan["schema"] = "latent.local-test-plan.v1"
    return plan


def prerequisite_check(repo: Path, plan: dict) -> dict:
    problems = list(plan["blockers"])
    if plan["suite"] == TOOLING:
        for name in (TEST_SOURCE, "tools/ci_rust_artifacts.py", "tools/local_python_suite.py"):
            if not (repo / name).is_file():
                problems.append(f"missing checked-out source: {name}")
        try:
            source_identity(repo)
        except (LocalTestError, OSError, artifacts.ArtifactError, subprocess.SubprocessError):
            problems.append("Git source identity unavailable; use a complete local checkout")
    return {"suite": plan["suite"], "state": "not-run" if problems else "ready",
            "prerequisites": plan["prerequisites"], "problems": problems,
            "prepare_command": plan["prepare_command"],
            "version_diagnostics": "delegate with doctor; scoped #338 integration is optional and pending"}


def summarize_output(raw: bytes, status: int, plan: dict) -> dict:
    summary = {"state": "failed", "exit_code": status if 0 < status < 256 else 1,
               "required_cases": len(plan["cases"]), "observed_cases": 0, "failed_cases": []}
    if status < 0:
        summary.update(state="cancelled", exit_code=min(255, 128 - status))
        return summary
    try:
        _, separator, tail = raw.rpartition(MARKER)
        if not separator:
            raise LocalTestError("missing child case receipt")
        result = decode(tail)
        if not isinstance(result, dict) or set(result) != {"cases", "observed_cases", "failed_cases", "state"}:
            raise LocalTestError("invalid child case receipt")
        if result["cases"] != plan["cases"] or type(result["observed_cases"]) is not int:
            raise LocalTestError("changed child selection")
        observed = result["observed_cases"]
        failed = result["failed_cases"]
        if (not 0 <= observed <= len(plan["cases"]) or not isinstance(failed, list)
                or len(set(failed)) != len(failed) or any(case not in plan["cases"] for case in failed)):
            raise LocalTestError("invalid child counts")
        state = result["state"]
        if state not in {"passed", "failed", "not-run"}:
            raise LocalTestError("invalid child state")
        if state == "passed" and (status or observed != len(plan["cases"]) or failed):
            raise LocalTestError("incomplete or failed child cannot pass")
        if state != "passed" and status == 0:
            raise LocalTestError("failed or not-run child returned zero")
        summary.update(state=state, exit_code=status, observed_cases=observed, failed_cases=failed)
    except (LocalTestError, TypeError, ValueError):
        # Preserve a concrete child failure code, even if it could not emit JSON.
        pass
    return summary


def execute(repo: Path, plan: dict, source: dict) -> dict:
    if not plan["ready"]:
        raise LocalTestError("; ".join(plan["blockers"]))
    command = [sys.executable, *plan["command"][1:]]
    try:
        status, raw = artifacts.run_owned(command, cwd=repo, env=environment(),
                                          timeout=plan["timeout_seconds"], maximum=artifacts.MAX_OUTPUT_BYTES)
        result = summarize_output(raw, status, plan)
        # Raw logs, traceback text, paths and credentials are never retained.
        # The normal bounded diagnostics remain visible on stderr, not JSON stdout.
        diagnostics = raw.rpartition(MARKER)[0] if MARKER in raw else raw
        if diagnostics:
            print(diagnostics.decode("utf-8", errors="replace"), file=sys.stderr, end="")
    except KeyboardInterrupt:
        result = {"state": "cancelled", "exit_code": 130, "observed_cases": 0, "failed_cases": []}
    except Terminated:
        result = {"state": "cancelled", "exit_code": 143, "observed_cases": 0, "failed_cases": []}
    except artifacts.ArtifactError as error:
        result = {"state": "failed", "exit_code": 124 if str(error) == "test-timeout" else 125,
                  "observed_cases": 0, "failed_cases": []}
    except (OSError, subprocess.SubprocessError):
        result = {"state": "not-run", "exit_code": 3, "observed_cases": 0, "failed_cases": []}
    try:
        after = source_identity(repo)
        if after != source:
            source = {**source, "dirty": True}
    except (LocalTestError, OSError, artifacts.ArtifactError, subprocess.SubprocessError):
        # Never describe an unobservable/changing source tree as exact.
        source = {**source, "dirty": True}
    result.update(schema="latent.local-test-selection.v1", suite=plan["suite"],
                  case=plan["selected_case"],
                  source=source, host=host_identity(), recipe=plan["recipe_identity"],
                  fixtures=plan["fixtures"], options={}, required_cases=len(plan["cases"]))
    validate_report(result)
    return result


class Terminated(BaseException):
    pass


def delegate(repo: Path, command: str, args: argparse.Namespace) -> int:
    if command == "preview":
        path = repo / "tools/preview_ci.py"
        if not path.is_file():
            raise LocalTestError("optional prerequisite #339: tools/preview_ci.py is not available")
        argv = ["--base", args.base]
        argv += ["--worktree"] if args.worktree else ["--head", args.head]
        argv += ["--output", args.output]
    else:
        path = repo / "tools/check_tool_versions.py"
        if not path.is_file():
            raise LocalTestError("optional prerequisite #338: scoped toolchain diagnostics are unavailable")
        tree = ast.parse(bounded_read(path))
        has_scope = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "add_argument" and any(
                            isinstance(a, ast.Constant) and a.value == "--scope" for a in n.args)
                        for n in ast.walk(tree))
        if not has_scope:
            raise LocalTestError("optional prerequisite #338: checker has no --scope interface; refusing all-SDK fallback")
        argv = ["--scope", args.scope, "--report-all", "--output", args.output]
    status, output = artifacts.run_owned([sys.executable, str(path), *argv], cwd=repo,
                                         env=environment(), timeout=120, maximum=MAX_JSON)
    print(output.decode("utf-8", errors="replace"), end="")
    return status if status >= 0 else min(255, 128 - status)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("list", "explain", "plan", "check", "prepare", "run"):
        child = sub.add_parser(name, allow_abbrev=False)
        child.add_argument("--output", choices=("human", "json"), default="human")
        if name != "list":
            child.add_argument("--suite", required=True)
            child.add_argument("--case")
            child.add_argument("--context", choices=("local", "ci"), default="local")
        if name == "run":
            child.add_argument("--record", type=Path)
    repro = sub.add_parser("reproduce", allow_abbrev=False)
    repro.add_argument("report", type=Path)
    repro.add_argument("--allow-changed-checkout", action="store_true")
    repro.add_argument("--case", help="one recorded failing case, never a substring filter")
    repro.add_argument("--output", choices=("human", "json"), default="human")
    preview = sub.add_parser("preview", allow_abbrev=False)
    preview.add_argument("--base", required=True)
    group = preview.add_mutually_exclusive_group()
    group.add_argument("--head", default="HEAD")
    group.add_argument("--worktree", action="store_true")
    preview.add_argument("--output", choices=("human", "json"), default="human")
    doctor = sub.add_parser("doctor", allow_abbrev=False)
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
    def interrupted(_signum: int, _frame: object) -> None:
        raise Terminated()

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.command in {"preview", "doctor"}:
            return delegate(repo, args.command, args)
        if args.command == "list":
            emit([plan_suite(repo, name) for name in suite_ids()], args.output)
            return 0
        if args.command == "reproduce":
            record = validate_report(decode(bounded_read(args.report)))
            plan = plan_suite(repo, record["suite"], record["case"])
            current = source_identity(repo)
            mode = reproduce_selection(record, plan, current, host_identity(),
                                       allow_changed=args.allow_changed_checkout)
            if args.case is not None:
                if args.case not in record["failed_cases"]:
                    raise LocalTestError("case was not a recorded failure; use an explicit new run selection")
                plan = plan_suite(repo, record["suite"], args.case)
            # Check before execution; --allow-changed-checkout never bypasses
            # suite/recipe/fixture validation or missing preparation.
            checked = prerequisite_check(repo, plan)
            if checked["problems"]:
                raise LocalTestError("; ".join(checked["problems"]))
            result = execute(repo, plan, current)
            emit({"reproduction": mode, "result": result}, args.output)
            return result["exit_code"]
        plan = plan_suite(repo, args.suite, args.case, args.context)
        if args.command in {"plan", "explain"}:
            emit(plan, args.output)
            return 0
        checked = prerequisite_check(repo, plan)
        if args.command in {"check", "prepare"}:
            if args.command == "prepare" and not checked["problems"]:
                checked.update(state="prepared", preparation="source-only; no installs, downloads or builds")
            emit(checked, args.output)
            return 3 if checked["problems"] else 0
        if checked["problems"]:
            raise LocalTestError("; ".join(checked["problems"]))
        result = execute(repo, plan, source_identity(repo))
        if args.record:
            try:
                write_report(args.record, result)
            except (OSError, LocalTestError):
                print("could not create the requested report (use a new file in an existing directory)", file=sys.stderr)
                if result["exit_code"] == 0:
                    emit(result, args.output)
                    return 3
        emit(result, args.output)
        return result["exit_code"]
    except LocalTestError as error:
        emit({"state": error.state, "reason": str(error), "exit_code": error.code}, args.output)
        return error.code
    except (KeyboardInterrupt, Terminated) as error:
        code = 130 if isinstance(error, KeyboardInterrupt) else 143
        emit({"state": "cancelled", "exit_code": code}, args.output)
        return code
    except (OSError, ValueError, SyntaxError, RecursionError, artifacts.ArtifactError, subprocess.SubprocessError):
        emit({"state": "not-run", "reason": "invalid or unavailable local inputs", "exit_code": 3}, args.output)
        return 3
    finally:
        signal.signal(signal.SIGTERM, previous)

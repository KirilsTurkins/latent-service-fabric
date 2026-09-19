#!/usr/bin/env python3
"""Bounded exact runtime-security cases; manual execution needs an enclosing owner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process import BuildProcessError, run_bounded
from tools.build_process_signals import owned_cancellation
from tools.phase3_security_artifacts import (
    MAX_LIST_BYTES, NAME, SecurityError, file_identity, listing, read_inventory, require,
    validate_custom, validate_result, validate_selection,
)
from tools.phase3_security_cases import GROUPS, selected

ROOT = Path(__file__).resolve().parents[1]
MAX_RECEIPT_BYTES = 128 * 1024
BASE_ENVIRONMENT = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL",
                    "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")


class Runner:
    def __init__(self, repo: Path, profile: str):
        self.repo = repo
        self.started = time.monotonic()
        self.deadline = self.started + (600 if profile == "pr" else 2400)
        self.environment = {name: os.environ[name] for name in BASE_ENVIRONMENT if name in os.environ}
        self.environment.update({"GIT_OPTIONAL_LOCKS": "0", "RUST_BACKTRACE": "0"})
        self.current = "preflight"
        self.commands = 0
        self.validated_cases = []
        self.active_case = None
        self.active_case_completed = False
        self.validated_workflows = []

    def command(self, command: list[str], *, cwd: Path | None = None,
                environment: dict | None = None, timeout: int = 90, maximum: int = 1024 * 1024):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "suite-deadline")
        self.commands += 1
        require(self.commands <= 1024, "suite-command-limit")
        return run_bounded(command, cwd or self.repo, environment or self.environment,
                           timeout_seconds=min(timeout, remaining), max_output_bytes=maximum)


def verify_source(runner: Runner, source: str) -> None:
    require(re.fullmatch(r"[0-9a-f]{40}", source) is not None, "source-commit-format")
    prefix = ["git", "-c", "safe.directory=" + str(runner.repo)]
    current = runner.command([*prefix, "rev-parse", "HEAD"], maximum=4096)
    require(current.stdout.decode("ascii").strip() == source, "source-commit-mismatch")
    status = runner.command([*prefix, "status", "--porcelain", "--untracked-files=no"], maximum=65536)
    require(not status.stdout, "tracked-source-dirty")
    runner.command([*prefix, "ls-files", "--error-unmatch", "tools/phase3_security.py",
                    "tools/phase3_security_cases.py", "tools/phase3_security_artifacts.py",
                    "tools/phase3_security_manual.py", "tools/phase3_security_container.py"], maximum=4096)


def check_matrix() -> None:
    keys = set()
    owners = set()
    for group in GROUPS:
        require(group.key not in keys and re.fullmatch(r"[a-z0-9_-]+", group.key) is not None,
                "matrix-group-key")
        keys.add(group.key)
        require(group.kind in ("lib", "test") and 0 < group.timeout <= 180, "matrix-harness")
        require(bool(group.cases) != bool(group.marker), "matrix-harness-shape")
        for case in group.cases:
            require(NAME.fullmatch(case.name) is not None and not (case.pr and case.ignored),
                    "matrix-case")
            owner = (group.manifest, group.target, case.name)
            require(owner not in owners, "matrix-duplicate-case")
            owners.add(owner)
    require(0 < len(owners) <= 512, "matrix-case-limit")


def check_engine(repo: Path) -> str:
    lock = tomllib.loads((repo / "Cargo.lock").read_text(encoding="utf-8"))
    tools = tomllib.loads((repo / "tools/toolchain.toml").read_text(encoding="utf-8"))
    versions = [package["version"] for package in lock["package"] if package["name"] == "wasmtime"]
    require(versions == ["47.0.4"] and tools["rust"]["dependencies"]["wasmtime"] == "47.0.4",
            "unreviewed-engine-profile")
    return versions[0]


def test_environment(runner: Runner, artifact, runtime: Path, fixtures: dict) -> dict[str, str]:
    paths = [runtime, runner.repo / "target/debug/deps", runner.repo / "target/debug",
             *artifact.link_paths]
    return {**runner.environment, **fixtures, "CARGO_MANIFEST_DIR": str(artifact.package),
            "LD_LIBRARY_PATH": os.pathsep.join(str(path) for path in paths)}


def inventories(runner: Runner, groups: tuple, artifacts: dict, runtime: Path) -> dict:
    cache = {}
    identities = {}
    for group in groups:
        runner.current = group.key + ":inventory"
        artifact = artifacts[group.key]
        if artifact.executable not in identities:
            identities[artifact.executable] = file_identity(artifact.executable, runner.deadline)
        if group.marker is not None:
            continue
        if artifact.executable not in cache:
            environment = test_environment(runner, artifact, runtime, {})
            listed = []
            for extra in ([], ["--ignored"]):
                result = runner.command([str(artifact.executable), "--list", "--format=pretty", *extra],
                                        cwd=artifact.package, environment=environment,
                                        timeout=30, maximum=MAX_LIST_BYTES)
                require(not result.stderr, "test-list-diagnostics")
                listed.append(listing(result.stdout))
            cache[artifact.executable] = tuple(listed)
        validate_selection(group, *cache[artifact.executable])
    return identities


def run_cases(runner: Runner, groups: tuple, artifacts: dict, runtime: Path,
              profile: str, fixtures: dict, directory: Path) -> list[dict]:
    results = []
    for group in groups:
        artifact = artifacts[group.key]
        environment = test_environment(runner, artifact, runtime, fixtures)
        if group.key == "fixture-publication":
            environment["LSF_OPERATOR_FIXTURE_ROOT"] = str(directory / "publication")
        completed = []
        explicit_ignored = []
        if group.marker is not None:
            runner.current = group.key
            runner.active_case = group.key + ":" + group.target
            runner.active_case_completed = False
            result = runner.command([str(artifact.executable)], cwd=artifact.package,
                                    environment=environment, timeout=group.timeout)
            runner.active_case_completed = True
            validate_custom(result.stdout + result.stderr, group.marker)
            completed.append(group.target)
            runner.validated_cases.append(runner.active_case)
            runner.active_case = None
        else:
            for case in group.cases:
                if profile == "pr" and not case.pr:
                    continue
                runner.current = group.key + ":" + case.name
                runner.active_case = runner.current
                runner.active_case_completed = False
                command = [str(artifact.executable), case.name, "--exact", "--test-threads=1",
                           "--format=pretty", "--color=never"]
                if case.ignored:
                    command.append("--ignored")
                    explicit_ignored.append(case.name)
                result = runner.command(command, cwd=artifact.package, environment=environment,
                                        timeout=group.timeout)
                runner.active_case_completed = True
                emitted_record = None
                if group.key in ("actual-browser", "actual-browser-application"):
                    from tools.phase3_security_manual import browser_output
                    emitted_record = browser_output(directory, runner.deadline,
                                                    application=group.key == "actual-browser-application")
                validate_result(result.stdout, case.name, emitted_record=emitted_record)
                completed.append(case.name)
                runner.validated_cases.append(runner.active_case)
                runner.active_case = None
        require(completed, "empty-security-group")
        results.append({"id": group.key, "layer": group.layer, "issues": list(group.issues),
                        "passed": completed, "explicitIgnored": explicit_ignored,
                        "customHarnessMarker": group.marker})
        print(json.dumps({"group": group.key, "passed": len(completed)}, separators=(",", ":")),
              file=sys.stderr, flush=True)
    return results


def run(args, runner: Runner) -> dict:
    require(sys.platform == "linux" and platform.machine() == "x86_64" and sys.version_info >= (3, 13),
            "unsupported-security-platform")
    if args.profile == "manual":
        require(os.geteuid() == 0, "manual-disposable-root-fixture-required")
    check_matrix()
    verify_source(runner, args.source_commit)
    engine = check_engine(runner.repo)
    groups = selected(args.profile)
    inventory_before = file_identity(args.inventory, runner.deadline, 32 * 1024 * 1024)
    artifacts = read_inventory(args.inventory, runner.repo, groups)
    version = runner.command(["rustc", "--version"], maximum=4096).stdout.decode("ascii").strip()
    runtime = Path(runner.command(["rustc", "--print", "target-libdir"], maximum=4096)
                   .stdout.decode("utf-8").strip()).resolve(strict=True)
    identities = inventories(runner, groups, artifacts, runtime)
    target = runner.repo / "target/phase3-security"
    target.mkdir(exist_ok=True)
    require(target.resolve().is_relative_to((runner.repo / "target").resolve()), "owned-output-root")
    fixture_inputs = {}
    fixture_outputs = {}
    workflow_results = []
    with tempfile.TemporaryDirectory(prefix="owned-", dir=target) as temporary:
        directory = Path(temporary)
        fixtures = {}
        if args.profile == "manual":
            from tools import phase3_security_manual as manual
            runner.current = "manual-inputs"
            fixtures, fixture_inputs = manual.inputs(args, runner, directory)
        results = run_cases(runner, groups, artifacts, runtime, args.profile, fixtures, directory)
        if args.profile == "manual":
            runner.current = "maintained-node-workflows"
            workflow_results = manual.workflows(args, runner, directory)
            runner.current = "fixture-identities"
            fixture_outputs = manual.fixture_identities(directory, runner.deadline)
            runner.current = "manual-input-identities"
            manual.verify_inputs(args, runner, fixture_inputs)
    require(not directory.exists(), "owned-fixtures-retained")
    runner.current = "final-identities"
    for executable, identity in identities.items():
        require(file_identity(executable, runner.deadline) == identity, "test-binary-changed")
    require(file_identity(args.inventory, runner.deadline, 32 * 1024 * 1024) == inventory_before,
            "inventory-changed")
    verify_source(runner, args.source_commit)
    return {
        "schemaVersion": "latent.phase3.security.v1", "profile": args.profile, "passed": True,
        "sourceCommit": args.source_commit, "trackedSourceClean": True,
        "cargoInventory": inventory_before,
        "inventoryContract": "current-job-cargo-no-run-not-a-build-attestation",
        "cargoLock": file_identity(runner.repo / "Cargo.lock", runner.deadline),
        "matrix": file_identity(runner.repo / "tools/phase3_security_cases.py", runner.deadline),
        "platform": {"os": sys.platform, "architecture": platform.machine(),
                     "kernel": platform.release(), "python": platform.python_version(),
                     "rustc": version, "uid": os.geteuid(), "wasmtime": engine},
        "groups": results,
        "testExecutables": {group.key: identities[artifacts[group.key].executable] for group in groups},
        "fixtureInputs": fixture_inputs, "fixtureOutputs": fixture_outputs, "workflows": workflow_results,
        "testEntriesPassed": sum(len(group["passed"]) for group in results),
        "explicitIgnoredExecuted": sum(len(group["explicitIgnored"]) for group in results),
        "commands": runner.commands, "elapsedMillis": int((time.monotonic() - runner.started) * 1000),
        "temporaryOutputsRemoved": True,
        "processBoundary": "bounded-process-groups-and-maintained-workflow-owners",
        "enclosingContainerStopRequired": args.profile == "manual",
        "enclosingContainerOwner": args.container_owner,
        "qualificationExclusions": ["T2-guest-process-containment", "reference-browser-backend-canary-236",
                                    "hosted-provider-vendor-campaigns", "SDK-real-node-runner",
                                    "load", "non-Linux-x86_64"],
    }


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("pr", "manual"), default="pr")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--container-owner")
    for name in ("cli", "node", "compiler", "guest-capsules", "web-component",
                 "browser-node", "browser-chrome", "browser-toolchain", "angular-build", "angular-compiler"):
        parser.add_argument("--" + name, type=Path)
    return parser.parse_args(argv)


def failure_reason(error: BaseException) -> str:
    return str(error) if isinstance(error, (SecurityError, BuildProcessError)) else "fixture-or-process-error"


def failure_report(args, runner: Runner, error: BaseException) -> dict:
    entries = [group.key + ":" + name for group in selected(args.profile)
               for name in ([group.target] if group.marker else
                            [case.name for case in group.cases if args.profile == "manual" or case.pr])]
    completed = set(runner.validated_cases)
    active_workflow = runner.current.removeprefix("workflow:") if runner.current.startswith("workflow:") else None
    return {"schemaVersion": "latent.phase3.security.failure.v1", "profile": args.profile, "passed": False,
            "requestedSourceCommit": args.source_commit if re.fullmatch(r"[0-9a-f]{40}", args.source_commit) else None,
            "failedStage": runner.current, "classification": failure_reason(error),
            "validatedCases": runner.validated_cases, "activeCase": runner.active_case,
            "activeCaseCommandAccepted": runner.active_case_completed if runner.active_case else None,
            "notExecutedCases": [name for name in entries if name not in completed and name != runner.active_case],
            "validatedWorkflows": runner.validated_workflows, "activeWorkflow": active_workflow,
            "notExecutedWorkflows": [name for name in ("publication", "security-profile", "provider-management", "angular-t1")
                                     if args.profile == "manual" and name not in runner.validated_workflows
                                     and name != active_workflow],
            "commands": runner.commands, "elapsedMillis": int((time.monotonic() - runner.started) * 1000),
            "enclosingContainerStopRequired": args.profile == "manual",
            "enclosingContainerOwner": args.container_owner}


def container_entry(argv=None) -> None:
    """Private owner protocol; the host CLI must reject a negative receipt."""
    args = arguments(argv)
    runner = Runner(ROOT, args.profile)
    try:
        with owned_cancellation():
            report = run(args, runner)
    except (Exception, KeyboardInterrupt) as error:
        report = failure_report(args, runner, error)
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    require(len(encoded) <= MAX_RECEIPT_BYTES, "security-receipt-limit")
    print(encoded.decode())


def main(argv=None) -> int:
    args = arguments(argv)
    runner = Runner(ROOT, args.profile)
    try:
        with owned_cancellation():
            report = run(args, runner)
            encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
            require(len(encoded) <= MAX_RECEIPT_BYTES, "security-receipt-limit")
            if args.output is not None:
                destination = args.output.absolute()
                require(destination.parent.resolve(strict=True).is_relative_to((ROOT / "target").resolve()),
                        "receipt-outside-owned-target")
                with destination.open("xb") as output:
                    output.write(encoded + b"\n")
            print(encoded.decode())
        return 0
    except (Exception, KeyboardInterrupt) as error:
        reason = failure_reason(error)
        print(f"Phase 3 security failed: {runner.current}: {reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

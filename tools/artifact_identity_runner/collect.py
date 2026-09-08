"""Serial source builds, shared fixtures, and alternating retained attempts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time

from optimization_runner.cgroups import cgroup
from phase1_measurement_environment import host
from .build import build_arm, command, git, identity, matching_controls, validate_refs
from .files import fingerprint, inventory, reference, retain, total_bytes, write_json
from .model import population, suite
from .run import collect, make_run


def tool(name: str) -> dict:
    found = shutil.which(name)
    if found is None:
        raise ValueError("required-tool-missing-" + name)
    # rustup selects rustc/cargo by argv[0]; retain its invocation basename.
    path = Path(found).absolute()
    result = subprocess.run([str(path), "--version"], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=15, check=True)
    value = result.stdout + result.stderr
    if len(value) > 65536:
        raise ValueError("tool-version-bound")
    return {"path": str(path), "sha256": fingerprint(path.resolve())[0], "version": value.decode().strip()}


def prepare_fixture(size: str, args, receipt: dict, output: Path, deadline: int) -> dict:
    root = output / "fixtures" / size
    root.parent.mkdir(exist_ok=True)
    argv = [str(output / receipt["builds"]["control"]["binary"]["path"]), "fixture",
            "--component", str(output / "inputs" / "component.wasm"),
            "--capsule", str(output / "inputs" / "capsule.json"),
            "--contracts", str(output / "inputs" / "contracts.json"), "--output", str(root), "--size", size]
    process = command(argv, output / "fixtures" / f"{size}-generation.log", 180, output, deadline)
    manifest_path = root / "fixture.json"
    fingerprint(manifest_path, 16384)
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("size") != size:
        raise ValueError("fixture-size-mismatch")
    return {"root": root.relative_to(output).as_posix(), "manifest": manifest,
            "files": inventory(root, output), "generation_process": process, "command": argv,
            "generation_log": reference(output / "fixtures" / f"{size}-generation.log", output)}


def sources(repo: Path, args, output: Path, receipt: dict, deadline: int) -> None:
    matching_controls(repo, args.control_ref, args.candidate_ref)
    temporary = tempfile.TemporaryDirectory(prefix="lsf-artifact-identity-")
    source, target = Path(temporary.name) / "source", Path(temporary.name) / "target"
    registered = False
    try:
        git(repo, "worktree", "add", "--detach", str(source), args.control_ref)
        registered = True
        for arm, commit in (("control", args.control_ref), ("candidate", args.candidate_ref)):
            if arm == "candidate":
                git(source, "checkout", "--detach", commit)
            if identity(source)["commit"] != commit:
                raise ValueError("source-ref-mismatch")
            receipt["builds"][arm] = build_arm(source, target, arm, output, deadline)
            write_json(output / "suite.json", receipt)
        control = receipt["builds"]["control"]["probe_sources"]
        candidate = receipt["builds"]["candidate"]["probe_sources"]
        if {name: (item["sha256"], item["bytes"]) for name, item in control.items()} != {
                name: (item["sha256"], item["bytes"]) for name, item in candidate.items()}:
            raise ValueError("probe-sources-differ")
    finally:
        if registered:
            # source is a literal child of this invocation's private temp root.
            if source.parent.resolve() != Path(temporary.name).resolve():
                raise ValueError("owned-worktree-path-mismatch")
            git(repo, "worktree", "remove", "--force", str(source))
        temporary.cleanup()
        receipt["cleanup"]["owned_worktree_removed"] = True


def execute(args, repo: Path) -> int:
    if platform.system() != "Linux":
        raise ValueError("linux-required")
    validate_refs(args.control_ref, args.candidate_ref, args.profile)
    if any(os.environ.get(name) for name in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("inherited-allocation-override")
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    receipt = suite(args.profile, args.control_ref, args.candidate_ref)
    started = time.monotonic_ns()
    deadline = started + receipt["plan"]["suite_timeout_seconds"] * 1_000_000_000
    write_json(output / "suite.json", receipt)
    try:
        receipt["environment"] = {"host": host(), "cgroup": cgroup(), "runner_source": identity(repo)}
        receipt["tools"] = {name: tool(name) for name in ("heaptrack", "heaptrack_print", "zstd", "rustc", "cargo", "git")}
        if "1.4" not in receipt["tools"]["heaptrack"]["version"]:
            raise ValueError("heaptrack-version-unsupported")
        for name, path, bound in (("component.wasm", args.component, 16 * 1024 * 1024),
                                  ("capsule.json", args.capsule, 1024 * 1024),
                                  ("contracts.json", args.contracts, 1024 * 1024)):
            fingerprint(path, bound)
            retain(path, output / "inputs" / name, output)
        sources(repo, args, output, receipt, deadline)
        for size in receipt["plan"]["sizes"]:
            receipt["fixtures"][size] = prepare_fixture(size, args, receipt, output, deadline)
            write_json(output / "suite.json", receipt)
        # No builds, fixture generation, profiler report children, or other
        # subprocesses overlap a normal child's RUSAGE_CHILDREN interval.
        for pair, arm, size, operation, mode in population(args.profile):
            record, directory = make_run(pair, arm, size, operation, mode, receipt, output,
                                         receipt["tools"]["heaptrack"]["path"])
            receipt["runs"].append(record)
            write_json(output / "suite.json", receipt)
            try:
                collect(record, directory, receipt["builds"][arm]["binary"],
                        receipt["fixtures"][size], output, deadline,
                        receipt["tools"]["heaptrack_print"]["path"], receipt["tools"]["zstd"]["path"])
            except Exception:
                record["reason"] = "probe-collection-failed"
                raise
            finally:
                write_json(output / "suite.json", receipt)
            total_bytes(output)
        for fixture in receipt["fixtures"].values():
            if inventory(output / fixture["root"], output) != fixture["files"]:
                raise ValueError("fixture-mutated-after-measurement")
        for build in receipt["builds"].values():
            if reference(output / build["binary"]["path"], output) != build["binary"]:
                raise ValueError("retained-binary-mutated")
        if time.monotonic_ns() > deadline:
            raise TimeoutError("suite-deadline")
        receipt.update(status="passed", reason=None)
    except BaseException as error:
        receipt.update(status="failed", reason="collection-failed")
        write_json(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
    finally:
        receipt["elapsed_nanos"] = str(time.monotonic_ns() - started)
        try:
            receipt["artifacts"] = [value for name, value in inventory(output, output).items()
                                    if name not in ("suite.json", "aggregate.json")]
        except (OSError, ValueError):
            receipt.update(status="failed", reason="artifact-inventory-failed")
        write_json(output / "suite.json", receipt)
    if receipt["status"] != "passed":
        return 1
    from artifact_identity_evidence import validate_suite
    try:
        aggregate = validate_suite(output / "suite.json")
        write_json(output / "aggregate.json", aggregate)
    except Exception as error:
        write_json(output / "validation-failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
        return 1
    return 0

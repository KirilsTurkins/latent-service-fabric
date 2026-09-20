#!/usr/bin/env python3
"""Execute exact libtest suites from this checkout's successful Cargo inventory.

Suite identities and recipes live in ci_suites.json. This runner never builds or
finds executables by glob, and an empty or changed selection is never success.
The inventory is build metadata, not cached test or qualification evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import threading
import time

MAX_INVENTORY_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_RECORDS = 100_000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_LIST_BYTES = 64 * 1024
MAX_LINK_PATHS = 256
POLICY_PREFIX = "supply_chain::tests::support::operator_fixture::"
CURRENTNESS_PREFIX = "standalone::start::tests::trust_currentness::"
REGISTRY = Path(__file__).with_name("ci_suites.json")


class ArtifactError(Exception):
    """A bounded failure reason; no missing test is accepted as a successful suite."""


@dataclass(frozen=True)
class Suite:
    manifest: str
    target: str
    source: str
    filter: str
    names: frozenset[str]
    exact: bool
    ignored: bool = True
    timeout_seconds: int = 300
    nocapture: bool = False
    platforms: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    classification: str = "integration"
    resource_class: str = "serial-host"
    required_job: str = "rust"
    recipe: tuple[str, ...] = ()
    expected_features: tuple[str, ...] | None = None
    assertions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Artifact:
    executable: Path
    package: Path
    link_paths: tuple[Path, ...]


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError("duplicate-inventory-key")
        result[key] = value
    return result


def read_suites(path: Path) -> dict[str, Suite]:
    with path.open("rb") as source:
        raw = source.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ArtifactError("suite-inventory-limit")
    document = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(document, dict)
            or document.get("schemaVersion") != "latent.ci.libtest-suites.v1"
            or not isinstance(document.get("suites"), dict)
            or not 1 <= len(document["suites"]) <= 64):
        raise ArtifactError("invalid-suite-inventory")
    suites: dict[str, Suite] = {}
    for name, value in document["suites"].items():
        if (re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) is None
                or not isinstance(value, dict)
                or set(value) != set(Suite.__dataclass_fields__)):
            raise ArtifactError("invalid-suite-definition")
        for field in ("manifest", "target", "source", "filter", "classification",
                      "resource_class", "required_job"):
            if (not isinstance(value[field], str) or not value[field]
                    or len(value[field]) > 1024 or any(ord(c) < 32 for c in value[field])):
                raise ArtifactError("invalid-suite-field")
        for field in ("manifest", "source"):
            path_value = Path(value[field])
            if path_value.is_absolute() or ".." in path_value.parts or "\\" in value[field]:
                raise ArtifactError("invalid-suite-owner")
        for field in ("exact", "ignored", "nocapture"):
            if type(value[field]) is not bool:
                raise ArtifactError("invalid-suite-boolean")
        if (type(value["timeout_seconds"]) is not int
                or not 1 <= value["timeout_seconds"] <= 1800):
            raise ArtifactError("invalid-suite-timeout")
        for field in ("names", "platforms", "prerequisites", "recipe", "assertions",
                      "expected_features"):
            items = value[field]
            if field == "expected_features" and items is None:
                continue
            if (not isinstance(items, list) or len(items) > 128
                    or any(not isinstance(item, str) or not item or len(item) > 1024
                           or any(ord(c) < 32 for c in item) for item in items)):
                raise ArtifactError("invalid-suite-list")
            if field != "recipe" and len(items) != len(set(items)):
                raise ArtifactError("duplicate-suite-entry")
            value[field] = frozenset(items) if field == "names" else tuple(items)
        if (not value["names"] or not value["recipe"]
                or any(not test.startswith(value["filter"]) for test in value["names"])
                or (value["exact"] and value["names"] != {value["filter"]})
                or set(value["prerequisites"]) - {"linux-proc-vmhwm"}):
            raise ArtifactError("invalid-suite-selection")
        suites[name] = Suite(**value)
    return suites


SUITES = read_suites(REGISTRY)


def absolute_path(value: object) -> Path:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        raise ArtifactError("invalid-artifact-path")
    path = Path(value)
    if not path.is_absolute():
        raise ArtifactError("relative-artifact-path")
    return path.resolve(strict=True)


def read_inventory(path: Path, repo: Path, suite: Suite) -> Artifact:
    repo = repo.resolve(strict=True)
    expected_manifest = (repo / suite.manifest).resolve(strict=True)
    expected_source = expected_manifest.parent / suite.source
    target_root = (repo / "target").resolve(strict=True)
    executable_root = (target_root / "debug/deps").resolve(strict=True)
    found: Path | None = None
    link_paths: set[Path] = set()
    finished = False
    consumed = 0
    records = 0
    with path.open("rb") as source:
        while raw := source.readline(MAX_LINE_BYTES + 1):
            consumed += len(raw)
            records += 1
            if (len(raw) > MAX_LINE_BYTES or consumed > MAX_INVENTORY_BYTES
                    or records > MAX_RECORDS):
                raise ArtifactError("inventory-limit")
            if not raw.strip():
                continue
            if finished:
                raise ArtifactError("inventory-after-build-finished")
            message = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(message, dict):
                raise ArtifactError("invalid-inventory-record")
            reason = message.get("reason")
            if reason == "build-finished":
                if message.get("success") is not True:
                    raise ArtifactError("cargo-build-failed")
                finished = True
            elif reason == "build-script-executed":
                paths = message.get("linked_paths", [])
                if not isinstance(paths, list) or len(paths) > MAX_LINK_PATHS:
                    raise ArtifactError("link-path-limit")
                for value in paths:
                    if not isinstance(value, str) or len(value) > 4096:
                        raise ArtifactError("invalid-link-path")
                    value = value.split("=", 1)[-1]
                    candidate = Path(value)
                    if candidate.is_absolute():
                        candidate = candidate.resolve()
                        if candidate.is_relative_to(target_root):
                            link_paths.add(candidate)
                    if len(link_paths) > MAX_LINK_PATHS:
                        raise ArtifactError("link-path-limit")
            elif reason == "compiler-artifact":
                manifest = message.get("manifest_path")
                if not isinstance(manifest, str) or len(manifest) > 4096:
                    raise ArtifactError("invalid-artifact-manifest")
                if Path(manifest).resolve() != expected_manifest:
                    continue
                target = message.get("target")
                profile = message.get("profile")
                if not isinstance(target, dict) or not isinstance(profile, dict):
                    raise ArtifactError("invalid-artifact-target")
                if target.get("kind") != ["lib"] or profile.get("test") is not True:
                    continue
                if (target.get("name") != suite.target
                        or absolute_path(target.get("src_path")) != expected_source.resolve(strict=True)):
                    raise ArtifactError("wrong-libtest-owner")
                if suite.expected_features is not None:
                    features = message.get("features")
                    if (not isinstance(features, list)
                            or any(not isinstance(feature, str) for feature in features)
                            or sorted(features) != sorted(suite.expected_features)):
                        raise ArtifactError("suite-feature-recipe-mismatch")
                executable = absolute_path(message.get("executable"))
                if not executable.is_relative_to(executable_root) or not executable.is_file():
                    raise ArtifactError("executable-outside-deps")
                if found is not None:
                    raise ArtifactError("ambiguous-libtest-artifact")
                found = executable
    if not finished or found is None:
        raise ArtifactError("missing-successful-libtest-artifact")
    return Artifact(found, expected_manifest.parent, tuple(sorted(link_paths)))


def run_owned(command: list[str], *, cwd: Path, env: dict[str, str],
              timeout: int, maximum: int) -> tuple[int, bytes]:
    """Bound output and lifetime, retaining process ownership through kill/reap."""
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
    expired = threading.Event()

    def stop() -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass

    def expire() -> None:
        expired.set()
        stop()

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        assert process.stdout is not None
        output = process.stdout.read(maximum + 1)
        if len(output) > maximum:
            raise ArtifactError("test-output-limit")
        # Retire the timer before reaping: after wait(), this PID could be reused.
        timer.cancel()
        timer.join()
        process.wait(timeout=5)
        if expired.is_set():
            raise ArtifactError("test-timeout")
        return process.returncode, output
    finally:
        timer.cancel()
        timer.join()
        if process.returncode is None:
            stop()
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def require_source(repo: Path, expected: str | None, env: dict[str, str]) -> None:
    if expected is None or re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", expected) is None:
        raise ArtifactError("missing-source-commit")
    status, output = run_owned(["git", "-c", "gc.auto=0", "rev-parse", "--verify", "HEAD"],
                               cwd=repo, env=env, timeout=30, maximum=256)
    if status or output.strip().decode("ascii") != expected.lower():
        raise ArtifactError("inventory-source-checkout-mismatch")


def cargo_environment(repo: Path, artifact: Artifact, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    status, output = run_owned(["rustc", "--print", "target-libdir"], cwd=repo,
                               env=env, timeout=30, maximum=4096)
    if status:
        raise ArtifactError("rust-library-path-unavailable")
    rust_libraries = absolute_path(output.decode("utf-8").strip())
    paths = [*artifact.link_paths, repo / "target/debug/deps", repo / "target/debug", rust_libraries]
    key = "PATH" if os.name == "nt" else ("DYLD_FALLBACK_LIBRARY_PATH" if sys.platform == "darwin"
                                          else "LD_LIBRARY_PATH")
    env[key] = os.pathsep.join([*(str(path) for path in paths), *([env[key]] if env.get(key) else [])])
    env["CARGO_MANIFEST_DIR"] = str(artifact.package)
    return env


def validate_listing(output: bytes, suite: Suite) -> None:
    names: list[str] = []
    summary: tuple[int, int] | None = None
    for line in output.decode("utf-8").splitlines():
        if not line:
            continue
        if line.endswith(": test"):
            names.append(line[:-6])
        elif match := re.fullmatch(r"(\d+) tests?, (\d+) benchmarks?", line):
            if summary is not None:
                raise ArtifactError("invalid-test-list")
            summary = (int(match[1]), int(match[2]))
        else:
            raise ArtifactError("invalid-test-list")
    if (len(names) != len(suite.names) or set(names) != suite.names
            or summary != (len(suite.names), 0)):
        raise ArtifactError("expected-ignored-tests-missing-or-changed")


def prerequisites(suite: Suite, env: dict[str, str]) -> None:
    if suite.platforms and sys.platform not in suite.platforms:
        raise ArtifactError("unsupported-suite-platform")
    if suite.required_job == "catalog" and any(name in env for name in (
            "LSF_DEPLOYMENT_MEMORY_MODE", "LSF_DEPLOYMENT_MEMORY_ROOT")):
        raise ArtifactError("parent-suite-rejects-child-environment")
    if "linux-proc-vmhwm" in suite.prerequisites:
        try:
            with Path("/proc/self/status").open("rb") as source:
                status = source.read(MAX_LIST_BYTES + 1)
        except OSError as error:
            raise ArtifactError("unavailable-linux-proc-vmhwm") from error
        values = re.findall(rb"^VmHWM:\s*([1-9][0-9]*)\s+kB\s*$", status, re.MULTILINE)
        if len(status) > MAX_LIST_BYTES or len(values) != 1:
            raise ArtifactError("unavailable-linux-proc-vmhwm")


def observation(output: bytes, suite: Suite) -> dict | None:
    """Require the completed parent fixture's record, never a child-only success."""
    schemas = {
        "correctness": (b"LSF_METADATA_CORRECTNESS ", "latent.catalog.metadata-correctness.v1", 4, 8192),
        "physical-resource": (b"LSF_METADATA_PHYSICAL ", "latent.catalog.metadata-working-set.v1", 32, 3145728),
    }
    if suite.required_job != "catalog":
        return None
    prefix, schema, releases, size = schemas[suite.classification]
    records = [line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)]
    if len(records) != 1:
        raise ArtifactError("missing-or-duplicate-suite-observation")
    value = json.loads(records[0], object_pairs_hook=unique_object)
    if (not isinstance(value, dict) or value.get("schemaVersion") != schema
            or value.get("releases") != releases
            or value.get("documentation_bytes_per_release") != size):
        raise ArtifactError("wrong-suite-observation")
    if suite.classification == "physical-resource":
        phases = value.get("phases")
        if (value.get("max_growth_kib") != 65536 or not isinstance(phases, list)
                or len(phases) != 3
                or [phase.get("mode") for phase in phases if isinstance(phase, dict)]
                != ["publish", "apply", "reopen"]):
            raise ArtifactError("incomplete-physical-observation")
    return value


def run_suite(repo: Path, inventory: Path, suite: Suite, env: dict[str, str],
              record: dict | None = None) -> None:
    prerequisites(suite, env)
    artifact = read_inventory(inventory, repo, suite)
    runtime_env = cargo_environment(repo, artifact, env)
    command = [str(artifact.executable), suite.filter]
    if suite.ignored:
        command.append("--ignored")
    if suite.exact:
        command.append("--exact")
    status, output = run_owned([*command, "--list"], cwd=artifact.package, env=runtime_env,
                               timeout=30, maximum=MAX_LIST_BYTES)
    if status:
        raise ArtifactError("libtest-list-failed")
    validate_listing(output, suite)
    if not suite.ignored:
        status, output = run_owned([*command, "--ignored", "--list"], cwd=artifact.package,
                                   env=runtime_env, timeout=30, maximum=MAX_LIST_BYTES)
        if status:
            raise ArtifactError("libtest-list-failed")
        validate_listing(output, replace(suite, names=frozenset()))
    execution = [*command, "--test-threads=1"]
    if suite.nocapture:
        execution.append("--nocapture")
    started = time.monotonic()
    if record is not None:
        record["execution_started"] = True
    try:
        status, output = run_owned(execution, cwd=artifact.package, env=runtime_env,
                                   timeout=suite.timeout_seconds, maximum=MAX_OUTPUT_BYTES)
    finally:
        if record is not None:
            record["execution_seconds"] = time.monotonic() - started
    print(output.decode("utf-8", errors="replace"), end="", flush=True)
    if record is not None:
        record["exit_code"] = status
    if status:
        raise ArtifactError("ignored-libtest-failed")
    expected = len(suite.names)
    results = re.findall(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;",
                         output, re.MULTILINE)
    # --nocapture includes child summaries. The final summary belongs to the parent.
    if not results or tuple(int(value) for value in results[-1]) != (expected, 0, 0):
        raise ArtifactError("ignored-libtest-result-mismatch")
    measured = observation(output, suite)
    if record is not None:
        record["passed_cases"] = expected
        record["observation"] = measured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--record", type=Path, help="write bounded stage/case observations, not a phase receipt")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    suite = SUITES[args.suite]
    record = {
        "schemaVersion": "latent.ci.libtest-execution.v1", "suite": args.suite,
        "source_commit": args.source_commit, "recipe": suite.recipe,
        "classification": suite.classification, "cases": sorted(suite.names),
        "assertions": suite.assertions, "execution_started": False, "outcome": "not-run",
        "platform": sys.platform, "architecture": platform.machine(),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "registry_sha256": hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
    }

    def interrupted(_signum: int, _frame: object) -> None:
        raise ArtifactError("test-interrupted")

    previous = signal.signal(signal.SIGTERM, interrupted)
    started = time.monotonic()
    result = 1
    try:
        env = dict(os.environ)
        require_source(repo, args.source_commit, env)
        run_suite(repo, args.inventory, suite, env, record)
        record["outcome"] = "passed"
        result = 0
    except (ArtifactError, OSError, ValueError, TypeError, RecursionError,
            subprocess.SubprocessError, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, ArtifactError) else "artifact-execution-failed"
        record["outcome"] = "failed" if record["execution_started"] else "not-run"
        record["reason"] = reason
        print(f"CI Rust artifacts: {reason}", file=sys.stderr)
    finally:
        signal.signal(signal.SIGTERM, previous)
        record["total_seconds"] = time.monotonic() - started
        if args.record is not None:
            try:
                args.record.parent.mkdir(parents=True, exist_ok=True)
                args.record.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            except OSError:
                print("CI Rust artifacts: execution-record-write-failed", file=sys.stderr)
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())

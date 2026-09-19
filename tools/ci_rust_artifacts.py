#!/usr/bin/env python3
"""Run selected ignored Rust tests from the current job's successful Cargo inventory.

The workflow must create the inventory with the ordinary workspace/all-targets/
all-features `cargo test --no-run --message-format=json` invocation on this checkout.
This consumes Cargo's artifact identities; it never discovers executables by glob.
The inventory is build metadata, not cached test or gate evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading

MAX_INVENTORY_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_RECORDS = 100_000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_LIST_BYTES = 64 * 1024
MAX_LINK_PATHS = 256
POLICY_PREFIX = "supply_chain::tests::support::operator_fixture::"
CURRENTNESS_PREFIX = "standalone::start::tests::trust_currentness::"


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
    kind: str = "lib"


SUITES = {
    "angular-t1-fixture": Suite(
        "apps/latentd/Cargo.toml", "phase3_angular_fixture", "tests/phase3_angular_fixture.rs",
        "export_actual_angular_t1_fixtures",
        frozenset({"export_actual_angular_t1_fixtures"}), True, "test"),
    "browser-boundary": Suite(
        "apps/latentd/Cargo.toml", "latentd", "src/lib_root.rs",
        "standalone::http::assets::browser::actual_browser_boundary_hydrates_navigates_and_blocks_injection_on_live_ingress",
        frozenset({"standalone::http::assets::browser::actual_browser_boundary_hydrates_navigates_and_blocks_injection_on_live_ingress"}), True),
    "operator-fixture": Suite(
        "crates/latent-policy/Cargo.toml", "latent_policy", "src/lib.rs",
        POLICY_PREFIX + "export_operator_workflow_fixture",
        frozenset({POLICY_PREFIX + "export_operator_workflow_fixture"}), True),
    "publication-fixture": Suite(
        "crates/latent-policy/Cargo.toml", "latent_policy", "src/lib.rs",
        POLICY_PREFIX + "export_publication_workflow_fixture",
        frozenset({POLICY_PREFIX + "export_publication_workflow_fixture"}), True),
    "resource-fixture": Suite(
        "crates/latent-policy/Cargo.toml", "latent_policy", "src/lib.rs",
        POLICY_PREFIX + "resources::export_phase2_resource_fixture",
        frozenset({POLICY_PREFIX + "resources::export_phase2_resource_fixture"}), True),
    "trust-currentness": Suite(
        "apps/latentd/Cargo.toml", "latentd", "src/lib_root.rs", CURRENTNESS_PREFIX,
        frozenset(CURRENTNESS_PREFIX + name for name in (
            "profile::external_profile_preserves_cold_warm_and_restart_requirements",
            "real_proof_age_expiry_denies_retained_native_work_with_a_current_clock_lease",
            "real_policy_expiry_denies_native_work_and_recovers_readable_negative_history",
            "real_publisher_revocation_denies_native_work_without_any_registry_event",
        )), False),
}


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
                    # Cargo only adds build-script search paths inside target.
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
                if target.get("kind") != [suite.kind] or profile.get("test") is not True:
                    continue
                if target.get("name") != suite.target:
                    continue
                if absolute_path(target.get("src_path")) != expected_source.resolve(strict=True):
                    raise ArtifactError("wrong-libtest-owner")
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


def run_suite(repo: Path, inventory: Path, suite: Suite, env: dict[str, str]) -> None:
    artifact = read_inventory(inventory, repo, suite)
    runtime_env = cargo_environment(repo, artifact, env)
    command = [str(artifact.executable), suite.filter, "--ignored"]
    if suite.exact:
        command.append("--exact")
    status, output = run_owned([*command, "--list"], cwd=artifact.package, env=runtime_env,
                               timeout=30, maximum=MAX_LIST_BYTES)
    if status:
        raise ArtifactError("libtest-list-failed")
    validate_listing(output, suite)
    status, output = run_owned([*command, "--test-threads=1"], cwd=artifact.package, env=runtime_env,
                               timeout=300, maximum=MAX_OUTPUT_BYTES)
    print(output.decode("utf-8", errors="replace"), end="", flush=True)
    if status:
        raise ArtifactError("ignored-libtest-failed")
    expected = len(suite.names)
    result = re.search(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;",
                       output, re.MULTILINE)
    if result is None or tuple(int(value) for value in result.groups()) != (expected, 0, 0):
        raise ArtifactError("ignored-libtest-result-mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]

    def interrupted(_signum: int, _frame: object) -> None:
        raise ArtifactError("test-interrupted")

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        env = dict(os.environ)
        require_source(repo, args.source_commit, env)
        run_suite(repo, args.inventory, SUITES[args.suite], env)
        return 0
    except (ArtifactError, OSError, ValueError, TypeError, RecursionError,
            subprocess.SubprocessError, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, ArtifactError) else "artifact-execution-failed"
        print(f"CI Rust artifacts: {reason}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())

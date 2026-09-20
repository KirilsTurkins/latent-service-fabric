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

try:
    from .owned_test_process import ProcessFailure, run_owned as supervise
except ImportError:
    from owned_test_process import ProcessFailure, run_owned as supervise

MAX_INVENTORY_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_RECORDS = 100_000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_LIST_BYTES = 64 * 1024
MAX_LINK_PATHS = 256
POLICY_PREFIX = "supply_chain::tests::support::operator_fixture::"
CURRENTNESS_PREFIX = "standalone::start::tests::trust_currentness::"
METADATA_TEST = ("deployments::tests::resources::compilation_memory::"
                 "large_release_metadata_has_a_bounded_compilation_working_set")
METADATA_SCHEMA = "latent.metadata-working-set.v1"


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
    timeout: int = 300
    platforms: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    resource_class: str = "integration"
    observation_schema: str | None = None


SUITES = {
    # Full-profile fallback until #427 qualifies narrower transitive selection.
    # Ordinary libtest excludes this ignored test; this is its single CI owner.
    "metadata-working-set": Suite(
        "crates/latent-control-store/Cargo.toml", "latent_control_store", "src/lib.rs",
        METADATA_TEST, frozenset({METADATA_TEST}), True,
        timeout=930, platforms=("linux",),
        prerequisites=("proc-vmhwm", "real-writable-filesystem"),
        resource_class="physical-exclusive", observation_schema=METADATA_SCHEMA),
    "angular-t1-fixture": Suite(
        "apps/latentd/Cargo.toml", "phase3_angular_fixture", "tests/phase3_angular_fixture.rs",
        "export_actual_angular_t1_fixtures",
        frozenset({"export_actual_angular_t1_fixtures"}), True, kind="test"),
    "browser-boundary": Suite(
        "apps/latentd/Cargo.toml", "latentd", "src/lib_root.rs",
        "standalone::http::assets::browser::actual_browser_",
        frozenset({"standalone::http::assets::browser::actual_browser_boundary_hydrates_navigates_and_blocks_injection_on_live_ingress",
                   "standalone::http::assets::browser::actual_browser_application_uses_only_the_public_shared_http_contract"}), False),
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


def read_inventory(path: Path, repo: Path, suite: Suite, *, target: Path | None = None) -> Artifact:
    repo = repo.resolve(strict=True)
    expected_manifest = (repo / suite.manifest).resolve(strict=True)
    expected_source = expected_manifest.parent / suite.source
    target_root = (target or repo / "target").resolve(strict=True)
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
    """Use the common bounded descendant owner, preserving artifact errors."""
    try:
        result = supervise(command, cwd=cwd, env=env, timeout=timeout, maximum=maximum)
    except ProcessFailure as error:
        reason = {"output-overflow": "test-output-limit", "infrastructure-timeout": "test-timeout",
                  "cancelled": "test-interrupted", "unavailable-environment": "test-prerequisite-unavailable"}.get(
                      error.category, "test-process-failed")
        raise ArtifactError(reason) from None
    if result.returncode is None:
        raise ArtifactError("test-exit-unobserved")
    return result.returncode, result.output


def require_source(repo: Path, expected: str | None, env: dict[str, str]) -> None:
    if expected is None or re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", expected) is None:
        raise ArtifactError("missing-source-commit")
    status, output = run_owned(["git", "-c", "gc.auto=0", "rev-parse", "--verify", "HEAD"],
                               cwd=repo, env=env, timeout=30, maximum=256)
    if status or output.strip().decode("ascii") != expected.lower():
        raise ArtifactError("inventory-source-checkout-mismatch")


def cargo_environment(repo: Path, artifact: Artifact, base: dict[str, str], *, execute=None,
                      target: Path | None = None) -> dict[str, str]:
    env = dict(base)
    execute = execute or run_owned
    status, output = execute(["rustc", "--print", "target-libdir"], cwd=repo,
                               env=env, timeout=30, maximum=4096)
    if status:
        raise ArtifactError("rust-library-path-unavailable")
    rust_libraries = absolute_path(output.decode("utf-8").strip())
    target_root = target or repo / "target"
    paths = [*artifact.link_paths, target_root / "debug/deps", target_root / "debug", rust_libraries]
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


def validate_metadata_observations(output: bytes) -> list[dict]:
    """Three completed processes, both measured scenarios, unchanged input budget.

    A passing outer libtest without these observations is not resource evidence.
    These values describe this one regression probe, not a Phase 2/3 receipt.
    """
    observations: list[dict] = []
    for line in output.decode("utf-8").splitlines():
        if line.startswith("LSF_METADATA_MEASUREMENT "):
            value = json.loads(line.removeprefix("LSF_METADATA_MEASUREMENT "),
                               object_pairs_hook=unique_object)
            if not isinstance(value, dict):
                raise ArtifactError("invalid-metadata-observation")
            observations.append(value)
    if len(observations) != 3:
        raise ArtifactError("missing-or-duplicate-metadata-observations")

    def integer(value: object) -> bool:
        return type(value) is int

    for value, mode in zip(observations, ("publish", "apply", "reopen")):
        fixed = {"schema": METADATA_SCHEMA, "mode": mode, "releases": 32,
                 "documentation_bytes_per_release": 3 * 1024 * 1024,
                 "max_growth_kib": 64 * 1024, "max_state_bytes": 512 * 1024,
                 "os": "linux"}
        if any(value.get(key) != expected or type(value.get(key)) is not type(expected)
               for key, expected in fixed.items()):
            raise ArtifactError("metadata-input-mismatch")
        if (not integer(value.get("wall_ns")) or value["wall_ns"] <= 0
                or not isinstance(value.get("arch"), str) or not value["arch"]):
            raise ArtifactError("missing-metadata-timing-or-host")
        observation = value.get("observation")
        if (not isinstance(observation, dict) or observation.get("mode") != mode
                or observation.get("complete") is not True):
            raise ArtifactError("incomplete-metadata-observation")
        if mode == "publish":
            if (type(observation.get("verified_releases")) is not int
                    or observation["verified_releases"] != 32
                    or type(observation.get("documentation_bytes")) is not int
                    or observation["documentation_bytes"] != 32 * 3 * 1024 * 1024):
                raise ArtifactError("incomplete-metadata-publication")
            continue
        scenarios = observation.get("scenarios")
        if not isinstance(scenarios, list) or len(scenarios) != 2:
            raise ArtifactError("incomplete-metadata-scenarios")
        for scenario, name in zip(scenarios, ("distinct-releases", "shared-release-distinct-scopes")):
            if (not isinstance(scenario, dict) or scenario.get("name") != name
                    or scenario.get("state_unchanged") is not (mode == "reopen")):
                raise ArtifactError("metadata-scenario-mismatch")
            fields = ("routes", "generation", "baseline_kib", "peak_kib", "growth_kib", "state_bytes")
            if any(not integer(scenario.get(key)) for key in fields):
                raise ArtifactError("missing-metadata-measurement")
            baseline, peak, growth = (scenario[key] for key in ("baseline_kib", "peak_kib", "growth_kib"))
            if (scenario["routes"] != 32 or scenario["generation"] != 1
                    or baseline <= 0 or peak < baseline or growth != peak - baseline
                    or not 0 <= growth <= 64 * 1024
                    or not 0 < scenario["state_bytes"] < 512 * 1024):
                raise ArtifactError("metadata-measurement-outside-contract")
    return observations


def run_suite(repo: Path, inventory: Path, suite: Suite, env: dict[str, str]) -> None:
    if suite.platforms and sys.platform not in suite.platforms:
        raise ArtifactError("unsupported-suite-platform")
    if suite.observation_schema == METADATA_SCHEMA:
        # Do not let inherited child mode or a diagnostic mutation bypass the parent.
        if any(key in env for key in ("LSF_DEPLOYMENT_MEMORY_MODE", "LSF_DEPLOYMENT_MEMORY_ROOT",
                                      "LSF_METADATA_RETAIN")):
            raise ArtifactError("unexpected-metadata-probe-input")
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
    execution = [*command, "--test-threads=1"]
    if suite.observation_schema is not None:
        execution.append("--show-output")
    status, output = run_owned(execution, cwd=artifact.package, env=runtime_env,
                               timeout=suite.timeout, maximum=MAX_OUTPUT_BYTES)
    print(output.decode("utf-8", errors="replace"), end="", flush=True)
    if status:
        raise ArtifactError("ignored-libtest-failed")
    expected = len(suite.names)
    result = re.search(rb"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;",
                       output, re.MULTILINE)
    if result is None or tuple(int(value) for value in result.groups()) != (expected, 0, 0):
        raise ArtifactError("ignored-libtest-result-mismatch")
    if suite.observation_schema == METADATA_SCHEMA:
        validate_metadata_observations(output)


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

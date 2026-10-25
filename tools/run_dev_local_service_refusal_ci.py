#!/usr/bin/env python3
"""One ordinary local-service fixture diagnosis, never a port or release qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import BuildProcessError, run_bounded_result

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "diag/local-service-refusal-20261025"
WORKFLOW = ".github/workflows/developer-local-service-refusal.yml"
MAX_SECONDS = 2400
MAX_LOG = 16 * 1024 * 1024
NATIVE_CASES = (
    "host::service::refusal::tests::disabled_and_first_per_activation_do_not_share_global_admission",
    "host::service::refusal::tests::typed_budget_refuses_coercion_unknown_details_and_private_error_text",
)
CONFIG_CASE = "config::tests::development::local_service_refusal_observation_requires_exact_consent_and_existing_local_provider"
PYTHON_CASES = (
    "test_two_cells_and_explicit_child_budget_only_follow_a_selected_local_fixture",
    "test_refusal_records_bind_the_failed_activation_after_expected_negative_cases",
    "test_refusal_reader_rejects_coerced_private_forged_or_foreign_observations",
    "test_refusal_probe_option_leaves_ordinary_log_rpc_path_untouched",
)
RECIPE = (
    WORKFLOW, "tools/run_dev_local_service_refusal_ci.py", "tools/build_dev_guest_tools.py",
    "tools/dev_tool_distribution.py", "tools/dev_node_application_probe.py",
    "tools/dev_local_service_fixture_probe.py", "tools/dev_workflow/local_service_refusals.py",
    "tools/dev_workflow/node_test_profile.py", "tools/dev_workflow/node_fixtures.py",
    "tools/dev_workflow/local_service_fixture.py", "tools/dev_workflow/node_output.py",
    "tools/dev_workflow/service.py", "tools/tests/test_dev_local_service_fixture.py",
    "apps/latentd/Cargo.toml", "apps/latentd/src/config.rs",
    "apps/latentd/src/config/development.rs", "apps/latentd/src/config/model.rs",
    "apps/latentd/src/config/runtime.rs", "apps/latentd/src/config/security.rs",
    "apps/latentd/src/config/tests/development.rs", "crates/latent-wasmtime/Cargo.toml",
    "crates/latent-wasmtime/src/config.rs", "crates/latent-wasmtime/src/config/profile.rs",
    "crates/latent-wasmtime/src/host.rs", "crates/latent-wasmtime/src/host/service.rs",
    "crates/latent-wasmtime/src/host/service/refusal.rs", "tools/toolchain.toml",
    "Cargo.toml", "Cargo.lock", ".cargo/managed-guest.toml", "wit/platform/invocation/package.wit",
    "tools/requirements.lock",
)


ALLOWED_SOURCE_CHANGES = frozenset({
    b"tools/tests/test_dev_local_service_fixture.py",
    b"tools/run_dev_local_service_refusal_ci.py",
    b"tools/ci/contracts/owners/tools/run_dev_local_service_refusal_ci.py.json",
})
PRIOR_FILTERED_TREE_SHA256 = "sha256:e075a17c434a9a720d242e08813ee6e3da05aad57e51a08c77580ecbf9ac6ca3"
PRIOR_NATIVE_CONTROLS = {
    "sourceCommit": "81e7c5a8e8d687d478bd502c35c5cca98e4f3fb9",
    "sourceTree": "343a620dc91522bc1b35759f2cd48b2c4d955fbf",
    "runId": 40156235393, "jobId": 121058134076, "artifactId": 12585211327,
    "artifactBytes": 17457,
    "artifactSha256": "sha256:d40994e1bb9f669c1f75685b978272ace5c9eae5be4eb3a684e1d0d846ca68bf",
    "overallStatus": "failed", "overallFailurePhase": "python-controls",
    "scope": "only-the-three-actually-passed-native-and-config-controls",
    "observerStdout": {"bytes": 334, "sha256": "sha256:9fdd45e5950f5df520f4dff02d7ba932efaa9b44401d5332614221ae7e283dfa"},
    "configStdout": {"bytes": 239, "sha256": "sha256:614fdae33b7d4376c8b1d26256ee0b6dc1ff3c35d39caff52d1e6c61ac857ab6"},
    "nativeCases": list(NATIVE_CASES), "configCases": [CONFIG_CASE],
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def identity(path, maximum):
    require(path.is_file() and not path.is_symlink(), "regular-input-required")
    require(path.stat().st_size <= maximum, "input-byte-bound")
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    require(len(data) <= maximum, "input-byte-bound")
    return {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}


def native_result(raw, expected):
    observed = re.findall(rb"^test ([a-zA-Z0-9_:]+) \.\.\. ok$", raw, re.M)
    require(sorted(name.decode() for name in observed) == sorted(expected), "exact-native-cases-required")
    summary = re.findall(rb"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;", raw)
    require(summary == [(str(len(expected)).encode(), b"0", b"0")], "native-zero-skip-summary-required")


def native_source_identity(raw):
    # One fixed Git inventory, not a prior checkout/fetch or a rebuilt envelope.
    require(0 < len(raw) <= MAX_LOG and raw.endswith(b"\0"), "bounded-git-tree-required")
    canonical, exempt = [], set()
    for entry in raw[:-1].split(b"\0"):
        fields = entry.split(b"\t", 1)
        require(len(fields) == 2, "git-tree-record-invalid")
        header, path = fields
        if path in ALLOWED_SOURCE_CHANGES:
            require(path not in exempt and header.startswith(b"100644 blob "), "regular-exempt-source-required")
            exempt.add(path)
        else:
            canonical.append(entry + b"\0")
    require(exempt == ALLOWED_SOURCE_CHANGES, "all-three-source-exceptions-required")
    observed = "sha256:" + hashlib.sha256(b"".join(canonical)).hexdigest()
    require(observed == PRIOR_FILTERED_TREE_SHA256, "prior-native-source-tree-drift")
    return {"filteredTreeSha256": observed, "inventoryBytes": len(raw),
            "unchangedTrackedEntries": len(canonical),
            "excludedPaths": sorted(path.decode("ascii") for path in exempt)}


def run(python_prefix: Path, output: Path):
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(), "new-unprivileged-linux-owner-required")
    require(os.environ.get("GITHUB_EVENT_NAME") == "push" and os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH,
            "exact-diagnostic-push-required")
    origin = os.environ.get("GITHUB_WORKFLOW_REF")
    require(origin == "KirilsTurkins/latent-service-fabric/" + WORKFLOW + "@refs/heads/" + BRANCH, "exact-workflow-required")
    output.mkdir(parents=True, mode=0o700)
    logs = output / "commands"
    logs.mkdir(mode=0o700)
    until = time.monotonic() + MAX_SECONDS
    environment = build_environment(output)
    environment.update(RUSTUP_TOOLCHAIN="1.97.1", GITHUB_ACTIONS="true", RUNNER_OS="Linux")
    receipt = {"schemaVersion": "latent.dev.local-service-refusal-ci.v1", "status": "failed",
               "scope": "ordinary-signed-local-service-fixture-diagnostic", "qualificationComplete": False,
               "publisherAuthenticated": False, "maximumSeconds": MAX_SECONDS, "workflowOrigin": origin,
               "runId": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
               "commands": [], "originalFixtureAssertionsChanged": False, "limitsChanged": False,
               "nativeCases": [], "configCases": [], "pythonCases": [], "originalTestsPassed": None}

    def command(name, argv, cap):
        require(time.monotonic() < until, "overall-deadline")
        receipt["phase"] = name
        started = time.monotonic()
        result = run_bounded_result([str(item) for item in argv], cwd=ROOT, env=environment,
            timeout_seconds=min(cap, until - started), max_output_bytes=MAX_LOG)
        (logs / (name + ".stdout")).write_bytes(result.stdout)
        (logs / (name + ".stderr")).write_bytes(result.stderr)
        receipt["commands"].append({"name": name, "argv": [str(item) for item in argv],
            "seconds": time.monotonic() - started, "exitCode": result.returncode,
            "stdout": identity(logs / (name + ".stdout"), MAX_LOG),
            "stderr": identity(logs / (name + ".stderr"), MAX_LOG)})
        require(result.returncode == 0, "command-exit:" + name)
        return result

    try:
        commit = command("source-head", ["git", "rev-parse", "HEAD"], 15).stdout.decode().strip()
        require(re.fullmatch(r"[0-9a-f]{40}", commit) and commit == os.environ.get("GITHUB_SHA"), "exact-source-head-required")
        receipt["sourceCommit"] = commit
        receipt["sourceTree"] = command("source-tree", ["git", "rev-parse", "HEAD^{tree}"], 15).stdout.decode().strip()
        require(re.fullmatch(r"[0-9a-f]{40}", receipt["sourceTree"]), "exact-source-tree-required")
        require(not command("clean-source", ["git", "status", "--porcelain"], 15).stdout, "clean-source-required")
        receipt["recipe"] = {name: identity(ROOT / name, 4 * 1024 * 1024) for name in RECIPE}
        command("builder-import-preflight", [sys.executable, "tools/build_dev_guest_tools.py", "--help"], 60)
        fixture_help = command("fixture-cli-preflight", [sys.executable, "tools/dev_local_service_fixture_probe.py", "--help"], 60)
        require(b"--observe-refusals" in fixture_help.stdout, "explicit-fixture-option-required")
        source_tree = command("prior-native-source-tree", ["git", "ls-tree", "-r", "-z", "HEAD"], 15)
        receipt["nativeSourceIdentity"] = native_source_identity(source_tree.stdout)
        receipt["priorNativeControls"] = PRIOR_NATIVE_CONTROLS
        receipt["currentExecutionScope"] = "native-and-config-controls-only"
        receipt["currentExecution"] = "not-run;prior-source-exact"
        controls = command("python-controls", [sys.executable, "-m", "unittest", "-v",
            *("tools.tests.test_dev_local_service_fixture.LocalServiceFixture." + case for case in PYTHON_CASES)], 60)
        passed_python = re.findall(rb"^(test_[a-zA-Z0-9_]+) \([^\n]+\) \.\.\. ok$", controls.stderr, re.M)
        require(sorted(name.decode() for name in passed_python) == sorted(PYTHON_CASES)
                and b"Ran 4 tests" in controls.stderr and controls.stderr.rstrip().endswith(b"OK"), "four-python-cases-zero-skip-required")
        receipt["pythonCases"] = list(PYTHON_CASES)
        command("normal-rust-tools-and-node", [sys.executable, "tools/build_dev_guest_tools.py", "--language", "rust",
            "--output", "target/local-service-tools", "--python-prefix", python_prefix, "--node-tests"], 1800)
        source_node = ROOT / "target/local-service-tools/source-node/source-node.json"
        receipt["sourceNode"] = identity(source_node, 65536)
        command("original-local-service-fixture", [sys.executable, "tools/dev_local_service_fixture_probe.py",
            "--payload", "target/local-service-tools/payload", "--source-node", "target/local-service-tools/source-node",
            "--output", output / "fixture", "--observe-refusals"], 900)
        result = output / "fixture/node/node-tests.json"
        receipt["originalNodeTests"] = identity(result, 256 * 1024)
        receipt["originalTestsPassed"] = json.loads(result.read_bytes()).get("passed")
        require(receipt["originalTestsPassed"] is True, "original-fixture-did-not-pass")
        require(receipt["recipe"] == {name: identity(ROOT / name, 4 * 1024 * 1024) for name in RECIPE}, "source-changed")
        require(time.monotonic() < until, "overall-deadline")
        receipt["status"] = "passed"
        receipt["phase"] = "complete"
    except (ValueError, BuildProcessError) as error:
        receipt["failure"] = str(error)
        raise
    finally:
        result = output / "fixture/node/node-tests.json"
        if result.is_file():
            try:
                receipt["originalNodeTests"] = identity(result, 256 * 1024)
                receipt["originalTestsPassed"] = json.loads(result.read_bytes()).get("passed")
            except (ValueError, OSError):
                receipt["originalTestsObservation"] = "unavailable"
                receipt["status"] = "failed"
        # The original failed test remains failed; no expected-negative rewriting.
        (output / "NODE-LOCAL-SERVICE-REFUSAL.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.python_prefix.resolve(strict=True), args.output.absolute())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

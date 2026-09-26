#!/usr/bin/env python3
"""Execute the maintained AOT matrix from exact prepared Cargo products.

--compare runs identical cases with original and stripped worker inputs, then
repeats the stripped selection to expose reuse cost. No build tools run here.
Observations are same-job performance data, never sandbox qualification receipts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import aot_test_inputs as inputs
from tools import ci_rust_artifacts as artifacts

SUPERVISOR_CASES = frozenset("""readiness-success readiness-malformed probe-launch-mismatch
probe-stalled-launch readiness-wrong-digest readiness-relative-path oversized zero
truncated-header truncated-body trailing nonzero-exit diagnostic-overflow
cancel-running-prefix malformed-readiness launch-mismatch stalled-launch
fragmented-success running-deadline last-owner-drop active-shutdown
inherited-descriptor healthy-after-failures""".split())
ISOLATED_CASES = frozenset({
    "ownership::real_compile_binds_exact_source_and_keeps_output_capacity_until_drop",
    "ownership::cancelled_unstarted_job_retains_its_reservation_until_consumed",
    "ownership::queued_deadline_is_not_restarted_when_the_job_runs",
    "ownership::shutdown_does_not_refund_a_held_job_and_closes_admission",
    "source::tampered_component_is_rejected_by_the_fresh_catalog_read",
    "source::queued_job_cannot_upgrade_its_revoked_lifecycle_capability",
    "source::over_budget_and_noncanonical_sources_fail_before_fresh_io",
    "source::compiler_binary_digest_and_actual_engine_profile_are_checked",
    "source::invalid_portable_bytes_fail_in_the_child_without_a_trusted_output",
    "prepared_negative::prepared_missing_and_modified_executables_are_rejected",
    "prepared_negative::prepared_wrong_digest_profile_and_stale_identities_are_rejected",
    "prepared_negative::prepared_wrong_role_and_symlinks_are_rejected",
    "prepared_negative::replacement_after_configuration_is_rejected_and_compilation_recovers",
})
NATIVE_CASES = frozenset({
    "ownership::evicted_ready_handle_keeps_its_image_and_revocation_never_recovers_from_native_cache",
    "reopen::identical_component_after_restart_requires_its_exact_engine_before_native_reuse",
    "reopen::real_miss_invokes_then_reopened_native_hit_verifies_source_without_compiling",
    "tamper::replaced_bytes_with_matching_sha_and_wrong_host_key_never_reach_the_loader",
})
CASES = dict(zip(inputs.HARNESS_NAMES, (SUPERVISOR_CASES, ISOLATED_CASES, NATIVE_CASES)))
BUILD_TOOLS = ("cargo", "rustc", "rustup", "npm", "npx", "objcopy", "strip", "curl", "wget")
MAX_LOG = 4 * 1024 * 1024


def listing(raw: bytes, expected: frozenset[str]) -> None:
    # Reuse the maintained libtest parser; the custom harness implements its list format.
    artifacts.validate_listing(raw, artifacts.Suite("", "", "", "", expected, False))


def validate_case_coverage(text: str, suite: str) -> None:
    """Check actual completed cases independently of optional timing records."""
    summaries = re.findall(r"^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; "
                           r"(\d+) measured; (\d+) filtered out", text, re.MULTILINE)
    if summaries != [(str(len(CASES[suite])), "0", "0", "0", "0")]:
        raise inputs.InputError("incomplete-or-failed-case-set")
    if "NOT RUN" in text:
        raise inputs.InputError("required-linux-cases-not-run")
    if suite == "aot_supervisor":
        records = [line for line in text.splitlines() if line.startswith("LSF_AOT_CASE ")]
        if len(records) != 2 * len(CASES[suite]):
            raise inputs.InputError("supervisor-case-coverage-mismatch")
        for outcome in ("started", "passed"):
            names = re.findall(rf"^LSF_AOT_CASE {outcome} (\S+)$", text, re.MULTILINE)
            if Counter(names) != Counter(CASES[suite]):
                raise inputs.InputError("supervisor-case-coverage-mismatch")
    else:
        # --nocapture can interleave a test's progress prefix with stage records.
        names = re.findall(r"(?:^|\n)test (\S+) \.\.\. ", text)
        if Counter(names) != Counter(CASES[suite]):
            raise inputs.InputError("libtest-case-coverage-mismatch")


def result(raw: bytes, suite: str) -> dict:
    text = raw.decode("utf-8", errors="strict")
    validate_case_coverage(text, suite)
    observations = []
    current = "setup"
    stages: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        if line.startswith("LSF_AOT_CASE started "):
            current = line.removeprefix("LSF_AOT_CASE started ")
        elif match := re.match(r"test (\S+) \.\.\. ", line):
            current = match[1]
        for prefix in ("LSF_AOT_STAGE ", "LSF_AOT_MEASURE "):
            if prefix not in line:
                continue
            record = json.loads(line.split(prefix, 1)[1])
            if record.get("outcome") == "started":
                continue
            elapsed = record["elapsed_ns"]
            if not isinstance(elapsed, int) or elapsed < 0 or elapsed > 600_000_000_000:
                raise inputs.InputError("invalid-stage-observation")
            stage = record["stage"]
            if not isinstance(stage, str) or len(stage) > 80:
                raise inputs.InputError("invalid-stage-name")
            record["case"] = current
            observations.append(record)
            stages[stage] += elapsed
    if not observations or len(observations) > 4096:
        raise inputs.InputError("missing-or-excessive-stage-observations")
    if "production-executable-verification" not in stages:
        raise inputs.InputError("missing-production-verification-timings-build-all-features")
    return {"cases": sorted(CASES[suite]), "stage_ns": dict(stages), "observations": observations}


def sentinels(root: Path) -> Path:
    root.mkdir()
    log = root / "unexpected-tools"
    # Deliberately failing executable names. This is detection, NOT a sandbox:
    # an absolute-path invocation can bypass PATH. The runner also permits only
    # exact inventoried harness paths at its own subprocess boundary.
    for tool in BUILD_TOOLS:
        path = root / tool
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$LSF_AOT_TOOL_LOG"\nexit 97\n')
        path.chmod(0o755)
    return log


def execute(repo: Path, manifest_path: Path, report_dir: Path, compare: bool) -> dict:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise inputs.InputError("not-run-linux-x86_64-required")
    started = time.monotonic_ns()
    manifest = inputs.validate(repo, manifest_path)
    validation_ns = time.monotonic_ns() - started
    if report_dir.exists():
        raise inputs.InputError("report-directory-exists")
    report_dir.mkdir(parents=True)
    report = {"schema": "latent.aot-test-observations.v1", "checkout": manifest["checkout"],
              "preparation_ns": manifest["preparation_ns"],
              "preparation_total_ns": manifest["preparation_total_ns"],
              "initial_validation_ns": validation_ns,
              "executables": manifest["entries"], "runs": [],
              "passed": False, "qualification": "test-input-performance-only"}
    modes = ("original", "prepared", "reused") if compare else ("prepared",)
    try:
        with tempfile.TemporaryDirectory(prefix="lsf-aot-tools-") as temporary:
            sentinel = Path(temporary) / "bin"
            tool_log = sentinels(sentinel)
            for mode in modes:
                start = time.monotonic_ns()
                # Repeat exact validation for reused artifacts; no cached success receipts.
                inputs.validate(repo, manifest_path)
                mode_record = {"mode": mode, "validation_ns": time.monotonic_ns() - start, "suites": {}}
                report["runs"].append(mode_record)
                for suite in inputs.HARNESS_NAMES:
                    env = dict(os.environ)
                    for key in ("LSF_AOT_TEST_INPUTS", "LSF_AOT_TEST_INPUTS_SHA256", "LSF_AOT_TEST_EXECUTION_ONLY"):
                        env.pop(key, None)
                    env.update(manifest["runtime"])
                    if mode != "original":
                        env.update(inputs.environment(manifest_path, manifest))
                    env.update(LSF_AOT_TEST_TIMINGS="1", LSF_AOT_REQUIRE_LINUX="1",
                               LSF_AOT_TOOL_LOG=str(tool_log),
                               PATH=str(sentinel) + os.pathsep + env.get("PATH", ""))
                    binary = Path(manifest["entries"][suite]["original"]["path"])
                    package = repo / "crates/latent-wasmtime"
                    print(f"AOT {mode}/{suite}: starting exact maintained case set", flush=True)
                    status, output = artifacts.run_owned([str(binary), "--list"], cwd=package, env=env,
                                                         timeout=30, maximum=artifacts.MAX_LIST_BYTES)
                    if status:
                        raise inputs.InputError("case-list-failed")
                    listing(output, CASES[suite])
                    start = time.monotonic_ns()
                    status, output = artifacts.run_owned([str(binary), "--test-threads=1", "--nocapture"],
                                                         cwd=package, env=env, timeout=600, maximum=MAX_LOG)
                    elapsed = time.monotonic_ns() - start
                    (report_dir / f"{mode}-{suite}.log").write_bytes(output)
                    if status:
                        print(output[-12000:].decode("utf-8", errors="replace"), file=sys.stderr)
                        raise inputs.InputError(f"case-execution-failed-{mode}-{suite}")
                    if tool_log.exists():
                        raise inputs.InputError("unexpected-execution-build-tool")
                    mode_record["suites"][suite] = {**result(output, suite), "execution_ns": elapsed}
                    print(f"AOT {mode}/{suite}: {len(CASES[suite])} passed, {elapsed / 1e9:.3f}s", flush=True)
            report["passed"] = True
            report["unexpected_build_tool_calls"] = 0
            return report
    finally:
        (report_dir / "observations.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args(argv)
    try:
        execute(Path(__file__).resolve().parents[1], args.manifest.absolute(), args.report_dir.absolute(), args.compare)
        return 0
    except (inputs.InputError, artifacts.ArtifactError, OSError, ValueError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error, (inputs.InputError, artifacts.ArtifactError)) else "invalid-aot-test-input"
        print(f"AOT tests: {reason}\nPrepare explicitly: {inputs.PREPARE}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Current-source Linux controls for the optional prepaid C upload window.

These controls do not build a C component, run a signed guest, or qualify a
host boundary. The output is bounded evidence for the named source tests only.
"""
from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parents[1]
MAX_LOG = 4 * 1024 * 1024
TIMEOUT = 900

CASES = (
    ("latent-capabilities", (), (
        "broker::io::transfer::native_tests::prepared_http_owner_drops_real_unsubmitted_input_before_upload_on_drop_and_cancel",
        "broker::io::transfer::native_tests::prepared_input_captures_once_without_callbacks_and_retains_the_original_owner",
        "broker::io::transfer::native_tests::prepared_input_refuses_foreign_owners_cancellation_and_unfunded_capacity",
        "broker::io::transfer::native_tests::prepared_input_refuses_the_logical_only_profile_before_allocation",
    )),
    ("latent-http", (), tuple("tests::streaming::" + name for name in (
        "prepared_upload_uses_the_original_small_window_and_sends_each_chunk_once",
        "prepared_upload_rejects_excess_declared_length_before_send",
        "prepared_upload_preserves_the_original_cumulative_input_limit",
        "prepared_upload_cancel_retires_original_connection_and_disallows_reuse",
        "prepared_upload_release_completes_with_the_same_provider",
        "prepared_upload_unpolled_future_drops_input_before_its_original_upload",
        "prepared_upload_cancel_keeps_a_retained_transport_chunk_on_its_original_ledger",
    ))),
    ("latent-packaging", (), (
        "semantics::host::tests::upload_window_requires_the_exact_original_operational_resource",
    )),
    ("latent-component-threading", (), (
        "c_context::tests::shared_parallel_memory_cannot_select_the_cooperative_mechanism",
    )),
    ("latent-wasmtime", ("--features", "http-upload-window"), (
        "bindings::tests::upload_window_manifest_preserves_prior_interfaces_and_exact_source_identity",
        "surface::tests::upload_window_requires_one_original_operational_resource_identity",
        "host::streaming_http::table::tests::failed_window_restore_retains_the_detached_upload_until_the_caller_drops_it",
        "host::streaming_http::upload_drop_tests::real_canonical_upload_drop_currently_runs_before_the_guest_marker",
        "host::streaming_http::upload_drop_tests::trapped_upload_is_retained_until_the_actual_store_drops",
        "host::streaming_http::upload_drop_tests::abandoned_wait_retains_the_upload_until_the_actual_store_drops",
        "host::streaming_http::upload_drop_tests::real_pending_canonical_borrow_rejects_drop_before_the_upload_destructor",
        "backend::preparation::compilation::tests::upload_window_requires_the_c_authenticated_profile_before_linking",
        "component_threading::tests::upload_window_host_authentication_rejects_handcrafted_shared_original_memory",
    )),
    ("latentd", (), (
        "config::tests::engine::upload_window_input_is_a_strict_engine_opt_in",
        "config::tests::providers::activation_runtime::protected_c_upload_window_selects_v8_only_with_original_streaming_provider",
    )),
)

PYTHON_CASES = tuple("tools.tests.test_c_standard_facilities.StandardFacilities." + name for name in (
    "test_libfetch_profile_derives_only_typed_streams_and_preserves_dependency_selection",
    "test_libfetch_window_profiles_select_the_original_owner_and_reserved_adapter",
    "test_libfetch_unthreaded_build_refuses_before_binding_generation_or_output",
    "test_upload_window_owner_rejects_missing_or_duplicate_test_evidence",
)) + tuple("tools.tests.test_c_thread_minimal.CThreadMinimal." + name for name in (
    "test_unsolicited_partial_inverse_requires_exact_reviewed_source",
    "test_upload_window_inverse_refuses_missing_duplicate_modified_and_unrelated_drift",
    "test_minimal_overlay_preserves_every_original_byte_and_full_standard_lifecycle_calls",
    "test_only_application_main_changes_and_all_original_limits_profile_wit_remain_exact",
    "test_file_abi_addendum_refuses_missing_duplicate_modified_and_unrelated_source_drift",
))


def require_one(output: bytes, name: str) -> None:
    """A successful cargo process with zero or duplicate tests is a refusal."""
    lines = output.decode("utf-8", "replace").splitlines()
    if lines.count(f"test {name} ... ok") != 1 or sum(
        line.startswith("test result: ok. 1 passed; 0 failed; 0 ignored;") for line in lines
    ) != 1:
        raise ValueError("exact-test-result-missing:" + name)


def require_discovery(output: bytes, names: tuple[str, ...]) -> None:
    lines = output.decode("utf-8", "replace").splitlines()
    for name in names:
        if lines.count(name + ": test") != 1:
            raise ValueError("exact-test-discovery-missing:" + name)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def stop_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run(output: Path, records: list[dict], label: str, command: list[str]) -> bytes:
    path = output / f"{len(records) + 1:02d}-{label}.log"
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    state = {"size": 0, "overflow": False, "read_error": None}

    def collect() -> None:
        try:
            with path.open("xb") as sink:
                while True:
                    chunk = os.read(process.stdout.fileno(), 8192)
                    if not chunk:
                        break
                    if state["size"] + len(chunk) > MAX_LOG:
                        state["overflow"] = True
                        stop_group(process)
                        break
                    sink.write(chunk)
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                    state["size"] += len(chunk)
        except Exception as error:  # Preserve a failed receipt if I/O fails.
            state["read_error"] = type(error).__name__
            stop_group(process)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_group(process)
        process.wait()
    reader.join(timeout=5)
    if reader.is_alive():
        stop_group(process)
        reader.join(timeout=5)
    content = path.read_bytes() if path.exists() else b""
    records.append({"label": label, "argv": command, "exitCode": process.returncode,
                    "seconds": round(time.monotonic() - started, 3), "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(), "log": path.name,
                    "timedOut": timed_out, "overflow": state["overflow"],
                    "readerError": state["read_error"]})
    if (process.returncode != 0 or timed_out or state["overflow"] or state["read_error"]
            or reader.is_alive()):
        raise RuntimeError("control-command-failed:" + label)
    return content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("linux-x86-64-required")
    if not re.fullmatch("[0-9a-f]{40}", args.expected_revision):
        raise ValueError("exact-git-revision-required")
    output = args.output.absolute()
    if output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("output-must-not-be-inside-source")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    records: list[dict] = []
    receipt = {"schemaVersion": "latent.c-http-upload-window-controls.v1",
               "sourceRevision": None, "expectedRevision": args.expected_revision,
               "status": "failed", "signedGuest": False, "hostBoundaryQualified": False,
               "canonicalDropScope": {
                   "engine": "direct-wasmtime-linker",
                   "componentAuthentication": "not-invoked",
                   "upload": "synthetic",
                   "preparedInput": "none",
                   "pendingResourceBorrow": "synthetic-host-call-only",
                   "actualPendingProviderWrite": "not-tested",
                   "signedC": "not-run",
               },
               "commands": records}
    try:
        head = git("rev-parse", "--verify", "HEAD")
        receipt["sourceRevision"] = head
        if head != args.expected_revision or git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("source-revision-or-cleanliness-mismatch")
        # These are distinct feature closures: old default host and the
        # ordinary node's new, explicit opt-in compiled into its binary.
        run(output, records, "default-host-check", ["cargo", "check", "--locked", "-p", "latent-wasmtime"])
        run(output, records, "node-production-check", ["cargo", "check", "--locked", "-p", "latentd"])
        for package, features, names in CASES:
            prefix = ["cargo", "test", "--locked", "-p", package, "--lib", *features]
            discovered = run(output, records, package + "-discovery", [*prefix, "--", "--list"])
            require_discovery(discovered, names)
            for ordinal, name in enumerate(names, 1):
                result = run(output, records, f"{package}-{ordinal}",
                             [*prefix, name, "--", "--exact", "--nocapture", "--test-threads=1"])
                require_one(result, name)
        result = run(output, records, "c-source-profile", [sys.executable, "-m", "unittest", "-v", *PYTHON_CASES])
        text = result.decode("utf-8", "replace")
        if (text.count(" ... ok") != len(PYTHON_CASES)
                or f"Ran {len(PYTHON_CASES)} tests" not in text or "\nOK" not in text):
            raise ValueError("c-source-profile-exact-results-missing")
        if git("rev-parse", "--verify", "HEAD") != head or git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("source-changed-during-controls")
        receipt["status"] = "passed"
        return 0
    except Exception as error:
        receipt["failure"] = str(error)[:512]
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

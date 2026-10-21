"""Focused broker-owner execution and stream-source compile; no kernel build."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.owned_test_process import ProcessFailure, run_owned

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    "Cargo.toml", "Cargo.lock", "rust-toolchain.toml",
    "crates/latent-capabilities/src/broker/pools.rs",
    "crates/latent-capabilities/src/broker/pools/admission.rs",
    "crates/latent-capabilities/src/broker/pools/protocol.rs",
    "crates/latent-capabilities/src/broker/pools/tests/protocol.rs",
    "crates/latent-streams/src/connection.rs",
    "crates/latent-streams/src/kernel.rs",
    "tools/qualify_stream_kernel_owners.py",
)
PREFIX = "broker::pools::tests::protocol::"
CASES = (
    "queued_scope_checks_policy_after_waiting_and_does_not_close_the_store",
    "retained_queue_scope_cannot_reopen_a_dropped_store",
    "followup_keeps_the_original_deadline_and_can_progress_with_one_running_slot",
    "narrowed_timeout_cannot_be_refreshed_after_queueing",
    "protocol_metadata_reserves_before_work_and_survives_provider_retirement",
    "kernel_occupancy_retains_original_io_request_scope_and_memory",
    "kernel_occupancy_rejects_foreign_scope_and_nonoriginal_allowance",
    "stopped_kernel_occupancy_fails_checkpoint_without_refunding_owner",
    "kernel_backing_uses_existing_fixed_metadata_ceiling",
)


def materials() -> dict:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE}


def verify_tests(stdout: bytes) -> None:
    text = stdout.decode("utf-8", "strict")
    actual = re.findall(r"^test (\S+) \.\.\. ok$", text, re.M)
    if sorted(actual) != sorted(PREFIX + name for name in CASES) or not re.search(
        r"^test result: ok\. 9 passed; 0 failed; 0 ignored;", text, re.M
    ):
        raise ValueError("owner-test-identity-or-terminal-result")


def capture(command: list[str], environment: dict[str, str], timeout: int,
            output: Path, label: str):
    def retain(result):
        if len(result.output) + len(result.stderr) > 1048576:
            raise ValueError("owner-output-capture-bound")
        (output / (label + ".stdout")).write_bytes(result.output)
        (output / (label + ".stderr")).write_bytes(result.stderr)
    try:
        result = run_owned(command, cwd=ROOT, env=environment,
            timeout=timeout, maximum=1048576, separate_stderr=True)
    except ProcessFailure as failure:
        try:
            if failure.result is not None:
                retain(failure.result)
            (output / (label + "-failure.json")).write_bytes((json.dumps({
                "category": failure.category, "reason": failure.reason,
                "completed": False}) + "\n").encode())
        except (OSError, ValueError):
            # Storage exhaustion or a violated internal capture guarantee must
            # not replace the exact original process/cleanup failure.
            pass
        raise
    retain(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    before = materials()
    environment = dict(os.environ, CARGO_BUILD_JOBS="2", CARGO_INCREMENTAL="0",
        CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_TEST_DEBUG="0",
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS="true", CARGO_PROFILE_TEST_DEBUG_ASSERTIONS="true",
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS="true", CARGO_PROFILE_TEST_OVERFLOW_CHECKS="true")
    commands = (
        ("broker-owners", ["cargo", "test", "--locked", "-p", "latent-capabilities", "--lib",
            PREFIX, "--", "--show-output", "--test-threads=1"], 600),
        ("stream-compile", ["cargo", "check", "--locked", "-p", "latent-streams", "--all-features"], 300),
    )
    rows = []
    for label, command, timeout in commands:
        result = capture(command, environment, timeout, args.output, label)
        if result.returncode:
            raise ValueError(label + "-failed-inspect-retained-bounded-stderr")
        if label == "broker-owners":
            verify_tests(result.output)
        rows.append({"label": label, "exitCode": result.returncode,
            "stdoutSha256": hashlib.sha256(result.output).hexdigest(),
            "stderrSha256": hashlib.sha256(result.stderr).hexdigest()})
    after = materials()
    if before != after:
        raise ValueError("owner-source-changed")
    receipt = {"schemaVersion": "lsf.stream-kernel-owners.v1", "source": before,
        "sourceAfter": after, "cases": [PREFIX + name for name in CASES], "rows": rows,
        "kernelBuilt": False, "trustedFactoryInstalled": False,
        "completeAllocationClosure": False, "finalFreeCertified": False,
        "productionInstallation": False}
    (args.output / "receipt.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    print(json.dumps({"brokerTests": len(CASES), "streamCompiled": True, "kernelBuilt": False}))


if __name__ == "__main__":
    main()

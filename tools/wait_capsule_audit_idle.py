#!/usr/bin/env python3
"""Observe bounded audit ownership before a guide's single cleanup mutation.

This helper issues only capability-list reads, never grants or mutations. An
idle snapshot is not admission authority: the later deletion still checks its
generation, policy and actual capacity once. No uncertain effect is retried.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import BuildProcessError, run_bounded

MAX_SECONDS = 5
MAX_OBSERVATIONS = 32
MAX_OUTPUT_BYTES = 65536
COUNTERS = ("audit_pending_attempts", "audit_queued_operations", "audit_queued_bytes",
            "audit_reserved_records", "audit_reserved_bytes", "audit_query_owners", "audit_query_bytes",
            "audit_stage_bytes")
STATES = ("audit_closed", "audit_recovery_pending")
UNRELATED_UNAVAILABLE = {"provider-pools-no-retained-owner", "provider-io-no-retained-pool-owner"}


class AuditDrainError(ValueError):
    """Static diagnostics only; no credentials, response bytes or paths."""


def require(value, reason):
    if not value:
        raise AuditDrainError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "audit-observation-duplicate-key")
        result[key] = value
    return result


def reject_number(_value):
    raise AuditDrainError("audit-observation-number")


def counters(raw: bytes) -> dict[str, int]:
    require(len(raw) <= MAX_OUTPUT_BYTES, "audit-observation-output-limit")
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_float=reject_number,
                           parse_constant=reject_number)
    except (ValueError, RecursionError, UnicodeError) as error:
        if isinstance(error, AuditDrainError):
            raise
        raise AuditDrainError("audit-observation-invalid-json") from None
    require(isinstance(value, dict) and value.get("schemaVersion") == "latent.cli.result.v1"
            and value.get("command") == "capability list" and value.get("category") == "success"
            and value.get("error") is None and value.get("outcomeKnown") is True
            and value.get("requestDispatched") is True, "audit-observation-not-successful")
    data = value.get("data")
    require(isinstance(data, dict) and "nextPageToken" in data and data["nextPageToken"] is None,
            "audit-observation-incomplete")
    usage = data.get("nodeUsage")
    require(isinstance(usage, dict) and usage.get("scope") == "node",
            "audit-observation-unavailable")
    unavailable = usage.get("unavailable")
    require(isinstance(unavailable, list) and len(unavailable) <= len(UNRELATED_UNAVAILABLE)
            and all(isinstance(item, str) and item in UNRELATED_UNAVAILABLE for item in unavailable)
            and len(set(unavailable)) == len(unavailable), "audit-observation-unavailable")
    values = usage.get("counters")
    require(isinstance(values, dict) and 0 < len(values) <= 256, "audit-observation-counters")
    decoded = {}
    for name, value in values.items():
        require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                and isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value),
                "audit-observation-counter-shape")
        decoded[name] = int(value)
        require(decoded[name] < 2**64, "audit-observation-counter-overflow")
    require(all(name in decoded for name in (*COUNTERS, *STATES)), "audit-observation-missing-counter")
    require(decoded["audit_closed"] == 0, "audit-observation-closed")
    require(decoded["audit_recovery_pending"] == 0, "audit-observation-recovery-pending")
    return {name: decoded[name] for name in (*COUNTERS, *STATES)}


def wait(cli: Path, config: Path, deployment: str, *, timeout_seconds=MAX_SECONDS) -> dict:
    require(type(timeout_seconds) in {int, float} and 0 < timeout_seconds <= MAX_SECONDS
            and math.isfinite(timeout_seconds), "audit-drain-deadline-invalid")
    require(isinstance(deployment, str) and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", deployment)
            and len(deployment) <= 64, "audit-drain-deployment-invalid")
    cli, config = Path(cli).resolve(strict=True), Path(config).resolve(strict=True)
    require(cli.is_file() and config.is_file(), "audit-drain-input-file")
    started = time.monotonic()
    deadline = started + timeout_seconds
    for observation in range(1, MAX_OBSERVATIONS + 1):
        remaining = deadline - time.monotonic()
        require(remaining > 0, "audit-drain-deadline")
        # CLI and process have independent finite bounds. Owned descendant
        # cleanup retains the existing additional five-second cleanup deadline.
        rpc_millis = max(1, min(750, int(remaining * 1000)))
        result = run_bounded([str(cli), "--config", str(config), "--output", "json",
            "--rpc-timeout-ms", str(rpc_millis), "capability", "list", "--deployment", deployment,
            "--include-node-usage"], cwd=config.parent, env=dict(os.environ),
            timeout_seconds=min(1, remaining), max_output_bytes=MAX_OUTPUT_BYTES)
        require(time.monotonic() < deadline, "audit-drain-deadline")
        current = counters(result.stdout)
        finished = time.monotonic()
        require(finished < deadline, "audit-drain-deadline")
        if not any(current.values()):
            return {"schemaVersion": "latent.capsule.audit-drain.v1", "status": "idle",
                "observations": observation, "elapsedMillis": int((finished - started) * 1000),
                "limits": {"seconds": timeout_seconds, "observations": MAX_OBSERVATIONS,
                           "outputBytesPerRead": MAX_OUTPUT_BYTES, "processSecondsPerRead": 1,
                           "additionalCleanupSeconds": 5}, "counters": current}
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    raise AuditDrainError("audit-drain-observation-limit")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--deployment", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(wait(args.cli, args.config, args.deployment), sort_keys=True))
        return 0
    except (AuditDrainError, BuildProcessError, OSError) as error:
        reason = str(error) if isinstance(error, (AuditDrainError, BuildProcessError)) else "audit-drain-input-unavailable"
        print("Audit drain failed: " + reason, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

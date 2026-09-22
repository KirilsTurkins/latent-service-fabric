#!/usr/bin/env python3
"""Run bounded co-located CI integration lanes from prepared workspace inputs.

The Rust job remains the single producer of the Cargo inventory and host
artifacts. This coordinator consumes #427's reviewed suite inventory, dispatches
only same-checkout workers, and relies on #434's owned-process supervisor for
cancellation/descendant retirement. It never relocates a native target tree or
rebuilds the workspace.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import ci_suite_inventory as registry
from tools.ci_lanes import Completion, LaneError, Phase, Scheduler, Stage, State
from tools.owned_test_process import ProcessFailure, run_owned_async

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "latent.ci-lanes.v1"
CHILD_SCHEMA = "latent.ci-lane-run.v1"
MAX_RECEIPT_BYTES = 256 * 1024

PROVIDER_STEPS = (
    "s3-blobs",
    "s3-invalid-prepared-harness",
    "vault-secrets",
    "nats-events",
    "nats-triggers",
    "capability-policy-cli",
)
RENDERER_STEPS = (
    "angular-ssr-hydration",
    "browser-boundary",
    "angular-renderer",
    "renderer-failure-control",
    "angular-build-contracts",
    "angular-package",
    "angular-package-runtime",
)
PROVIDER_SELECTIONS = ("s3-blobs", "vault-secrets", "nats-events", "nats-triggers")
RENDERER_SUITES = ("latent-wasmtime.test.angular-renderer", "latent-wasmtime.test.angular-build")


def require(condition: object, reason: str) -> None:
    if not condition:
        raise LaneError(reason)


def _source_revision() -> str | None:
    value = os.environ.get("GITHUB_SHA")
    return value if value and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value) else None


def _expected_cases(data: dict, lane: str) -> tuple[str, ...]:
    suites = {row["id"]: row for row in data["suites"]}
    if lane == "provider":
        values = []
        for key in PROVIDER_SELECTIONS:
            selected = data["selections"].get(key)
            require(isinstance(selected, dict) and selected.get("runner") == "provider-owner",
                    "provider-selection-contract")
            values.extend(selected["names"])
        return tuple(values)
    require(lane == "renderer", "unknown-lane")
    browser = data["selections"].get("browser-boundary")
    require(isinstance(browser, dict) and browser.get("runner") == "ci_rust_artifacts",
            "browser-selection-contract")
    values = list(browser["names"])
    process = data.get("processContracts", {}).get("angular-renderer")
    require(isinstance(process, dict) and process.get("suiteIds"), "renderer-process-contract")
    for key in process["suiteIds"]:
        row = suites.get(key)
        require(isinstance(row, dict) and row.get("recipe") == "workspace-all-features",
                "renderer-suite-contract")
        selected = row["expectedIgnored"]
        if row["target"] == "latentd":
            selected = [name for name in selected if "actual_angular_http_" in name]
        values.extend(selected)
    for key in ("latent-packaging.test.angular-build", "latent-wasmtime.test.angular-build"):
        build = suites.get(key)
        require(isinstance(build, dict) and build.get("expectedIgnored"), "angular-build-suite-contract")
        values.extend(build["expectedIgnored"])
    policy = suites.get("latent-policy.lib.latent-policy")
    require(isinstance(policy, dict), "angular-policy-suite-contract")
    policy_cases = [name for name in policy["expectedIgnored"]
                    if "supply_chain::tests::web::angular_build::" in name]
    require(len(policy_cases) == 1, "angular-policy-case-contract")
    values.extend(policy_cases)
    return tuple(values)


def stages(renderer: bool) -> tuple[Stage, ...]:
    result = [
        Stage("provider-integrations", Phase.EXECUTION, "provider", 1500,
              cases=PROVIDER_STEPS, receipts=("provider-lane-receipt",)),
    ]
    if renderer:
        result.append(
            Stage("renderer-integrations", Phase.EXECUTION, "renderer", 3900,
                  cases=RENDERER_STEPS, receipts=("renderer-lane-receipt",))
        )
    return tuple(result)


def _read_receipt(path: Path, lease, data: dict) -> dict:
    require(path.is_file() and not path.is_symlink(), "missing-lane-receipt")
    raw = path.read_bytes()
    require(0 < len(raw) <= MAX_RECEIPT_BYTES, "lane-receipt-limit")
    value = json.loads(raw)
    require(isinstance(value, dict) and value.get("schemaVersion") == CHILD_SCHEMA,
            "lane-receipt-schema")
    lane = "provider" if lease.stage.name == "provider-integrations" else "renderer"
    require(value.get("lane") == lane and value.get("outcome") == "passed",
            "lane-receipt-outcome")
    require(value.get("steps") == list(lease.stage.cases), "lane-step-parity")
    expected = _expected_cases(data, lane)
    observed = value.get("selectedCases")
    require(isinstance(observed, list) and len(observed) == len(set(observed))
            and set(observed) == set(expected), "lane-selected-case-parity")
    timings = value.get("timings")
    require(isinstance(timings, list) and timings, "lane-timing-record-missing")
    for item in timings:
        require(isinstance(item, dict) and isinstance(item.get("stage"), str)
                and isinstance(item.get("elapsedMs"), (int, float))
                and item["elapsedMs"] >= 0, "lane-timing-record-invalid")
    return value


async def _execute(lease, inventory: Path, output: Path, data: dict) -> tuple[Completion, dict | None, str]:
    lane = "provider" if lease.stage.name == "provider-integrations" else "renderer"
    receipt = output / f"{lane}.json"
    command = [
        sys.executable, str(ROOT / "tools/ci_lane_worker.py"),
        "--lane", lane,
        "--inventory", str(inventory),
        "--output", str(receipt),
    ]
    try:
        result = await run_owned_async(
            command, cwd=ROOT, env=dict(os.environ),
            timeout=lease.stage.watchdog_seconds, maximum=8 * 1024 * 1024,
        )
    except ProcessFailure as error:
        outcome = State.CANCELLED if error.category == "cancelled" else State.FAILURE
        return Completion(lease.stage.name, outcome), None, f"{error.category}:{error.reason}"
    if result.returncode != 0:
        return Completion(lease.stage.name, State.FAILURE), None, f"worker-exit:{result.returncode}"
    try:
        value = _read_receipt(receipt, lease, data)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, LaneError) as error:
        return Completion(lease.stage.name, State.FAILURE), None, f"receipt:{error}"
    return (Completion(lease.stage.name, State.SUCCESS, lease.stage.cases, lease.stage.receipts),
            value, "reported-success")


async def run(args: argparse.Namespace) -> int:
    inventory = args.inventory.resolve(strict=True)
    data = registry.load()
    require(inventory.is_file() and not inventory.is_symlink(), "invalid-workspace-inventory")
    _expected_cases(data, "provider")
    if args.renderer:
        _expected_cases(data, "renderer")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    scheduler = Scheduler(
        stages(args.renderer), workers=args.workers,
        capacities={"provider": 1, "renderer": 1},
    )
    started = time.monotonic()
    children: dict[str, dict] = {}
    failures: dict[str, str] = {}
    running: dict[str, tuple[object, asyncio.Task]] = {}
    interrupted = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, interrupted.set)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        while not scheduler.finished:
            if interrupted.is_set():
                scheduler.cancel()
                for _name, (_lease, task) in running.items():
                    task.cancel()
            for lease in scheduler.claim_ready():
                running[lease.stage.name] = (
                    lease, asyncio.create_task(_execute(lease, inventory, output, data))
                )
            require(running or scheduler.finished, "lane-scheduler-stalled")
            if scheduler.finished:
                break
            done, _ = await asyncio.wait(
                [task for _, task in running.values()],
                timeout=0.25,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                continue
            for name, (lease, task) in list(running.items()):
                if task not in done:
                    continue
                try:
                    completion, child, reason = await task
                except asyncio.CancelledError:
                    completion, child, reason = Completion(name, State.CANCELLED), None, "coordinator-cancelled"
                scheduler.complete(lease, completion)
                # run_owned_async does not finish until its process owner has
                # acknowledged descendant cleanup; only then release capacity.
                scheduler.retire(lease)
                if child is not None:
                    children[name] = child
                if completion.outcome != State.SUCCESS:
                    failures[name] = reason
                del running[name]
    finally:
        for sig in installed:
            loop.remove_signal_handler(sig)

    raw_inventory = inventory.read_bytes()
    receipt = {
        "schemaVersion": SCHEMA,
        "sourceRevision": _source_revision(),
        "inventorySha256": "sha256:" + hashlib.sha256(raw_inventory).hexdigest(),
        "workers": args.workers,
        "rendererSelected": args.renderer,
        "elapsedMs": round((time.monotonic() - started) * 1000, 3),
        "states": {name: state.value for name, state in scheduler.states.items()},
        "reasons": dict(scheduler.reasons),
        "failures": failures,
        "children": children,
        "outcome": "passed" if scheduler.passed else "failed",
    }
    encoded = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(len(encoded) <= MAX_RECEIPT_BYTES, "aggregate-receipt-limit")
    temporary = output / ".receipt.json.tmp"
    temporary.write_bytes(encoded)
    temporary.chmod(0o600)
    temporary.replace(output / "receipt.json")
    print(json.dumps({
        "schemaVersion": SCHEMA,
        "outcome": receipt["outcome"],
        "workers": args.workers,
        "rendererSelected": args.renderer,
        "elapsedMs": receipt["elapsedMs"],
    }, sort_keys=True))
    return 0 if scheduler.passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--renderer", choices=("true", "false"), required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    args.renderer = args.renderer == "true"
    try:
        return asyncio.run(run(args))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, LaneError) as error:
        print(f"CI lane execution failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

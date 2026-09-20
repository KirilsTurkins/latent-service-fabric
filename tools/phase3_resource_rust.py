#!/usr/bin/env python3
"""Execute the exact Cargo-reported resource test artifact with finite ownership."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.ci_rust_artifacts import Artifact, Suite, cargo_environment, unique_object, validate_listing
from tools.phase2_operator_process import Process, WorkflowError, read_json, require
from tools.phase3_resource_campaign import write_receipt
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_profile import integer

ROOT = Path(__file__).resolve().parents[1]
NAME = "phase3_resource_small_provider_ownership_checkpoint"
SUITE = Suite("crates/latent-wasmtime/Cargo.toml", "phase3_resource", "tests/phase3_resource.rs",
              NAME, frozenset({NAME}), True)


def artifact_from_cargo(output, root, target=None, suite=SUITE):
    require(len(output) <= 2 * 1024 * 1024, "resource-rust-inventory-bytes")
    target_root = (target or root / "target").resolve(strict=True)
    require(target_root.is_relative_to((root / "target").resolve(strict=True)), "resource-rust-target-owner")
    expected_manifest = (root / suite.manifest).resolve(strict=True)
    expected_source = (expected_manifest.parent / suite.source).resolve(strict=True)
    found, finished, links = None, False, set()
    for ordinal, line in enumerate(output.splitlines()):
        require(ordinal < 20000 and len(line) <= 1048576 and not finished, "resource-rust-inventory-bound")
        message = json.loads(line, object_pairs_hook=unique_object)
        require(isinstance(message, dict), "resource-rust-inventory-record")
        if message.get("reason") == "build-finished":
            require(message.get("success") is True, "resource-rust-build-failed")
            finished = True
        elif message.get("reason") == "build-script-executed":
            paths = message.get("linked_paths", [])
            require(isinstance(paths, list) and len(paths) <= 256, "resource-rust-link-bound")
            for path in paths:
                require(isinstance(path, str) and len(path) <= 4096, "resource-rust-link-path")
                candidate = Path(path.split("=", 1)[-1])
                if candidate.is_absolute() and candidate.resolve().is_relative_to(target_root):
                    links.add(candidate.resolve())
                    require(len(links) <= 256, "resource-rust-link-bound")
        elif message.get("reason") == "compiler-artifact" and message.get("target", {}).get("name") == suite.target:
            require(found is None and Path(message["manifest_path"]).resolve() == expected_manifest,
                    "resource-rust-artifact-owner")
            target, profile = message["target"], message["profile"]
            require(target["kind"] == ["test"] and profile["test"] is True
                    and Path(target["src_path"]).resolve() == expected_source, "resource-rust-artifact-target")
            executable = Path(message["executable"])
            require(executable.is_absolute() and executable.is_file() and not executable.is_symlink()
                    and executable.resolve().is_relative_to(target_root / "debug/deps"),
                    "resource-rust-executable-owner")
            found = (executable.resolve(), profile)
    require(finished and found is not None, "resource-rust-missing-artifact")
    executable, profile = found
    return Artifact(executable, expected_manifest.parent, tuple(sorted(links))), profile


def validate_observations(value, binary):
    require(value["schemaVersion"] == "latent.phase3.resource-regression.v1"
            and value["status"] == "checkpoint-passed" and value["ticketAcceptance"] == "pending",
            "resource-rust-report-scope")
    require(value["binarySha256"] == binary["sha256"], "resource-rust-report-binary")
    rows = value["observations"]
    require(0 < len(rows) <= 128, "resource-rust-empty-report")
    for provider in ("http", "blob", "secret", "event", "child"):
        selected = [row for row in rows if row["provider"] == provider]
        require({"fixed", "active", "recovery"} <= {row["phase"] for row in selected},
                "resource-rust-missing-population")
        active = [row for row in selected if row["phase"] == "active"]
        require(any(integer(row["broker"]["sessions"]) > 0 for row in active),
                "resource-rust-no-live-provider")
        require(any(integer(row["runtime"]["stores_created"]) > 0 for row in selected),
                "resource-rust-no-guest-execution")
        for row in selected:
            require(integer(row["os"]["rssBytes"]) > 0 and integer(row["os"]["threads"]) > 0,
                    "resource-rust-empty-os")
            require(row["rendererHeapBytes"] is None and row["allocatorRetainedBytes"] is None,
                    "resource-rust-unobserved-heap")
            if row["phase"] == "recovery":
                require(all(integer(row["broker"][key]) == 0 for key in
                            ("sessions", "handles", "calls", "results", "buffer_bytes")),
                        "resource-rust-retained-active-broker")
                require(all(integer(row["runtime"][key]) == 0 for key in
                            ("live_stores", "live_host_states", "live_component_instances")),
                        "resource-rust-retained-active-runtime")
    return True


def execute(command, directory, environment, cancellation, timeout, maximum, commands):
    record = {"command": command, "deadlineSeconds": timeout, "maximumOutputBytes": maximum,
              "startedUnixNanos": str(time.time_ns()), "reaped": False}
    commands.append(record)
    process = Process(command, directory, environment, cancellation, maximum=maximum)
    try:
        completed = process.complete(time.monotonic() + timeout)
        record["exitCode"] = completed.returncode
        return completed
    finally:
        process.close()
        record.update(reaped=process.owner.finished, finishedUnixNanos=str(time.time_ns()),
                      stdout=bytes(process.buffers[0]).decode("utf-8", "replace"),
                      stderr=bytes(process.buffers[1]).decode("utf-8", "replace"))


def run(args):
    require(sys.platform == "linux" and re.fullmatch(r"[0-9a-f]{40}", args.revision),
            "resource-rust-linux-and-revision")
    require(all(path.is_absolute() and not path.exists() and path.parent.is_dir()
                for path in (args.output, args.report)) and args.output != args.report,
            "resource-rust-fresh-outputs")
    result = {"schemaVersion": "latent.phase3.resource-rust-run.v1", "status": "failed",
              "ticketAcceptance": "pending", "commands": [], "sourceRevision": args.revision,
              "revisionAssociation": "operator-asserted-with-explicit-input-digest",
              "host": {"kernel": platform.release(), "python": platform.python_version(),
                       "cpuQuota": Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
                       "memoryLimitBytes": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
                       "hostConditions": args.host_condition, "dedicatedHardware": False},
              "runnerIdentity": file_identity(Path(__file__))}
    try:
        source = source_identity(ROOT)
        result["sourceInputs"] = source
        environment = dict(os.environ)
        result["buildEnvironment"] = {key: environment.get(key) for key in
                                      ("CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "CARGO_PROFILE_TEST_DEBUG", "RUSTFLAGS")}
        with owned_cancellation() as cancellation:
            commands = result["commands"]
            compiler = execute(["rustc", "--version", "--verbose"], ROOT, environment,
                               cancellation, 10, 4096, commands)
            require(compiler.returncode == 0, "resource-rust-compiler-unavailable")
            built = execute(["cargo", "test", "--locked", "-p", "latent-wasmtime", "--test", "phase3_resource",
                             "--no-run", "--message-format=json", "-j", "3"], ROOT, environment,
                            cancellation, 900, 2 * 1024 * 1024, commands)
            require(built.returncode == 0, "resource-rust-build-failed")
            target = Path(environment.get("CARGO_TARGET_DIR", ROOT / "target"))
            artifact, profile = artifact_from_cargo(built.stdout, ROOT, target)
            result["cargoProfile"] = profile
            result["binary"] = file_identity(artifact.executable)
            require(source_identity(ROOT) == source, "resource-rust-source-changed")
            runtime_environment = cargo_environment(ROOT, artifact, environment)
            runtime_environment["LD_LIBRARY_PATH"] = os.pathsep.join(
                [str(artifact.executable.parent), str(target / "debug"), runtime_environment.get("LD_LIBRARY_PATH", "")])
            runtime_environment["LSF_PHASE3_RESOURCE_REPORT"] = str(args.report)
            command = [str(artifact.executable), NAME, "--exact"]
            listing = execute([*command, "--list"], artifact.package, runtime_environment,
                              cancellation, 10, 4096, commands)
            require(listing.returncode == 0, "resource-rust-list-failed")
            validate_listing(listing.stdout, SUITE)
            tested = execute([*command, "--nocapture", "--test-threads=1"], artifact.package, runtime_environment,
                             cancellation, 120, 262144, commands)
            require(tested.returncode == 0 and re.search(
                rb"^test result: ok\. 1 passed; 0 failed; 0 ignored;", tested.stdout, re.MULTILINE),
                "resource-rust-test-failed")
            require(file_identity(artifact.executable) == result["binary"] and source_identity(ROOT) == source,
                    "resource-rust-input-changed")
            observed = read_json(args.report, 2 * 1024 * 1024)
            validate_observations(observed, result["binary"])
            result["report"] = {**file_identity(args.report), "observations": len(observed["observations"])}
            result["status"] = "checkpoint-passed"
    except Exception as error:
        result["failure"] = (str(error) if isinstance(error, WorkflowError) else type(error).__name__)[:256]
    write_receipt(args.output, result)
    print(json.dumps({"status": result["status"], "ticketAcceptance": "pending",
                      "failure": result.get("failure"), "receipt": file_identity(args.output)}))
    return 0 if result["status"] == "checkpoint-passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--host-condition", action="append", default=[])
    args = parser.parse_args()
    require(len(args.host_condition) <= 8 and all(re.fullmatch(r"[a-z0-9-]{1,96}", value)
            for value in args.host_condition), "resource-rust-host-label-bound")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

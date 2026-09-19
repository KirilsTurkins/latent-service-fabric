#!/usr/bin/env python3
"""Run the manual matrix in one explicitly labelled disposable container, then stop it.

The container must already contain the locked build and browser prerequisites.
This owner never removes containers or volumes and never targets an unlabelled
container. Stopping its pinned ID also terminates detached browser processes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process import BuildProcessError, run_bounded
from tools.build_process_signals import owned_cancellation
from tools.phase3_security_artifacts import SecurityError, require, unique_object, validate_failure_locations

ROOT = Path(__file__).resolve().parents[1]
LABEL = "latent.phase3-security.owner"


def command(arguments: list[str], timeout: int = 30, maximum: int = 256 * 1024):
    names = ("PATH", "HOME", "USERPROFILE", "SystemRoot", "SYSTEMROOT", "WINDIR",
             "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")
    environment = {name: os.environ[name] for name in names if name in os.environ}
    return run_bounded(["docker", *arguments], ROOT, environment,
                       timeout_seconds=timeout, max_output_bytes=maximum)


def inspect(name: str) -> dict:
    rows = json.loads(command(["inspect", "--type", "container", name]).stdout)
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict), "container-inspect")
    return rows[0]


def owned_container(value: dict, owner: str) -> str:
    identifier = value.get("Id")
    require(isinstance(identifier, str) and re.fullmatch(r"[0-9a-f]{64}", identifier) is not None,
            "container-id")
    require(value.get("Config", {}).get("Labels", {}).get(LABEL) == owner, "container-not-owned")
    host = value.get("HostConfig", {})
    require(value.get("State", {}).get("Running") is True
            and host.get("Init") is True and host.get("AutoRemove") is False,
            "container-not-running-owned-init")
    require(0 < host.get("Memory", 0) <= 8 * 1024**3
            and 0 < host.get("NanoCpus", 0) <= 2_000_000_000
            and 0 < host.get("PidsLimit", 0) <= 512, "container-resource-bounds")
    require(not host.get("Privileged") and not host.get("CapAdd")
            and not host.get("PidMode") and not host.get("Devices")
            and host.get("NetworkMode") != "host", "container-host-authority")
    mounts = value.get("Mounts", [])
    require(not any(mount.get("Destination") == "/var/run/docker.sock" for mount in mounts),
            "container-engine-authority")
    workspaces = [mount for mount in mounts if mount.get("Destination") == "/workspace"]
    require(len(workspaces) == 1 and workspaces[0].get("Type") == "bind"
            and Path(workspaces[0]["Source"]).resolve() == ROOT.resolve(), "container-workspace-owner")
    return identifier


def run(args) -> dict:
    require(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,80}", args.owner) is not None, "container-owner-label")
    require(args.arguments and not any(value in ("--profile", "--container-owner", "--output")
                                      or value.startswith(("--profile=", "--container-owner=", "--output="))
                                      for value in args.arguments), "container-run-arguments")
    before = inspect(args.container)
    identifier = owned_container(before, args.owner)
    try:
        result = command(["exec", "--workdir", "/workspace", identifier, "python3",
                          "-c", "from tools.phase3_security import container_entry; container_entry()",
                          "--profile", "manual", "--container-owner", args.owner,
                          *args.arguments], timeout=2460, maximum=256 * 1024)
        report = json.loads(result.stdout, object_pairs_hook=unique_object)
        require(isinstance(report, dict) and report.get("profile") == "manual"
                and report.get("enclosingContainerStopRequired") is True
                and report.get("enclosingContainerOwner") == args.owner, "container-run-receipt")
        if report.get("schemaVersion") == "latent.phase3.security.failure.v1":
            require(report.get("passed") is False
                    and isinstance(report.get("failedStage"), str)
                    and re.fullmatch(r"[A-Za-z_0-9:-]{1,512}", report["failedStage"]) is not None
                    and isinstance(report.get("classification"), str)
                    and re.fullmatch(r"[a-z0-9-]{1,80}", report["classification"]) is not None,
                    "container-failure-receipt")
            validate_failure_locations(report.get("failureLocations", []))
        else:
            require(report.get("schemaVersion") == "latent.phase3.security.v1"
                    and report.get("passed") is True, "container-run-receipt")
    finally:
        with owned_cancellation() as cancellation, cancellation.defer():
            command(["stop", "--timeout", "5", identifier])
            after = inspect(identifier)
            require(after.get("Id") == identifier and after.get("State", {}).get("Running") is False
                    and after.get("Config", {}).get("Labels", {}).get(LABEL) == args.owner,
                    "container-stop-unverified")
    report["enclosingContainerStopRequired"] = False
    report["enclosingContainer"] = {"id": identifier, "image": before["Image"], "stopped": True,
                                     "volumesPreserved": True, "memoryBytes": before["HostConfig"]["Memory"],
                                     "nanoCpus": before["HostConfig"]["NanoCpus"],
                                     "pidsLimit": before["HostConfig"]["PidsLimit"]}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.arguments[:1] == ["--"]:
        args.arguments.pop(0)
    try:
        with owned_cancellation():
            report = run(args)
            encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
            require(len(encoded) <= 128 * 1024, "container-receipt-limit")
            if args.output is not None:
                destination = args.output.absolute()
                require(destination.parent.resolve(strict=True).is_relative_to((ROOT / "target").resolve()),
                        "receipt-outside-owned-target")
                with destination.open("xb") as output:
                    output.write(encoded + b"\n")
            print(encoded.decode())
            if report.get("passed") is False:
                print("Phase 3 security failed: " + report["failedStage"] + ": "
                      + report["classification"], file=sys.stderr)
                return 1
        return 0
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, (SecurityError, BuildProcessError)) else "container-or-fixture-error"
        print("Phase 3 security container failed: " + reason, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

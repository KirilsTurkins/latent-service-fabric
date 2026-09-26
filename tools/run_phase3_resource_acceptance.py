#!/usr/bin/env python3
"""Manual bounded matrix: fresh signed fixtures, exact Cargo artifacts, immutable failures."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.ci_rust_artifacts import SUITES, Suite, cargo_environment, validate_listing
from tools.phase2_operator_process import WorkflowError, read_json, require
from tools.phase3_resource_campaign import ROOT, build, run, write_receipt
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_profile import PROFILES
from tools.phase3_resource_rust import artifact_from_cargo, execute

PROVIDER = Suite("apps/latentd/Cargo.toml", "phase3_workflow_fixture", "tests/phase3_workflow_fixture.rs",
                 "export_signed_provider_workflow_fixtures", frozenset({"export_signed_provider_workflow_fixtures"}),
                 True, "test")


def export(artifact, suite, environment, cancellation, output):
    result = {"schemaVersion": "latent.phase3.resource-fixture-export.v1", "status": "failed", "commands": [],
              "binary": file_identity(artifact.executable), "test": suite.filter}
    try:
        command = [str(artifact.executable), suite.filter, "--exact", "--ignored"]
        listing = execute([*command, "--list"], artifact.package, environment, cancellation, 10, 4096, result["commands"])
        require(listing.returncode == 0, "resource-fixture-list-failed")
        validate_listing(listing.stdout, suite)
        observed = execute([*command, "--nocapture", "--test-threads=1"], artifact.package, environment,
                           cancellation, 120, 262144, result["commands"])
        require(observed.returncode == 0 and re.search(
            rb"^test result: ok\. 1 passed; 0 failed; 0 ignored;", observed.stdout, re.MULTILINE),
            "resource-fixture-export-failed")
        require(file_identity(artifact.executable) == result["binary"], "resource-fixture-binary-changed")
        result["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        result["failure"] = (str(error) if isinstance(error, WorkflowError) else type(error).__name__)[:256]
    write_receipt(output, result)
    require(result["status"] == "passed", result.get("failure", "resource-fixture-failed"))


def matrix(args):
    require(sys.platform == "linux" and re.fullmatch(r"[0-9a-f]{40}", args.revision), "resource-matrix-platform-revision")
    require(args.output.is_absolute() and args.output.parent.is_dir() and not args.output.exists(), "resource-matrix-fresh-output")
    args.output.mkdir(mode=0o700)
    profiles = args.profile or list(PROFILES)
    require(len(profiles) <= len(PROFILES) and len(set(profiles)) == len(profiles), "resource-matrix-duplicates")
    suites = {PROFILES[name]["kind"]: PROVIDER if PROFILES[name]["kind"] == "provider"
              else SUITES["angular-t1-fixture"] for name in profiles}
    environment = dict(os.environ)
    target = Path(environment.get("CARGO_TARGET_DIR", ROOT / "target"))
    result = {"schemaVersion": "latent.phase3.resource-matrix.v1", "status": "failed",
              "sourceRevision": args.revision, "sourceInputs": source_identity(ROOT), "profiles": profiles,
              "preparationCommands": [], "runs": [], "runner": file_identity(Path(__file__)),
              "ticketAcceptance": "pending", "automaticMutationRetries": 0}
    try:
        artifacts = {}
        with owned_cancellation() as cancellation:
            command = ["cargo", "test", "--locked", "-p", "latentd", "--no-run", "--message-format=json", "-j", "3"]
            for suite in suites.values():
                command.extend(["--test", suite.target])
            compiled = execute(command, ROOT, environment, cancellation, 900, 2 * 1024 * 1024, result["preparationCommands"])
            require(compiled.returncode == 0, "resource-matrix-fixture-build")
            for kind, suite in suites.items():
                artifacts[kind], _profile = artifact_from_cargo(compiled.stdout, ROOT, target, suite)
        identity = args.output / "build.json"
        require(build(SimpleNamespace(record_build=identity, revision=args.revision)), "resource-matrix-native-build")
        for name in profiles:
            kind = PROFILES[name]["kind"]
            fixture = args.output / (name + "-fixtures")
            artifact, suite = artifacts[kind], suites[kind]
            exported_environment = cargo_environment(ROOT, artifact, environment)
            exported_environment["LD_LIBRARY_PATH"] = os.pathsep.join([
                str(artifact.executable.parent), str(target / "debug"), exported_environment.get("LD_LIBRARY_PATH", "")])
            if kind == "provider":
                require(args.guest_capsules is not None and args.guest_capsules.is_dir(), "resource-matrix-real-guests-required")
                exported_environment.update(LSF_GUEST_CAPSULES=str(args.guest_capsules),
                                            LSF_PHASE3_WORKFLOW_FIXTURE_ROOT=str(fixture))
            else:
                require(args.angular_build is not None and args.angular_build.is_dir()
                        and args.compiler is not None and args.compiler.is_file(), "resource-matrix-real-angular-required")
                exported_environment.update(LSF_ANGULAR_BUILD_DIR=str(args.angular_build),
                                            LSF_ANGULAR_T1_FIXTURE_ROOT=str(fixture))
            print("Resource matrix: " + name, file=sys.stderr, flush=True)
            with owned_cancellation() as cancellation:
                export(artifact, suite, exported_environment, cancellation, args.output / (name + "-export.json"))
            output = args.output / (name + ".json")
            code = run(SimpleNamespace(profile=name, node=target / "debug/latentd", cli=target / "debug/latent",
                fixture_root=fixture, build_identity=identity, output=output, compiler=args.compiler,
                host_condition=args.host_condition))
            measured = read_json(output, 8 * 1024 * 1024)
            result["runs"].append({"profile": name, "receipt": file_identity(output), "exitCode": code,
                                    "status": measured["status"], "failure": measured.get("failure")})
            require(code == 0, "resource-matrix-profile-failed-no-retry")
        require(source_identity(ROOT) == result["sourceInputs"], "resource-matrix-source-changed")
        result["status"] = "bounded-profiles-passed"
    except (Exception, KeyboardInterrupt) as error:
        result["failure"] = (str(error) if isinstance(error, WorkflowError) else type(error).__name__)[:256]
        result["unexecutedProfiles"] = [name for name in profiles if name not in {row["profile"] for row in result["runs"]}]
    write_receipt(args.output / "matrix.json", result)
    return 0 if result["status"] == "bounded-profiles-passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(PROFILES), action="append")
    parser.add_argument("--guest-capsules", type=Path)
    parser.add_argument("--angular-build", type=Path)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--host-condition", action="append", default=[])
    args = parser.parse_args()
    require(len(args.host_condition) <= 8 and all(re.fullmatch(r"[a-z0-9-]{1,96}", value)
            for value in args.host_condition), "resource-host-label-bound")
    return matrix(args)


if __name__ == "__main__":
    raise SystemExit(main())

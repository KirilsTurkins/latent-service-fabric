#!/usr/bin/env python3
"""Exercise independently compiled, signed Rust capsules on an enforced node.

Linux with readable pressure metrics, Python 3.13; one node, one bounded HTTP
peer, at most 384 controls, 48 activations, 17 deployments. Native guests use a
180-second overall deadline; TypeScript's cold engine compilation allows 900.
Credentials are public test-only values confined to private temporary files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, read_json, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_cases import tutorials, faults, http_cases, population, stop_peer
from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy, sample
from tools.rust_capsule_project import fresh
from tools.sdk_provider_scenario import start_provider

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {"greeting", "word-count", "shipping", "http-status", "recovery"}


def run(cli, node_binary, fixture, evidence, *, language="rust"):
    require(language in {"rust", "c", "go", "typescript", "dotnet"}, "authoring-language")
    require(sys.platform == "linux" and sys.version_info >= (3, 13), "authoring-linux-python313")
    evidence = fresh(evidence)
    result = {"schemaVersion": f"latent.{language}-capsule.workflow.v1", "status": "in-progress", "language": language,
        "scope": "isolated-local-experimental-node-with-enforced-package-admission",
        "releasePublication": "not-performed", "newcomerReview345": "pending-human-review",
        "invocations": [], "samples": [], "providerIdle": [], "releases": {},
        "limitations": ["Non-atomic Linux /proc observations; RSS is not allocator retention.",
                        "Finite correctness experiment, not a production sizing or throughput claim."]}
    node = peer = client = None
    try:
        result["source"] = source_identity(ROOT)
        identities = {"cli": file_identity(cli), "node": file_identity(node_binary)}
        result["binaries"] = identities
        metadata = read_json(fixture / "release-set.json")
        require(metadata["schemaVersion"] == "latent.capsule.demo.v1" and metadata["tenant"] == "examples"
                and metadata["trust"] == "isolated-short-lived-demo-only"
                and metadata["expiresAtUnixSeconds"] > time.time() + 180, "authoring-demo-trust")
        records = {record["name"].removeprefix("my-"): record for record in metadata["releases"]}
        require(set(records) == TEMPLATES and len(metadata["releases"]) == len(TEMPLATES), "authoring-template-set")
        build_type = f"https://latent.dev/build/{'c-guest' if language == 'c' else language + '-capsule'}/v1"
        require(all(record["buildType"] == build_type for record in records.values()), "authoring-guest-language")
        result["releaseSet"] = metadata
        with owned_cancellation() as cancellation:
            with tempfile.TemporaryDirectory(prefix=f"lsf-{language}-authoring-node-") as temporary:
                work = Path(temporary)
                for name in ("client", "node", "peer"):
                    (work / name).mkdir(mode=0o700)
                seconds = 900 if language in {"typescript", "dotnet"} else 180
                invocation_millis = 120000 if language in {"typescript", "dotnet"} else 5000
                result["limits"] = {"overallSeconds": seconds, "invocationMillis": invocation_millis}
                client = RecordingClient(cli, work / "client", cancellation, time.monotonic() + seconds,
                                         evidence=evidence / "controls", invocation_timeout_millis=invocation_millis)
                peer, port = start_provider(client, work / "peer")
                config, settings = configure(work / "node", fixture, port, runtime_grants=language in {"go", "dotnet"}, language=language)
                result["configuration"] = settings
                # The test token is not a secret, but configuration files still
                # stay private and no token is copied into the exported receipt.
                result["configuration"]["credentials"][0].pop("token")
                began = time.monotonic_ns()
                node = connect(client, node_binary, work / "node", config, "examples", 1)
                result["startupNanos"] = str(time.monotonic_ns() - began)
                result["startup"] = node.startup_record
                probe = Probe(node, identities["node"])
                result["samples"].append(sample(client, probe, "empty", 0))
                try:
                    denied = client.call("release", "publish-package", fixture / "my-greeting/package",
                        "--operation-id", "unsigned-denied", "--expected-generation", "0", codes=(4,))
                    require(denied["error"]["code"] == "permission-denied", "authoring-unsigned-admission")
                    result["unsignedDenied"] = denied
                    publications, targets = {}, {}
                    for template in sorted(TEMPLATES):
                        source = fixture / ("my-" + template)
                        published = client.call("release", "publish-package", source / "package",
                            "--evidence", source / "evidence/index.json", "--operation-id", "publish-" + template,
                            "--expected-generation", "0")
                        require(published["outcomeKnown"] and published["data"]["release"]["digest"] == records[template]["componentDigest"],
                                "authoring-publication-identity")
                        publication = published["data"]["operation"]["publication"]["id"]
                        publications[template] = publication
                        result["releases"][template] = published["data"]["operation"]
                        targets[template] = deploy(client, source / "deployment.json", publication)
                    names = population(client, fixture, targets, publications, probe, result)
                    if language in {"go", "dotnet"}:
                        from tools.guest_runtime_grants import grant
                        grant(client, node, fixture, targets, publications, result, language=language)
                    tutorials(client, targets, result)
                    result["samples"].append(sample(client, probe, "after-tutorials", len(names)))
                    faults(client, targets["recovery"], probe, result, len(names))
                    http_cases(client, node, fixture, targets["http-status"], publications["http-status"],
                               port, work / "peer", probe, result, len(names))
                    delete_all(client, names)
                    result["samples"].append(sample(client, probe, "after-delete", 0))
                    stop(client, node)
                    result["nodeShutdown"] = stopped_record(node)
                    result["peerShutdown"] = stop_peer(peer)
                finally:
                    client.node = None
                    node.close()
                    peer.close()
                result["cliCalls"] = client.calls
            cancellation.check()
        require(result["source"] == source_identity(ROOT) and identities == {"cli": file_identity(cli), "node": file_identity(node_binary)},
                "authoring-inputs-changed")
        result["status"] = "passed"
        write_json(evidence / "workflow.json", result)
        return result
    except BaseException as error:
        result["status"] = "failed"
        result["reason"] = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        write_json(evidence / "FAILED.json", result)
        raise
    finally:
        if client:
            client.node = None
        for process in (node, peer):
            if process:
                process.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.cli.resolve(strict=True), args.node.resolve(strict=True), args.releases.resolve(strict=True), args.output)
    print(json.dumps({"status": result["status"], "invocations": len(result["invocations"]), "cliCalls": result["cliCalls"]}))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f"Rust authoring workflow failed: {error}", file=sys.stderr)
        raise SystemExit(1)

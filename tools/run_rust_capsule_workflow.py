#!/usr/bin/env python3
"""Exercise independently compiled, signed Rust capsules on an enforced node.

Linux with readable pressure metrics, Python 3.13; one node, one bounded HTTP
peer, at most 384 controls, 48 activations, 17 deployments. Native guests use a
180-second overall deadline; Go, Java and .NET allow 900 seconds, TypeScript 1200.
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
from tools.phase2_operator_process import require, read_json, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_cases import tutorials, faults, http_cases, population, stop_peer
from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy, sample
from tools.rust_capsule_project import fresh
from tools.sdk_provider_scenario import close_failed_provider, start_provider

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {"greeting", "word-count", "shipping", "http-status", "recovery"}


def write_workflow_receipt(path, value):
    # Complete authoring reports contain several bounded node inventories.
    # Keep their new catalog-capacity rows without enlarging fixture inputs.
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    require(len(encoded) <= 1024 * 1024, "authoring-workflow-receipt-bound")
    with path.open("xb") as target:
        target.write(encoded)
    path.chmod(0o600)


def run(cli, node_binary, fixture, evidence, *, language="rust", noncrypto_entropy=False,
        c_standard_facilities=False, c_standard_logging=False, captured_dependency_recovery=False,
        captured_git_component=False, c_standard_combined=False, c_compiled_resources=False, rust_compatibility=False,
        captured_rust_matrix=False, go_standard_logging=False, rust_standard_stdio=False):
    require(language in {"rust", "c", "go", "typescript", "dotnet", "java"}, "authoring-language")
    require(type(noncrypto_entropy) is bool and (not noncrypto_entropy or language == "dotnet"),
            "authoring-noncrypto-entropy-language")
    require(type(c_standard_facilities) is bool and (not c_standard_facilities or language == "c"),
            "authoring-c-standard-facilities-language")
    require(type(c_standard_logging) is bool and (not c_standard_logging or language == "c")
            and not (c_standard_facilities and c_standard_logging), "authoring-c-standard-logging-language")
    require(type(c_standard_combined) is bool and (not c_standard_combined or language == "c")
            and not (c_standard_combined and (c_standard_facilities or c_standard_logging)),
            "authoring-c-standard-combined-language")
    require(type(c_compiled_resources) is bool and (not c_compiled_resources or language == 'c')
            and not (c_compiled_resources and (c_standard_facilities or c_standard_logging or c_standard_combined)),
            'authoring-c-compiled-resources-language')
    require(type(captured_dependency_recovery) is bool
            and (not captured_dependency_recovery or language in {"rust", "dotnet", "go"}),
            "authoring-captured-dependency-recovery-language")
    require(type(captured_git_component) is bool and (not captured_git_component or language == "rust"),
            "authoring-captured-Git-component-language")
    require(type(rust_compatibility) is bool and (not rust_compatibility or language == "rust"),
            "authoring-Rust-compatibility-language")
    require(type(captured_rust_matrix) is bool and (not captured_rust_matrix or language == "rust")
            and not (captured_rust_matrix and (rust_compatibility or captured_git_component or captured_dependency_recovery)),
            "authoring-Rust-matrix-language")
    require(type(go_standard_logging) is bool and (not go_standard_logging or language == 'go'),
            'authoring-Go-standard-logging-language')
    require(type(rust_standard_stdio) is bool and (not rust_standard_stdio or language == 'rust')
            and not (rust_standard_stdio and (captured_rust_matrix or rust_compatibility or captured_git_component
                                             or captured_dependency_recovery)), 'authoring-Rust-stdio-language')
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
                seconds = 1200 if language == "typescript" else 900 if language in {"go", "dotnet", "java"} else 180
                invocation_millis = 120000 if language in {"go", "typescript", "dotnet", "java"} else 5000
                control_millis = 125000 if language == "typescript" else 15000
                result["limits"] = {"overallSeconds": seconds, "invocationMillis": invocation_millis,
                                    "controlMillis": control_millis,
                                    "controlProcessSeconds": 130 if language == "typescript" else 25,
                                    "peerSeconds": seconds}
                client = RecordingClient(cli, work / "client", cancellation, time.monotonic() + seconds,
                                         evidence=evidence / "controls", invocation_timeout_millis=invocation_millis,
                                         control_timeout_millis=control_millis)
                peer, port = start_provider(client, work / "peer", maximum_seconds=seconds)
                config, settings = configure(work / "node", fixture, port,
                    runtime_grants=language in {"go", "dotnet", "java"} or c_standard_facilities or c_standard_combined, language=language,
                    noncrypto_entropy=noncrypto_entropy)
                if c_standard_logging or c_standard_combined:
                    from tools.c_standard_logging_probe import configure as configure_logging
                    configure_logging(settings)
                    config.write_bytes(json.dumps(settings, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n')
                if go_standard_logging:
                    from tools.go_standard_logging_probe import configure as configure_go_logging
                    configure_go_logging(settings)
                    config.write_bytes(json.dumps(settings, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n')
                if rust_standard_stdio:
                    from tools.rust_standard_logging_probe import configure as configure_rust_stdio
                    configure_rust_stdio(settings, fixture)
                    config.write_bytes(json.dumps(settings, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n')
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
                    if rust_standard_stdio:
                        from tools.rust_standard_logging_probe import grant as grant_rust_stdio
                        grant_rust_stdio(client, node, fixture, targets, publications, result)
                    if language in {"go", "dotnet", "java"}:
                        from tools.guest_runtime_grants import grant
                        grant(client, node, fixture, targets, publications, result, language=language)
                    if go_standard_logging:
                        from tools.go_standard_logging_probe import grant as grant_go_logging
                        grant_go_logging(client, node, fixture, targets, publications, result)
                    if c_standard_facilities:
                        from tools.c_standard_facilities_probe import grant_and_probe
                        grant_and_probe(client, node, fixture, targets, publications, result)
                    if c_standard_logging:
                        from tools.c_standard_logging_probe import grant_and_probe
                        grant_and_probe(client, node, fixture, targets, publications, result)
                    if c_standard_combined:
                        from tools.c_standard_combined_probe import grant_and_probe
                        grant_and_probe(client, node, fixture, targets, publications, result)
                    if c_compiled_resources:
                        from tools.c_compiled_resource_fixture import probe as compiled_resource_probe
                        compiled_resource_probe(client, targets['greeting'], probe, result, len(names))
                    if noncrypto_entropy:
                        from tools.dotnet_guest.entropy_grants import grant as grant_entropy
                        targets["greeting"] = grant_entropy(client, node, fixture / "my-greeting/deployment.json",
                            publications["greeting"], targets["greeting"], result)
                    if go_standard_logging:
                        from tools.go_standard_logging_probe import tutorials as logging_tutorials
                        logging_tutorials(client, targets, result)
                    else:
                        tutorials(client, targets, result)
                    if go_standard_logging:
                        from tools.go_standard_logging_probe import probe as probe_go_logging
                        probe_go_logging(client, targets['greeting'], probe, result, len(names))
                    if rust_compatibility:
                        from tools.rust_compatibility_probe import probe as probe_compatibility
                        probe_compatibility(client, targets['greeting'], probe, result, len(names))
                    if captured_rust_matrix:
                        from tools.rust_dependency_matrix import probe as probe_matrix
                        probe_matrix(client, targets['greeting'], probe, result, len(names),
                                     read_json(fixture / 'matrix-probe.json'))
                    if captured_git_component:
                        from tools.rust_git_component_fixture import probe as probe_git_component
                        probe_git_component(client, targets['greeting'], probe, result, len(names))
                    if rust_standard_stdio:
                        from tools.rust_standard_logging_probe import probe as probe_rust_stdio
                        probe_rust_stdio(client, targets['greeting'], fixture, probe, result, len(names))
                    if captured_dependency_recovery:
                        if language == "dotnet":
                            from tools.dotnet_dependency_recovery import recover
                        elif language == "go":
                            from tools.go_dependency_recovery import recover
                        else:
                            from tools.rust_dependency_recovery import recover
                        result["capturedDependencyRecovery"] = recover(
                            client, targets["greeting"], probe, result, len(names))
                    result["samples"].append(sample(client, probe, "after-tutorials", len(names)))
                    faults(client, targets["recovery"], probe, result, len(names), language=language)
                    http_cases(client, node, fixture, targets["http-status"], publications["http-status"],
                               port, work / "peer", probe, result, len(names))
                    delete_all(client, names)
                    result["samples"].append(sample(client, probe, "after-delete", 0))
                    stop(client, node)
                    result["nodeShutdown"] = stopped_record(node)
                    result["peerShutdown"] = stop_peer(peer)
                finally:
                    client.node = None
                    try:
                        node.close()
                    finally:
                        if "peerShutdown" not in result:
                            result["peerFailure"] = close_failed_provider(peer)
                        else:
                            peer.close()
                result["cliCalls"] = client.calls
            cancellation.check()
        require(result["source"] == source_identity(ROOT) and identities == {"cli": file_identity(cli), "node": file_identity(node_binary)},
                "authoring-inputs-changed")
        result["status"] = "passed"
        write_workflow_receipt(evidence / "workflow.json", result)
        return result
    except BaseException as error:
        result["status"] = "failed"
        result["reason"] = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        if peer is not None and "peerShutdown" not in result and "peerFailure" not in result:
            result["peerFailure"] = close_failed_provider(peer)
        write_workflow_receipt(evidence / "FAILED.json", result)
        raise
    finally:
        if client:
            client.node = None
        for process in (node, peer):
            if process:
                process.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="rust", choices=("rust", "c", "go", "typescript", "dotnet", "java"))
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.cli.resolve(strict=True), args.node.resolve(strict=True), args.releases.resolve(strict=True), args.output,
                 language=args.language)
    print(json.dumps({"status": result["status"], "invocations": len(result["invocations"]), "cliCalls": result["cliCalls"]}))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f"Rust authoring workflow failed: {error}", file=sys.stderr)
        raise SystemExit(1)

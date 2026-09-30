"""Execute independently built, signed Java domain/HTTP adapter components."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from tools.build_process_signals import owned_cancellation
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.java_http_composition.build import compile_pair
from tools.java_http_composition import context
from tools.java_http_composition.node import (
    ADAPTER, DOMAIN_CONTRACT, SERVICE_CAPABILITY, WEB_CONTRACT, configure, decoded,
    grant, idle, invoke, request, route, service_grant, web_request,
)
from tools.phase2_operator_process import Process, read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID, connect, receipt, stop
from tools.phase2_operator_canary import rollback_target
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.rust_capsule_node import RecordingClient, delete_all, deploy
from tools.rust_capsule_project import ROOT, fresh
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.rust_capsule_build import Commands


def publish(client, releases):
    result = {}
    for name in ("domain", "adapter", "context-required"):
        source = releases / ("java-http-" + name)
        published = client.call("release", "publish-package", source / "package", "--evidence", source / "evidence/index.json",
            "--operation-id", "publish-" + name, "--expected-generation", 0)
        require(published["outcomeKnown"], "java-http-publication-unknown")
        result[name] = published["data"]["operation"]["publication"]["id"]
    require(result["domain"] != result["adapter"], "java-http-independent-publications")
    return result


def fresh_status(client, targets, host, activation):
    direct = invoke(client, targets, "domain", "status", [], activation)
    status, body, _headers = request(host)
    require(status == 200 and json.loads(body) == decoded(direct), "java-http-direct-composed-value-mismatch")
    return {"direct": direct, "httpStatus": status, "responseBytes": len(body)}


def readiness(client):
    end = min(client.deadline, time.monotonic() + 20)
    for _ in range(128):
        data = client.call("node", "get", NODE_ID)["data"]["inventory"]
        if sum(int(row["active"]) for row in data["cellCapacity"]) == 2:
            return data
        require(time.monotonic() < end, "java-http-child-never-entered-real-cell")
        time.sleep(.025)
    raise RuntimeError("java-http-child-readiness-observation-bound")


def cancellation(client, targets, host, result):
    input_path = client.directory / "cancel-input.json"
    budget_path = client.directory / "cancel-budget.json"
    write_json(input_path, web_request(host, "/api/spin"))
    write_json(budget_path, targets["adapter"]["budget"])
    argv = [client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator",
        "--rpc-timeout-ms", "120000", "invoke", "--service", ADAPTER, "--route", "java-http-adapter",
        "--contract", WEB_CONTRACT, "--function", "handle", "--activation-id", "java-composed-cancel",
        "--input", str(input_path), "--budget", str(budget_path), "--budget-profile", "phase3"]
    process = Process(argv, client.directory, client.environment, client.cancellation, maximum=65536)
    try:
        result["cancellationReady"] = readiness(client)
        cancelled = client.call("activation", "cancel", "java-composed-cancel", "--reason", "Synthetic composed cancellation")
        require(cancelled["outcomeKnown"] and cancelled["data"]["disposition"] == "accepted", "java-composed-cancel-uncertain")
        completed = process.complete(min(client.deadline, time.monotonic() + 15))
        response = json.loads(completed.stdout)
        require(completed.returncode == 4 and response["error"]["code"] == "cancelled", "java-composed-cancel-result")
        result["cancellation"] = response
    finally:
        process.close()
    result["afterCancellation"] = idle(client)
    result["cancellationTree"] = context.tree(client, "java-composed-cancel")
    cancelled_nodes = result["cancellationTree"]["nodes"]
    require(len(cancelled_nodes) == 2 and all(row["terminalState"] == "cancelled" for row in cancelled_nodes),
            "java-context-cancellation-did-not-terminate-parent-and-child")
    cancelled_parent = next(row for row in cancelled_nodes if row["activationId"] == "java-composed-cancel")
    cancelled_child = next(row for row in cancelled_nodes if row["parentActivationId"] == "java-composed-cancel")
    require(cancelled_parent["principalKind"] == "administrator" and cancelled_child["principalKind"] == "service"
        and cancelled_child["callerService"] == ADAPTER, "java-context-cancellation-child-authority")
    result["afterCancellationFresh"] = fresh_status(client, targets, host, "java-after-cancellation")


def canary(client, targets, publications, releases, host):
    base = client.call("deployment", "get", "java-http-adapter")["data"]["deployment"]
    candidate = read_json(releases / "java-http-adapter/deployment.json")
    candidate["metadata"]["name"] = "java-http-adapter-next"
    candidate["spec"].update(publication=publications["adapter"], grants=targets["adapter"]["grants"])
    candidate["spec"]["route"]["weight"] = 5000
    candidate["spec"]["resources"]["cpuFuel"] -= 1
    candidate_path = client.directory / "candidate.json"
    write_json(candidate_path, candidate)
    policy_path = client.directory / "canary-policy.json"
    write_json(policy_path, {"formatVersion": 1, "observationMillis": 5000, "minimumCandidateSamples": 1,
        "maximumFailureBasisPoints": 0, "latencyThresholdMicros": 120000000, "maximumSlowBasisPoints": 0})
    started = receipt(client.call("rollout", "start", "java-http-canary", "--base", "java-http-adapter",
        "--expected-base-generation", base["generation"], "--candidate", candidate_path, "--weights", "5000,10000",
        "--operation-id", "java-canary-start", "--expected-revision", 0, "--canary-policy", policy_path), "java-canary-start")
    historical = rollback_target(client, "java-http-canary", started)
    samples = []
    for ordinal in range(16):
        sample = invoke(client, targets, "adapter", "handle", web_request(host), f"java-canary-{ordinal:02d}", route_name=False)
        require(decoded(sample)[0]["status"] == 200, "java-canary-composed-failed")
        samples.append(sample["data"]["resolvedRevision"])
    end = min(client.deadline, time.monotonic() + 10)
    for _ in range(64):
        report = client.call("rollout", "evaluate", "java-http-canary", "--expected-revision", started["revision"])["data"]["report"]
        if not report["assessment"]["verdict"].endswith(("COLLECTING", "DRAINING")):
            break
        require(time.monotonic() < end, "java-canary-window-did-not-close")
        time.sleep(.1)
    require(report["assessment"]["verdict"].endswith("HEALTHY") and int(report["terminal"]) == 16
        and int(report["live"]) == 0 and len({row["revisionId"] for row in samples}) == 2,
        "java-canary-live-sample-attribution")
    promoted = receipt(client.call("rollout", "promote", "java-http-canary", "--expected-revision", started["revision"],
        "--operation-id", "java-canary-promote", "--next-step", 1), "java-canary-promote")
    # The original exact trigger must not silently float to a new deployment.
    stale_status = request(host)[0]
    require(stale_status in (409, 503), "java-http-stale-trigger-silently-followed-rollout")
    rolled = receipt(client.call("rollout", "rollback", "java-http-canary", "--expected-revision", promoted["revision"],
        "--operation-id", "java-canary-rollback", "--target-generation", historical), "java-canary-rollback")
    route(client, host, publications["adapter"])
    require(request(host)[0] == 200, "java-http-rollback-fresh-route")
    return {"started": started, "samples": samples, "evaluation": report, "promoted": promoted,
            "staleTriggerStatus": stale_status, "rolledBack": rolled, "idle": idle(client)}


def run_node(binaries, releases, output, *, http, former_profile=False):
    evidence = fresh(output)
    result = {"schemaVersion": "latent.java-http.node.v1", "status": "in-progress", "httpEnabled": http,
              "formerProfileReproduction": former_profile}
    with owned_cancellation() as cancellation_owner:
        with tempfile.TemporaryDirectory(prefix="lsf-java-http-node-") as temporary:
            work = Path(temporary)
            (work / "node").mkdir(mode=0o700)
            (work / "client").mkdir(mode=0o700)
            client = RecordingClient(binaries["latent"], work / "client", cancellation_owner, time.monotonic() + 900,
                evidence=evidence / "controls", invocation_timeout_millis=120000)
            config, host = configure(work / "node", releases, http=http, former_profile=former_profile)
            # This disposable config contains only the public workflow token.
            # Preserve the exact finite bounds when startup fails before RPC.
            write_json(evidence / "node-config.json", read_json(config))
            node = None
            try:
                node = connect(client, binaries["latentd"], work / "node", config, "examples", 1)
                result["startup"] = node.startup_record
                publications = publish(client, releases)
                result["publications"] = publications
                targets = grant(client, node, releases, publications)
                if former_profile:
                    activation = "java-former-http-profile"
                    failure = invoke(client, targets, "domain", "status", [], activation, codes=(4,))
                    require(failure["error"]["code"] == "resource-exhausted", "java-former-profile-failure-category")
                    tree = client.call("activation", "tree", activation, "--page-size", 4)["data"]
                    require(tree["historyAvailable"] and len(tree["nodes"]) == 1 and not tree["nextPageToken"],
                            "java-former-profile-retained-diagnosis")
                    node_record = tree["nodes"][0]
                    diagnostic = node_record["diagnostic"]
                    require(node_record["diagnosticIsTerminal"] and diagnostic["stage"] == 3
                        and diagnostic["reason"] == 1 and diagnostic["profileDigest"],
                        "java-former-profile-producer-owned-signature-diagnosis")
                    bound, required, fixed, fuel, multiplier = (int(diagnostic[name]) for name in (
                        "configuredBound", "calculatedRequirement", "fixedBytes", "liftingFuel", "liftMultiplier"))
                    require(bound == 64 * 1024 * 1024 and fuel == 2 * 1024 * 1024
                        and required == fixed + fuel * multiplier and required > bound,
                        "java-former-profile-calculated-allocation-proof")
                    require("activation.diagnostic.v1" not in json.dumps(failure),
                        "java-former-profile-diagnosis-exposed-in-public-invoke")
                    result["formerProfileFailure"] = failure
                    result["formerProfileAuthorizedTree"] = tree
                else:
                    result["standaloneStatus"] = invoke(client, targets, "domain", "status", [], "java-standalone-status")
                    require(decoded(result["standaloneStatus"])[0][0]["sequence"] == "18446744073709551615",
                            "java-domain-full-width-result")
                if http:
                    route(client, host, publications["adapter"])
                    result["missingGrant"] = context.capture_http(client, host, expected=(403,))
                    result["missingGrantStatus"] = 403
                    service_generation = service_grant(client, node, publications)
                    targets["adapter"] = deploy(client, releases / "java-http-adapter/deployment.json", publications["adapter"],
                        generation=str(targets["adapter"]["generation"]), grants=targets["adapter"]["grants"] + [
                            {"capability": SERVICE_CAPABILITY, "policy": "java-domain-allow"}])
                    require(request(host)[0] in (409, 503), "java-http-stale-deployment-target-accepted")
                    route(client, host, publications["adapter"])
                    result["composed"] = fresh_status(client, targets, host, "java-domain-direct-composed")
                    generated_client = run_bounded_result(["node", "--dns-result-order=ipv4first",
                        str(ROOT / "examples/java-http-composition/client-test.mjs"), "http://" + host,
                        str(releases.parent / "projects/adapter/http/client.mjs")],
                        cwd=ROOT, env=client.environment, timeout_seconds=180, max_output_bytes=8192)
                    (evidence / "generated-client.stdout.log").write_bytes(generated_client.stdout)
                    (evidence / "generated-client.stderr.log").write_bytes(generated_client.stderr)
                    require(generated_client.returncode == 0, "java-http-normal-generated-client-failed")
                    result["generatedClient"] = json.loads(generated_client.stdout)
                    result["context"] = context.qualify(client, targets, host, evidence)
                    result["ordinaryContextImport"] = context.ordinary_import(client, targets, releases, publications, host)
                    service_generation = service_grant(client, node, publications,
                        generation=service_generation, trigger_only=True)
                    impersonation = invoke(client, targets, "adapter", "handle", web_request(host), "java-trigger-impersonation", codes=(4,))
                    require(impersonation["category"] == "platform-failure" and impersonation["error"]["code"] == "permission-denied"
                        and impersonation["outcomeKnown"], "java-operator-impersonated-original-http-trigger")
                    result["triggerImpersonationDenied"] = impersonation
                    result["triggerImpersonationTree"] = context.tree(client, "java-trigger-impersonation")
                    impersonation_nodes = result["triggerImpersonationTree"]["nodes"]
                    require(len(impersonation_nodes) == 1 and impersonation_nodes[0]["principalKind"] == "administrator"
                        and impersonation_nodes[0]["callerService"] is None, "java-context-operator-cannot-inherit-ingress-trigger")
                    service_generation = service_grant(client, node, publications, generation=service_generation)
                    route(client, host, publications["adapter"])
                    wide = decoded(result["standaloneStatus"])[0][0]
                    for path, arguments in (("echo", [wide]),
                            ("nested", [{"value": wide, "optional": {"some": wide}, "labels": ["Grüße 😀"]}]),
                            ("text", ["UTF-8 Grüße 😀\u0000"]), ("items", [["a", "b", "😀"]])):
                        status, body, _ = request(host, "/api/" + path, method="POST", value=arguments)
                        require(status == 200 and json.loads(body) == arguments, "java-http-safe-typed-" + path)
                    for path in ("private-admin", "publishing", "provider-event", "missing"):
                        require(request(host, "/api/" + path)[0] == 404, "java-http-private-route-generated")
                    require(request(host, "/api/fail")[0] == 422, "java-http-declared-error-erased")
                    require(request(host, "/api/throw")[0] == 500, "java-http-java-exception-became-declared-error")
                    for path, arguments in (("text", ["x" * (256 * 1024 + 1)]), ("items", [["x"] * 4097]),
                                            ("echo", [{"a": "missing-fields"}])):
                        require(request(host, "/api/" + path, method="POST", value=arguments)[0] in (400, 413, 503),
                                "java-http-over-limit-value-accepted")
                        idle(client)
                        require(request(host)[0] == 200, "java-http-rejected-value-poisoned-next-activation")
                    for headers in ({"Host": "spoofed.invalid"}, {"X-Forwarded-Host": "spoofed.invalid"},
                                    {"Authorization": "Bearer spoofed-platform-token"}):
                        require(request(host, headers=headers)[0] in (400, 401, 403), "java-http-spoofed-authority-accepted")
                    cancellation(client, targets, host, result)
                    result["canary"] = canary(client, targets, publications, releases, host)
                result["cleanup"] = idle(client)
                deployments = client.call("deployment", "list")["data"]["deployments"]
                delete_all(client, [row["manifest"]["metadata"]["name"] for row in deployments])
                stop(client, node)
                result["nodeStopped"] = node.owner.finished
                result["status"] = "passed"
            except BaseException as error:
                result.update(status="failed", reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
                raise
            finally:
                if node is not None:
                    client.node = None
                    node.close()
                    (evidence / "node.stderr.log").write_bytes(bytes(node.buffers[1]))
                write_workflow_receipt(evidence / "workflow.json", result)
    return result


def qualify(output, wasi_sdk, target):
    require(sys.platform == "linux" and sys.version_info >= (3, 13), "java-http-linux-python313-required")
    output = fresh(output)
    def inputs():
        checkout = run_bounded_result(["git", "rev-parse", "HEAD"], cwd=ROOT, env=build_environment(output),
            timeout_seconds=10, max_output_bytes=128)
        require(checkout.returncode == 0, "java-http-checkout-identity-unavailable")
        return {"checkout": checkout.stdout.decode("ascii").strip(), "runtime": source_identity(ROOT),
            "fixture": inventory(ROOT / "examples/java-http-composition"),
            "javaSdk": inventory(ROOT / "sdk/java-guest"), "wit": inventory(ROOT / "wit/platform"),
            "helpers": inventory(ROOT / "tools/java_http_composition"),
            "generator": inventory(ROOT / "tools/java_http_generation")}
    before = inputs()
    binaries = {name: target / "debug" / name for name in (
        "latent", "latentd", "examples/package", "examples/capsule_contracts", "examples/capsule_authoring")}
    identities = {name: file_identity(path) for name, path in binaries.items()}
    result = {"schemaVersion": "latent.java-http.qualification.v1", "status": "in-progress",
        "scope": "signed-local-experimental-node-with-enforced-admission", "source": before, "binaries": identities,
        "historicalFailure": {"runtimeSource": "2d6cc2eafc0a17dfe573be4252fa49835bebbbd6",
            "applicationHead": "80793e79392696f47cc7ec739a0139368c06ab53",
            "actualApplicationCheckout": "d38e168c7bfc270e5e257f6b2c3b591dca24e104",
            "outcome": "recorded-http-503-not-reexecuted", "privateApplicationQualification": "unavailable"},
        "releasePublication": "not-performed"}
    stage = "java-builds"
    try:
        built = compile_pair(output, wasi_sdk, binaries)
        result["generation"] = read_json(output / "projects/adapter/http/generation.json")
        result["generationCases"] = read_json(output / "generation-cases/generation-cases.json")
        result["builds"] = {name: read_json(path / "BUILD-COMPLETE.json") for name, path in built.items()}
        require(result["builds"]["domain"]["componentDigest"] != result["builds"]["adapter"]["componentDigest"],
                "java-http-independently-compiled-components")
        stage = "sign"
        (output / "signing").mkdir(mode=0o700)
        commands = Commands(ROOT, output / "signing", build_environment(output / "signing"))
        commands.run("demo-sign", binaries["examples/capsule_authoring"], "demo-sign", output / "releases", *built.values())
        result["releaseSet"] = read_json(output / "releases/release-set.json")
        signed_inputs = inventory(output / "releases", maximum_bytes=128 * 1024 * 1024)
        result["signedInputs"] = signed_inputs
        stage = "former-http-global-profile"
        result["formerProfile"] = run_node(binaries, output / "releases", output / "former-profile", http=False,
                                            former_profile=True)
        stage = "standalone-profile"
        result["standalone"] = run_node(binaries, output / "releases", output / "standalone", http=False)
        stage = "http-profile"
        result["http"] = run_node(binaries, output / "releases", output / "http", http=True)
        require(before == inputs()
            and identities == {name: file_identity(path) for name, path in binaries.items()}
            and signed_inputs == inventory(output / "releases", maximum_bytes=128 * 1024 * 1024),
            "java-http-qualified-inputs-changed")
        result["status"] = "passed"
        write_workflow_receipt(output / "qualification.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", stage=stage, reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        write_workflow_receipt(output / "QUALIFICATION-FAILED.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")))
    args = parser.parse_args()
    qualify(args.output.resolve(), args.wasi_sdk.resolve(), args.target.resolve())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Publish, deploy, invoke and clean up standalone Rust capsules on a real local node."""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import run_bounded
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import (Client, Process, WorkflowError, bounded_receipt,
    read_json, require, stopped_record, write_json)
from tools.phase2_operator_scenario import NODE_ID, configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools import rust_capsule as authoring


def payload(result):
    body = result["data"]["declaredError"]["payload"] if result["category"] == "declared-error" else result["data"].get("payload")
    require(isinstance(body, dict) and body["encoding"] == "base64"
            and body["mediaType"] == "application/vnd.latent.wit-values.v1+json", "authoring-payload-encoding")
    return json.loads(base64.b64decode(body["data"], validate=True))


def idle(client):
    deadline = min(client.deadline, time.monotonic()+5)
    while time.monotonic() < deadline:
        value = client.call("node", "get", NODE_ID)["data"]["inventory"]
        if (all(row["active"] == 0 and row["quarantined"] == 0 for row in value["cellCapacity"])
                and value["queueDepth"] == "0" and value["cacheSummary"]["preparing"] == "0"
                and value["quotas"]["usage"]["activeActivations"] == 0
                and value["quotas"]["usage"]["reservedMemoryBytes"] == "0"):
            return {key:value[key] for key in ("cellCapacity","queueDepth","cacheSummary","quotas")}
        time.sleep(0.01)
    raise WorkflowError("authoring-cleanup-did-not-retire")


def deploy(client, trust, builds, records):
    targets = {}
    for name in records:
        source = trust / name
        manifest = read_json(builds / name / "capsule.json")
        service = manifest["metadata"]["name"]
        require(len(manifest["exports"]) == 1 and not manifest["imports"], "authoring-demo-public-contract")
        published = client.call("release", "publish-package", source / "package",
                                "--evidence", source / "evidence/index.json",
                                "--operation-id", "publish-"+name, "--expected-generation", "0")
        require(published["outcomeKnown"], "authoring-publication-uncertain")
        publication = published["data"]["operation"]["publication"]["id"]
        deployment = {"apiVersion":"latent.dev/v1alpha1","kind":"Deployment",
            "metadata":{"name":name,"tenant":"tests"},
            "spec":{"service":service,"release":records[name]["componentDigest"],"publication":publication,
                    "route":{"weight":10000},"grants":[],"resources":manifest["execution"]["limits"],
                    "availability":{"minimumCachedCopies":1,"minimumZones":1},
                    "placement":{"trustClass":"internal","architectures":["x86_64"]}}}
        path = client.directory / (name+"-deployment.json")
        write_json(path, deployment)
        snapshot = client.call("deployment", "get", name, "--operation-snapshot", codes=(6,))["data"]
        applied = client.call("deployment", "apply", path, "--operation-id", "deploy-"+name,
                             "--expected-generation", "0", "--expected-state-version", snapshot["stateVersion"])
        require(applied["outcomeKnown"], "authoring-deployment-uncertain")
        targets[name] = {"name":name, "service":service, "contract":manifest["exports"][0]}
    return targets


def arguments(client, target, function, values, extra=()):
    name = "authoring-"+str(client.calls)
    path = client.directory / (name+".json")
    write_json(path, values)
    return ["invoke", "--service", target["service"], "--contract", target["contract"],
            "--function", function, "--input", path, "--activation-id", name, *extra]


def invoke(client, target, function, values, expected=None, code=0, extra=()):
    began = time.monotonic_ns()
    result = client.call(*arguments(client, target, function, values, extra), codes=(code,))
    require(result["outcomeKnown"], "authoring-invocation-uncertain")
    if expected is not None:
        require(payload(result) == expected, "authoring-typed-result-"+target["name"]+"-"+function)
    if code == 3:
        require(result["category"] == "declared-error", "authoring-declared-error-lost")
    record = {"function": function, "service": target["service"], "activationId": result["data"]["activationId"],
              "category": result["category"], "elapsedMicros": (time.monotonic_ns()-began)//1000}
    if code == 4:
        record["errorCode"] = result["error"]["code"]
    idle(client)
    return record


def cancelled(client, target, probe):
    args = arguments(client, target, "spin", [], ("--wall-time-ms", "4000", "--cpu-fuel", "10000000000"))
    activation = args[args.index("--activation-id")+1]
    pending = Process([client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator", *map(str,args)],
                      client.directory, client.environment, client.cancellation)
    try:
        deadline = min(client.deadline, time.monotonic()+3)
        while True:
            status = client.call("activation", "get", activation, codes=(0,6))
            if status["category"] == "success" and status["data"]["phase"] == "running":
                break
            require(time.monotonic() < deadline, "authoring-cancel-never-running")
            time.sleep(0.01)
        active = probe.sample()
        admitted = client.call("activation", "cancel", activation, "--reason", "authoring qualification")
        require(admitted["data"]["disposition"] == "accepted", "authoring-cancel-not-accepted")
        result = pending.complete(min(client.deadline, time.monotonic()+10))
        value = json.loads(result.stdout)
        require(result.returncode == 4 and value["error"]["code"] == "cancelled", "authoring-cancel-outcome")
        idle(client)
        return {"activationId":activation, "observedRunning":True,"errorCode":"cancelled"}, active
    finally:
        pending.close()


def conformance(client, targets, builds, probe):
    calls = []
    for name, function, good, wanted, bad, denied in (
        ("greeting","greet",["  Ada  "],[{"ok":"Hello, Ada!"}],["  "],[{"err":"Please enter a name."}]),
        ("word-count","count",["one two three"],[{"ok":3}],["x"*4097],[{"err":"Use text of at most 4096 bytes."}]),
        ("shipping","quote",[2,False],[{"ok":650}],[0,True],[{"err":"Choose between 1 and 100 items."}]),
    ):
        calls.append(invoke(client,targets[name],function,good,wanted))
        calls.append(invoke(client,targets[name],function,bad,denied,3))
        calls.append(invoke(client,targets[name],function,good,wanted))
    diagnostic = targets["diagnostics"]
    message = {"unsigned":"18446744073709551615","signed":"-9223372036854775808",
               "text":"Unicode é 世界"+chr(0), "values":["0","18446744073709551615"]}
    calls.append(invoke(client,diagnostic,"echo",[message],[{"ok":message}]))
    calls.append(invoke(client,diagnostic,"fresh",[],[1]))
    for function, extra, expected_error in (("trap",(),"guest-trap"),
        ("spin",("--wall-time-ms","80","--cpu-fuel","10000000000"),"deadline-exceeded"),
        ("spin",("--cpu-fuel","1",),"resource-exhausted")):
        attempt = invoke(client,diagnostic,function,[],code=4,extra=extra)
        require(attempt["errorCode"] == expected_error, "authoring-"+function+"-error-category")
        calls.append(attempt)
        calls.append(invoke(client,diagnostic,"fresh",[],[1]))
    budget = read_json(builds/"diagnostics"/"capsule.json")["execution"]["limits"]
    budget["memoryBytes"] = 65536
    path = client.directory/"memory-bound.json"; write_json(path,budget)
    exhausted = invoke(client,diagnostic,"fresh",[],code=4,extra=("--budget",path))
    require(exhausted["errorCode"] == "resource-exhausted", "authoring-memory-limit")
    calls.append(exhausted)
    calls.append(invoke(client,diagnostic,"fresh",[],[1]))
    cancelled_result, active = cancelled(client,diagnostic,probe)
    calls.append(cancelled_result)
    calls.append(invoke(client,diagnostic,"fresh",[],[1]))
    return calls, active


def run(args):
    names = ("greeting", "word-count", "shipping", "diagnostics") if args.conformance else (args.project.name,)
    builds = args.builds if args.conformance else args.project.parent
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-rust-node-") as temporary:
        root = Path(temporary); root.chmod(0o700)
        request = root / "approval.json"
        repository = read_json(builds / names[0] / "build-observation.json")["source"]["repository"]
        write_json(request, {"formatVersion":1,"repository":repository,
                            "projects":[{"name":name,"directory":str(builds/name)} for name in names]})
        trust = root / "trust"
        run_bounded([str(args.packager), "local-trust", "--approve-local-source", str(request), str(trust)],
                    root, {"PATH":"/usr/bin:/bin","HOME":str(root)}, timeout_seconds=60, max_output_bytes=65536)
        records = {row["name"]:row for row in read_json(trust/"fixture.json")["fixtures"]}
        node_root, client_root = root/"node", root/"client"
        node_root.mkdir(mode=0o700); client_root.mkdir(mode=0o700)
        client = Client(args.cli, client_root, cancellation, time.monotonic()+300)
        config = configure_node(node_root, trust, "tests")
        node = None
        try:
            began = time.monotonic_ns()
            node = connect(client, args.node, node_root, config, "tests", 1)
            startup = (time.monotonic_ns()-began)//1000
            probe = Probe(node, file_identity(args.node))
            samples = {"beforeDeployment":probe.sample()}
            targets = deploy(client, trust, builds, records)
            dormant = idle(client)
            samples["dormantDeployments"] = probe.sample()
            require(samples["beforeDeployment"]["metrics"]["processes"] == samples["dormantDeployments"]["metrics"]["processes"] == 1,
                    "authoring-dormant-process-growth")
            for key in ("listeners", "threads"):
                require(samples["beforeDeployment"]["metrics"][key] == samples["dormantDeployments"]["metrics"][key],
                        "authoring-dormant-"+key+"-growth")
            require(sum(row["total"] for row in dormant["cellCapacity"]) == 1, "authoring-deployment-owned-cell")
            if args.conformance:
                calls, active = conformance(client,targets,builds,probe)
                samples["activeInvocation"] = active
            else:
                values = json.loads(authoring.read(args.input))
                calls = [invoke(client,targets[names[0]],args.function,values,code=args.expected_exit)]
            after = idle(client)
            samples["afterInvocations"] = probe.sample()
            require(samples["afterInvocations"]["metrics"]["processes"] == 1, "authoring-activation-process-leak")
            stop(client,node)
            shutdown = stopped_record(node)
            require(shutdown["record"]["report"]["providers"]["clean"],"authoring-provider-cleanup")
            node = None
            return {"schemaVersion":"latent.rust.authoring.workflow.v1", "nodeStartupMicros":startup,
                    "executables":{"node":file_identity(args.node),"cli":file_identity(args.cli)},
                    "builds":records,"clientCommands":client.calls,"calls":calls,"samples":samples,
                    "dormantInventory":dormant,"finalInventory":after,"shutdown":shutdown,
                    "limitations":["RSS includes the node and bounded shared caches, not isolated guest allocator usage",
                                    "OS samples are non-atomic; unavailable fields are not zero",
                                    "Local trust is explicit, temporary and not production approval"]}
        finally:
            if node is not None:
                node.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cli", "node", "packager", "receipt"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--approve-local-source",action="store_true",required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--builds",type=Path)
    group.add_argument("--project",type=Path)
    parser.add_argument("--function")
    parser.add_argument("--input",type=Path)
    parser.add_argument("--expected-exit",type=int,choices=(0,3,4),default=0)
    args = parser.parse_args()
    args.conformance = args.builds is not None
    require(sys.platform == "linux", "authoring-local-node-platform")
    require(args.conformance or (args.function and args.input), "authoring-invocation-required")
    require(not args.receipt.exists(), "authoring-receipt-already-exists")
    for name in ("cli","node","packager","builds","project","input"):
        if getattr(args,name) is not None:
            setattr(args,name,getattr(args,name).resolve(strict=True))
    try:
        result = run(args)
        args.receipt.write_text(bounded_receipt(result)+"\n")
        print("Rust authoring real-node workflow passed")
    except BaseException as error:
        args.receipt.write_text(json.dumps({"schemaVersion":"latent.rust.authoring.failed.v1","errorType":type(error).__name__,"success":False})+"\n")
        raise


if __name__ == "__main__":
    main()

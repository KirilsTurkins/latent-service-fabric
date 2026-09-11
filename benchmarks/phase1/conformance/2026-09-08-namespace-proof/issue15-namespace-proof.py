"""One RPC-published echo across distinct mount namespaces; no build or heavy work."""

import base64
import hashlib
import json
import pathlib
import secrets
import shutil
import subprocess
import sys
import threading
import time


ROOT = pathlib.Path(__file__).resolve().parent
CLIENT = "lsf-phase1-implementation"
IMAGE = "lsf-phase0-gate:local"
RUN = secrets.token_hex(8)
NODE = "lsf-cli-namespace-" + RUN
CLIENT_ROOT = "/tmp/lsf-cli-namespace-" + RUN
STAGING = ROOT / ("namespace-staging-" + RUN)
TOKEN = secrets.token_hex(32)
START = time.monotonic()
INVOKES = 0
CREATED = False
CLIENT_CREATED = False
EVIDENCE = {"schema": "latent.cli.namespace-proof.v1", "run": RUN, "status": "failed"}


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def event(kind, **fields):
    encoded = json.dumps({"event": kind, **fields}, sort_keys=True)
    require(TOKEN not in encoded, "credential redaction invariant")
    print(encoded, flush=True)


def run(arguments, label, *, stdin=None, timeout=30, maximum=65536, cleanup=False, quiet_stderr=False):
    if not cleanup:
        require(time.monotonic() - START < 150, "overall proof watchdog")
    require(TOKEN not in " ".join(arguments), "credential must never enter process argv")
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    captured = [bytearray(), bytearray()]
    failed = threading.Event()

    def read(stream, index):
        try:
            while chunk := stream.read(4096):
                if len(captured[index]) + len(chunk) > maximum:
                    failed.set()
                    process.kill()
                    break
                captured[index].extend(chunk)
        except OSError:
            failed.set()
        finally:
            stream.close()

    readers = [
        threading.Thread(target=read, args=(process.stdout, 0)),
        threading.Thread(target=read, args=(process.stderr, 1)),
    ]
    for reader in readers:
        reader.start()
    try:
        if stdin is not None:
            require(len(stdin) <= 16384, "bounded private command input")
            process.stdin.write(stdin)
            process.stdin.close()
        code = process.wait(timeout=timeout)
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError(label + " command watchdog/failure") from None
    finally:
        for reader in readers:
            reader.join(timeout=5)
        require(not any(reader.is_alive() for reader in readers), label + " reader cleanup")
    require(not failed.is_set(), label + " output bound")
    require(code == 0, label + " command failed (raw diagnostics withheld)")
    require(not quiet_stderr or not captured[1], label + " unexpected stderr")
    return bytes(captured[0])


def docker(*arguments, label, **kwargs):
    return run(["docker", *arguments], label, **kwargs)


def py(container, source, *, value=None, label, **kwargs):
    args = ["exec"]
    if value is not None:
        args.append("-i")
    args += [container, "python3", "-c", source]
    stdin = None if value is None else json.dumps(value).encode()
    return docker(*args, label=label, stdin=stdin, **kwargs)


def cli(*arguments, category="success"):
    global INVOKES
    if arguments[0] == "invoke":
        INVOKES += 1
        require(INVOKES == 1, "exactly one invocation authorized")
    # A local GNU timeout owns the actual CLI even if the supervising Docker
    # command is interrupted; host readers enforce the 64 KiB output ceiling.
    output = docker("exec", CLIENT, "timeout", "--signal=KILL", "5",
                    "/workspace/project/target/debug/latent", "--config", CLIENT_ROOT + "/client.json",
                    "--output", "json", *arguments, label="CLI " + arguments[0], timeout=10, quiet_stderr=True)
    require(TOKEN.encode() not in output, "CLI credential redaction")
    require(output.endswith(b"\n") and len(output.splitlines()) == 1, "one CLI JSON result")
    document = json.loads(output)
    require(document["schemaVersion"] == "latent.cli.result.v1", "CLI schema")
    require(document["category"] == category, "CLI result category")
    require(document["requestDispatched"] is True, "real RPC was dispatched")
    require(document["outcomeKnown"] is True, "result certainty")
    return document


HASHES = r'''
import hashlib,json,pathlib,sys
paths=json.load(sys.stdin)
def digest(name):
 p=pathlib.Path(name); size=p.stat().st_size
 if size>512*1024*1024: raise SystemExit(33)
 h=hashlib.sha256()
 with p.open('rb') as f:
  while chunk:=f.read(1024*1024): h.update(chunk)
 return {'sha256':h.hexdigest(),'bytes':size}
print(json.dumps({p:digest(p) for p in paths}))
'''


def main():
    global CREATED, CLIENT_CREATED
    require(STAGING.resolve().parent == ROOT and STAGING.name == "namespace-staging-" + RUN, "host staging containment")
    STAGING.mkdir()
    private = STAGING / "node-private"
    private.mkdir()
    image = docker("image", "inspect", IMAGE, "--format", "{{.Id}}", label="image identity").decode().strip()
    EVIDENCE["image"] = image
    source_paths = [
        "/workspace/project/target/debug/latent", "/workspace/project/target/debug/latentd",
        "/workspace/project/target/capsules/echo/echo-capsule.wasm",
        "/workspace/project/target/capsules/echo/capsule.json",
        "/workspace/project/target/capsules/echo/contracts.json",
    ]
    hashes = json.loads(py(CLIENT, HASHES, value=source_paths, label="binary and fixture hashes"))
    EVIDENCE["inputs"] = hashes
    docker("cp", CLIENT + ":/workspace/project/target/debug/latentd", str(private / "latentd"), label="copy only node binary", timeout=45)
    node_config = {
        "formatVersion": 1, "dataDirectory": "/node-private/data", "nodeId": "namespace-node",
        "bind": "127.0.0.1:0", "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2, "maximumMemoryBytes": 67108864}],
        "execution": {"maximumCpuFuel": 100000000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16384},
        "cache": {"entries": 2, "preparations": 1}, "catalogs": {"releaseEntries": 4, "deployments": 4},
        "retention": {"terminalEntries": 8, "terminalTtlMillis": 30000}, "shutdownGraceMillis": 100,
        "credentials": [{"token": TOKEN, "subject": "namespace-operator", "tenant": "examples", "role": "operator"}],
    }
    config_bytes = json.dumps(node_config, separators=(",", ":")).encode()
    (private / "node.json").write_bytes(config_bytes)
    EVIDENCE["node_config_sha256"] = hashlib.sha256(config_bytes).hexdigest()
    CREATED = True
    docker("create", "--name", NODE, "--label", "latent.namespace-proof=" + RUN, "--network", "container:" + CLIENT,
           "--entrypoint", "/bin/sh", IMAGE, "-c",
           "chmod 700 /node-private /node-private/latentd && chmod 600 /node-private/node.json && exec /node-private/latentd serve --config /node-private/node.json",
           label="create isolated node")
    docker("cp", str(private), NODE + ":/node-private", label="copy private node files", timeout=45)
    mounts = json.loads(docker("inspect", NODE, "--format", "{{json .Mounts}}", label="verify no mounts"))
    require(mounts == [], "node has no source/client mounts")
    network = docker("inspect", NODE, "--format", "{{.HostConfig.NetworkMode}}", label="network namespace sharing").decode().strip()
    require(network.startswith("container:"), "shared loopback only")
    docker("start", NODE, label="start node")
    started = None
    for _ in range(30):
        logs = docker("logs", NODE, label="bounded startup log", maximum=16384)
        if logs:
            records = [json.loads(line) for line in logs.splitlines()]
            started = records[0]
            require(started["schemaVersion"] == "latent.standalone.status.v1", "node status schema")
            require(started["event"] in ["started", "ready"], "node startup event")
            break
        time.sleep(0.05)
    require(started is not None, "node startup observed")
    endpoint = "http://" + started["endpoint"]
    client_mount = docker("exec", CLIENT, "readlink", "/proc/self/ns/mnt", label="client mount namespace").decode().strip()
    node_mount = docker("exec", NODE, "readlink", "/proc/self/ns/mnt", label="node mount namespace").decode().strip()
    require(client_mount != node_mount, "mount namespaces must be distinct")
    node_hashes = json.loads(py(NODE, HASHES, value=["/node-private/latentd"], label="copied binary identity"))
    require(node_hashes["/node-private/latentd"] == hashes[source_paths[1]], "node binary copy identity")
    EVIDENCE["namespaces"] = {"client_mount": client_mount, "node_mount": node_mount, "node_mounts": mounts, "network_mode": network}
    EVIDENCE["endpoint"] = endpoint

    prepare = r'''
import hashlib,json,pathlib,shutil,sys
v=json.load(sys.stdin); root=pathlib.Path(v['root'])
assert root.parent==pathlib.Path('/tmp') and root.name.startswith('lsf-cli-namespace-') and not root.exists()
root.mkdir(mode=0o700)
source=pathlib.Path('/workspace/project/target/capsules/echo')
for name in ['echo-capsule.wasm','capsule.json','contracts.json']: shutil.copyfile(source/name,root/name)
component=(root/'echo-capsule.wasm').read_bytes(); digest='sha256:'+hashlib.sha256(component).hexdigest()
manifest=json.loads((root/'capsule.json').read_bytes()); assert manifest['component']['digest']==digest
deployment=json.loads(pathlib.Path('/workspace/project/examples/echo-contract/deployment.json').read_bytes())
deployment['metadata']['name']='namespace-echo'; deployment['spec']['release']=digest
(root/'deployment.json').write_text(json.dumps(deployment))
(root/'input.json').write_text(json.dumps(['separate mount namespace']))
(root/'client.json').write_text(json.dumps({'formatVersion':1,'profiles':[{'name':'local','tenant':'examples','endpoint':v['endpoint'],'token':v['token'],'connectTimeoutMillis':1000,'rpcTimeoutMillis':3000}]}))
(root/'client.json').chmod(0o600)
print(json.dumps({'root':str(root),'digest':digest}))
'''
    CLIENT_CREATED = True
    prepared = json.loads(py(CLIENT, prepare, value={"root": CLIENT_ROOT, "endpoint": endpoint, "token": TOKEN}, label="prepare private client package"))
    absent = py(NODE, "import json,pathlib,sys; p=json.load(sys.stdin); print(json.dumps({'exists':pathlib.Path(p).exists()}))", value=CLIENT_ROOT, label="node cannot see client package")
    require(json.loads(absent)["exists"] is False, "client package absent in server namespace")
    EVIDENCE["client_package"] = {"path": CLIENT_ROOT, "node_path_exists_before_publication": False, "release_digest": prepared["digest"]}
    event("isolation_verified", client_mount=client_mount, node_mount=node_mount, node_mounts=0)

    for _ in range(20):
        inventory = cli("node", "get", "namespace-node")
        if inventory["data"]["inventory"]["health"]["ready"] is True:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("node ready inventory not observed")
    release = cli("release", "publish", "--manifest", CLIENT_ROOT + "/capsule.json", "--component", CLIENT_ROOT + "/echo-capsule.wasm", "--contracts", CLIENT_ROOT + "/contracts.json")
    require(release["data"]["release"]["digest"] == prepared["digest"], "published release identity")
    applied = cli("deployment", "apply", CLIENT_ROOT + "/deployment.json", "--expected-generation", "0")
    generation = applied["data"]["deployment"]["generation"]
    require(isinstance(generation, str) and int(generation) > 0, "object version receipt")
    result = cli("invoke", "--service", "examples/echo", "--contract", "examples:echo/api@0.1.0", "--function", "echo", "--input", CLIENT_ROOT + "/input.json", "--activation-id", "namespace-proof-invoke")
    payload = result["data"]["payload"]
    require(json.loads(base64.b64decode(payload["data"], validate=True)) == [{"ok": "separate mount namespace"}], "actual generic echo result")
    require(result["data"]["resolvedRevision"]["releaseDigest"] == prepared["digest"], "invocation release pin")
    status = cli("activation", "get", "namespace-proof-invoke")
    require(status["data"]["terminalState"] == "completed", "retained terminal status")
    inventory = cli("node", "get", "namespace-node")
    require(inventory["data"]["inventory"]["cellCapacity"][0]["active"] == 0, "cell reclaimed before shutdown")
    deleted = cli("deployment", "delete", "namespace-echo", "--expected-generation", generation)
    require(deleted["category"] == "success", "versioned deletion")
    absent = py(NODE, "import json,pathlib,sys; p=json.load(sys.stdin); print(json.dumps({'exists':pathlib.Path(p).exists()}))", value=CLIENT_ROOT, label="client package remains namespace-private")
    require(json.loads(absent)["exists"] is False, "no node-side caller path became visible")
    EVIDENCE["client_package"]["node_path_exists_after_invocation"] = False
    EVIDENCE["invocation"] = {"attempts": INVOKES, "activation_id": result["data"]["activationId"], "resolved_revision": result["data"]["resolvedRevision"], "consumption": result["data"]["consumption"], "outcome": "success", "retained_terminal_state": "completed"}
    event("rpc_workflow_passed", invocations=INVOKES, published=prepared["digest"], deployment_generation=generation)
    docker("kill", "--signal", "SIGTERM", NODE, label="signal node shutdown")
    code = docker("wait", NODE, label="reap exited node", timeout=10).decode().strip()
    require(code == "0", "node clean exit")
    logs = docker("logs", NODE, label="bounded stopped evidence", maximum=32768)
    require(TOKEN.encode() not in logs, "node status redaction")
    records = [json.loads(line) for line in logs.splitlines()]
    require(len(records) == 2 and records[1]["event"] == "stopped" and records[1]["clean"] is True, "exact startup/shutdown status records")
    report = records[1]["report"]
    require(report["clean"] is True and report["telemetryFlushed"] is True and report["epochHelperJoined"] is True, "clean teardown owners")
    counters = ["activeConnections", "activeRpcs", "activeControlJobs", "activeActivations", "cancellationRegistrations", "observerCorrelations", "quotaReservations", "queuedReservations", "reservedCpuFuel", "reservedMemoryBytes", "activeLeases", "queuedActivations", "activeBackendInvocations", "instanceReservations", "preparingComponents", "preparingSourceBytes", "preparingMetadataBytes", "liveStores", "liveHostStates", "liveInstances", "liveTemporaryBuffers", "liveCancellationProbes"]
    require(all(report.get(name) == 0 for name in counters), "all transient shutdown counters zero")
    EVIDENCE["shutdown"] = report
    EVIDENCE["status"] = "passed"


def cleanup():
    failures = []
    if CREATED:
        try:
            require(NODE == "lsf-cli-namespace-" + RUN and NODE != CLIENT, "only disposable container cleanup")
            label = docker("inspect", NODE, "--format", '{{index .Config.Labels "latent.namespace-proof"}}', label="verify disposable ownership", cleanup=True).decode().strip()
            require(label == RUN, "disposable container ownership label")
            docker("rm", "-f", NODE, label="remove disposable node", cleanup=True)
        except Exception:
            failures.append("disposable-node")
    if CLIENT_CREATED:
        try:
            py(CLIENT, "import json,pathlib,shutil,sys; p=pathlib.Path(json.load(sys.stdin)); assert p.parent==pathlib.Path('/tmp') and p.name=='lsf-cli-namespace-" + RUN + "'; shutil.rmtree(p)", value=CLIENT_ROOT, label="remove only random client package", cleanup=True)
        except Exception:
            failures.append("random-client-package")
    if STAGING.exists():
        require(STAGING.resolve().parent == ROOT and STAGING.name == "namespace-staging-" + RUN, "host cleanup containment")
        shutil.rmtree(STAGING)
    EVIDENCE["cleanup"] = {"failures": failures, "persistent_container_untouched": True}
    require(not failures, "bounded proof cleanup incomplete")


if __name__ == "__main__":
    status = 0
    try:
        main()
    except Exception as error:
        status = 1
        EVIDENCE["failure"] = str(error).replace(TOKEN, "[redacted]")[:256]
    finally:
        try:
            cleanup()
        except Exception:
            status = 1
            EVIDENCE["failure"] = "proof cleanup failed"
        EVIDENCE["elapsed_seconds"] = round(time.monotonic() - START, 3)
        EVIDENCE["status"] = "passed" if status == 0 else "failed"
        event("namespace_proof", evidence=EVIDENCE)
    sys.exit(status)

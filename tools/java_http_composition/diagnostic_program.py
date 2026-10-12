"""Prepare and execute the existing standalone Java diagnostic owners separately.

Preparation publishes supplied signed fixtures and reads native identities. It
applies zero capability policies and invokes no guest or provider request. The
same retained configuration/catalog and nonrenewable boot/deadline are required
for execution after review of the exact candidate bytes.
"""
from contextlib import contextmanager
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from tools.build_process_signals import owned_cancellation
from tools.java_http_composition import context, history_diagnostics, inspection, native_inputs, policy_proposals
from tools.java_http_composition import provider_timeout, resource_diagnostics
from tools.java_http_composition.node import (SERVICE_CAPABILITY, TENANT, configure, grant, idle, invoke,
    rebind, request, route, service_grant, web_request)
from tools.java_http_composition.qualify import fresh_status, publish
from tools.phase2_operator_process import read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.run_security_profile_workflow import replace_config
from tools.rust_capsule_node import RecordingClient, deploy
from tools.rust_capsule_project import ROOT, fresh
from tools.sdk_provider_scenario import close_failed_provider, start_provider

SECONDS = 900
SCHEMA = "latent.java-preparation-diagnostics.candidate.v1"


def compact(value):
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    require(len(encoded) <= 262144, "java-diagnostic-record-bound")
    return encoded


def digest(value):
    return hashlib.sha256(compact(value)).hexdigest()


def clock():
    require(sys.platform == "linux" and os.geteuid() != 0 and sys.version_info[:3] == (3, 13, 5),
            "java-diagnostic-pinned-unprivileged-linux")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot), "java-diagnostic-original-boot")
    return {"bootId": boot, "deadlineMonotonicNanos": str(time.monotonic_ns() + SECONDS * 1_000_000_000)}


def deadline(original):
    require(Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() == original["bootId"],
            "java-diagnostic-original-boot-changed")
    raw = original["deadlineMonotonicNanos"]
    require(isinstance(raw, str) and re.fullmatch(r"[1-9][0-9]{0,19}", raw), "java-diagnostic-original-deadline")
    end = int(raw) / 1_000_000_000
    require(0 < end - time.monotonic() <= SECONDS, "java-diagnostic-original-deadline-expired-or-renewed")
    return end


def sources():
    pending = ["tools/qualify_java_preparation_diagnostics.py", "tools/sdk_provider_scenario.py",
               "tools/sdk_provider_http_fixture.py"]
    pending += [path.relative_to(ROOT).as_posix() for path in (ROOT / "tools/java_http_composition").glob("*.py")]
    observed, total = {}, 0
    while pending:
        name = pending.pop()
        if name in observed:
            continue
        require(len(observed) < 256, "java-diagnostic-conductor-owner-bound")
        path = ROOT / name
        identity = file_identity(path, 1048576)
        total += identity["bytes"]
        require(total <= 4194304, "java-diagnostic-conductor-byte-bound")
        observed[name] = identity
        module = name[:-3].replace("/", ".")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            selected = []
            if isinstance(node, ast.Import):
                selected = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = module.rsplit(".", node.level)[0] if node.level else ""
                imported = ".".join(value for value in (base, node.module) if value)
                selected = [imported, *(imported + "." + alias.name for alias in node.names)]
            for imported in selected:
                if imported != "tools" and not imported.startswith("tools."):
                    continue
                for relative in (imported.replace(".", "/") + ".py",
                                 imported.replace(".", "/") + "/__init__.py"):
                    if (ROOT / relative).is_file() and relative not in observed:
                        pending.append(relative)
    return {"owners": dict(sorted(observed.items())), "requirements": file_identity(ROOT / "tools/requirements.lock", 65536),
            "externalPythonDependencies": "not-attested"}


def inputs(native_directory, native_receipt, builds, releases, cutoff):
    binaries, native = native_inputs.native(native_directory, native_receipt)
    compiled = native_inputs.compiler(builds, deadline=cutoff)
    return binaries, {"native": native, "compiler": compiled,
        "signed": native_inputs.signed(releases, compiled, deadline=cutoff),
        "conductor": sources()}


def _release_records(client, publications):
    return {name: digest(client.call("release", "get", "--publication", publication)["data"])
            for name, publication in publications.items()}


def _absent_policies(client, program):
    observed = []
    for row in program["initial"]:
        reply = client.call("policy", "--kind", row["kind"], "get", "--id", row["id"], codes=(0, 6))
        require(reply["category"] == "not-found" and reply["outcomeKnown"] is True,
                "java-diagnostic-current-policy-absence-required")
        observed.append({"kind": row["kind"], "id": row["id"], "responseDigest": digest(reply["data"])})
    return observed


def private_store(work, cutoff, evidence=None):
    """Capture every path in the stopped node's protected data root.

    The maintained container storage scanner owns descriptor-anchored traversal,
    content hashes and complete hardlink-group validation. No store bytes are
    copied into the candidate; the full bounded inventory stays in local evidence.
    """
    require(sys.platform == "linux" and os.geteuid() > 0, "java-diagnostic-private-store-linux-owner")
    from tools.container_runtime import storage

    owner = (os.geteuid(), os.getegid())
    before = storage.scan(work, cutoff, roots=("data",), owner=owner, retain_identity=True)
    require(before["data"]["kind"] == "directory" and before["data"]["mode"] & 0o077 == 0,
            "java-diagnostic-private-store-protected-root")
    require(storage.scan(work, cutoff, roots=("data",), owner=owner, retain_identity=True) == before,
            "java-diagnostic-private-store-changed")
    captured = json.dumps(before, sort_keys=True, separators=(",", ":")).encode("utf-8")
    require(len(captured) <= 4 * 1024 * 1024, "java-diagnostic-private-store-inventory-bound")
    receipt = {"sha256": "sha256:" + hashlib.sha256(captured).hexdigest(), "bytes": len(captured),
               "entries": len(before), "files": sum(row["kind"] == "file" for row in before.values()),
               "ownerUid": owner[0], "ownerGid": owner[1], "root": "data"}
    if evidence is not None:
        inventory = evidence / "private-store-capture.json"
        with inventory.open("xb") as stream:
            stream.write(captured)
        inventory.chmod(0o400)
        require(file_identity(inventory, 4 * 1024 * 1024) ==
                {"sha256": receipt["sha256"], "bytes": receipt["bytes"]},
                "java-diagnostic-private-store-inventory-changed")
    return receipt


@contextmanager
def session(binary, cli, work, config, output, original_clock, *, ordinal):
    output.mkdir(mode=0o700)
    with owned_cancellation() as cancellation:
        client = RecordingClient(cli, work, cancellation, deadline(original_clock),
                                 evidence=output / "controls", invocation_timeout_millis=120000)
        node = None
        record = {"cleanPhysicalRetirement": False}
        try:
            node = connect(client, binary, work, config, TENANT, ordinal)
            yield client, node, record
            idle(client)
            stop(client, node)
            closed = stopped_record(node)
            provider_timeout.verify_shutdown(closed)
            capture = private_store(work, deadline(original_clock), output)
            record.update(cleanPhysicalRetirement=True, shutdown=closed, privateStoreCapture=capture)
        finally:
            if node is not None:
                client.node = None
                node.close()
                (output / "node.stderr.log").write_bytes(bytes(node.buffers[1]))
            write_json(output / "physical-retirement.json", record)


def _write_proposals(output, program):
    output.mkdir(mode=0o700)
    reviewed = policy_proposals.reviewed(program)
    for group in ("initial", "revisions"):
        for index, row in enumerate(reviewed[group]):
            path = output / f"{group}-{index:02}-{row['id']}.json"
            with path.open("xb") as stream:
                stream.write(policy_proposals.review_bytes(row["document"]))
            path.chmod(0o400)
    return reviewed


def prepare(native_directory, native_receipt, builds, releases, output, *, former_child=True):
    require(type(former_child) is bool, "java-diagnostic-former-selection")
    output = fresh(output)
    result = {"schemaVersion": SCHEMA, "status": "in-progress", "clock": None, "inputs": None,
        "applicationCapabilityPolicyMutations": 0, "guestInvocations": 0, "providerRequests": 0,
        "liveNodeBound": 1, "acceptedExternalMutationDisposition": "unknown", "cases": {}}
    peer = None
    try:
        original = clock()
        result["clock"] = original
        binaries, material = inputs(native_directory, native_receipt, builds, releases, deadline(original))
        result["inputs"] = material
        with owned_cancellation() as cancellation:
            peer_root = fresh(output / "prepare-peer")
            owner = RecordingClient(binaries["latent"], peer_root, cancellation, deadline(original),
                                    evidence=peer_root / "controls", invocation_timeout_millis=120000)
            peer, port = start_provider(owner, peer_root, maximum_seconds=1200)
            result["recipientPort"] = port
            for name in (("former", "current") if former_child else ("current",)):
                work = fresh(output / (name + "-node"))
                config, host = configure(work, releases, http=name == "current", former_profile=name == "former")
                selected = provider_timeout.configure(config.parent, read_json(config), port)
                require(selected["cells"][0]["queueCapacity"] == 4, "java-diagnostic-original-queue")
                selected["cells"][0]["queueCapacity"] = resource_diagnostics.QUEUE_SIZE
                require(selected["retention"]["terminalTtlMillis"] == history_diagnostics.RETENTION_MILLIS,
                        "java-diagnostic-original-retention")
                replace_config(config, selected)
                with session(binaries["latentd"], binaries["latent"], work, config, output / (name + "-prepare"),
                             original, ordinal=1) as (client, node, physical):
                    publications = publish(client, releases)
                    program = policy_proposals.program(node.startup_record, publications, port)
                    if name == "former":
                        program["revisions"], program["revisionCount"] = [], 0
                    prepared = _write_proposals(output / (name + "-policies"), program)
                    result["cases"][name] = {"configSha256": file_identity(config, 262144), "host": host,
                        "configFile": config.relative_to(work).as_posix(),
                        "publications": publications, "releaseRecords": _release_records(client, publications),
                        "startupProviders": node.startup_record["providers"], "policies": prepared,
                        "policyAbsence": _absent_policies(client, program),
                        "physical": physical}
            result["peerShutdown"] = provider_timeout.stop_unused_peer(peer)
            peer = None
        require(material == inputs(native_directory, native_receipt, builds, releases, deadline(original))[1],
                "java-diagnostic-prepare-inputs-changed")
        result.update(status="prepared", initialApplications=sum(row["policies"]["initialCount"]
                      for row in result["cases"].values()), revisionApplications=4,
                      independentPolicyApprovalRequired=True, qualificationPassed=False)
        write_json(output / "candidate.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        if peer is not None:
            result["peerFailureCleanup"] = close_failed_provider(peer)
        write_json(output / "PREPARE-FAILED.json", result)
        raise


def _review(candidate, approved_sha256):
    require(isinstance(approved_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", approved_sha256),
            "java-diagnostic-explicit-approved-candidate-hash")
    require(file_identity(candidate, 262144)["sha256"] == "sha256:" + approved_sha256,
            "java-diagnostic-approved-candidate-changed")
    value = read_json(candidate)
    require(value["schemaVersion"] == SCHEMA and value["status"] == "prepared"
            and all(type(value[key]) is int and value[key] == 0 for key in (
                "applicationCapabilityPolicyMutations", "guestInvocations", "providerRequests"))
            and value["independentPolicyApprovalRequired"] is True
            and set(value["cases"]) in ({"current"}, {"current", "former"})
            and all(row["physical"]["cleanPhysicalRetirement"] is True for row in value["cases"].values()),
            "java-diagnostic-original-preparation-required")
    for name, prepared in value["cases"].items():
        capture = prepared["physical"].get("privateStoreCapture")
        require(isinstance(capture, dict) and capture.get("root") == "data"
                and type(capture.get("entries")) is int and capture["entries"] >= 1
                and type(capture.get("files")) is int and capture["files"] >= 0
                and type(capture.get("ownerUid")) is int and capture["ownerUid"] > 0
                and type(capture.get("ownerGid")) is int and capture["ownerGid"] > 0
                and type(capture.get("bytes")) is int and 0 < capture["bytes"] <= 4 * 1024 * 1024
                and isinstance(capture.get("sha256"), str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", capture["sha256"]),
                "java-diagnostic-original-private-store-capture-required")
        inventory = candidate.parent / (name + "-prepare") / "private-store-capture.json"
        require(file_identity(inventory, 4 * 1024 * 1024) ==
                {"sha256": capture["sha256"], "bytes": capture["bytes"]},
                "java-diagnostic-original-private-store-inventory-changed")
    return value


def _admit(client, node, releases, prepared, port, *, service_required):
    require(node.startup_record["providers"] == prepared["startupProviders"], "java-diagnostic-native-profile-drift")
    publications = prepared["publications"]
    require(_release_records(client, publications) == prepared["releaseRecords"], "java-diagnostic-original-release-drift")
    program = policy_proposals.program(node.startup_record, publications, port)
    if not prepared["policies"]["revisions"]:
        program["revisions"], program["revisionCount"] = [], 0
    require(policy_proposals.reviewed(program) == prepared["policies"], "java-diagnostic-reviewed-policy-drift")
    require(_absent_policies(client, program) == prepared["policyAbsence"], "java-diagnostic-current-policy-drift")
    extra = provider_timeout.grant(client, node, publications["domain"], port)
    targets = grant(client, node, releases, publications, domain_grants=(extra,))
    if not service_required:
        return targets, None
    generation = service_grant(client, node, publications)
    targets["adapter"] = deploy(client, releases / "java-http-adapter/deployment.json", publications["adapter"],
        generation=str(targets["adapter"]["generation"]), grants=targets["adapter"]["grants"] + [
            {"capability": SERVICE_CAPABILITY, "policy": "java-domain-allow"}])
    return targets, generation


def _former(client, targets, host):
    activation = "java-diagnostic-former-parent"
    original = invoke(client, targets, "adapter", "handle", web_request(host), activation, codes=(0, 4))
    tree = context.tree(client, activation)
    nodes = tree["nodes"]
    require(len(nodes) == 2, "java-diagnostic-former-real-child-required")
    child = next(row for row in nodes if row["parentActivationId"] == activation)
    reason = child["diagnostic"]
    require(child["rootActivationId"] == activation and child["diagnosticIsTerminal"] is True
            and reason is not None and reason["stage"] == 3 and reason["reason"] == 1,
            "java-diagnostic-former-child-preparation-required")
    bound, required, fixed, fuel, multiplier = (int(reason[key]) for key in (
        "configuredBound", "calculatedRequirement", "fixedBytes", "liftingFuel", "liftMultiplier"))
    require(bound == 67108864 and fuel == 2097152 and required == fixed + fuel * multiplier and required > bound
            and reason["profileDigest"] and "activation.diagnostic.v1" not in json.dumps(original),
            "java-diagnostic-former-child-safe-exact-proof")
    return {"status": "passed", "originalResponse": original, "authorizedTree": tree,
            "externalMutationDisposition": "unknown"}


def _current(client, node, targets, prepared, releases, host, port, peer_root, output, generation):
    publications = prepared["publications"]
    route(client, host, publications["adapter"])
    missing = context.capture_http(client, host, expected=(403,))
    require(missing["tree"] is not None and any(row["diagnostic"] is not None
            and row["diagnostic"]["stage"] == 4 and row["diagnostic"]["reason"] in (7, 8)
            for row in missing["tree"]["nodes"]), "java-diagnostic-original-missing-grant-reason")
    require(generation is None, "java-diagnostic-original-service-admission-order")
    generation = service_grant(client, node, publications)
    targets["adapter"] = deploy(client, releases / "java-http-adapter/deployment.json", publications["adapter"],
        generation=str(targets["adapter"]["generation"]), grants=targets["adapter"]["grants"] + [
            {"capability": SERVICE_CAPABILITY, "policy": "java-domain-allow"}])
    route(client, host, publications["adapter"])
    result = {"initialMissingGrant": missing,
        "directAndComposedSuccess": fresh_status(client, targets, host, "java-diagnostic-direct-success"),
        "targetAuthority": inspection.authority(client),
        "context": context.qualify(client, targets, releases, publications, host, output)}
    result["guestFuel"] = resource_diagnostics.fuel(client, targets, host)
    result["queuePressure"] = resource_diagnostics.queue(client, targets, host)
    result["providerTimeout"] = provider_timeout.qualify(client, host, peer_root, port)
    require(all(result[name]["status"] == "passed" for name in ("guestFuel", "queuePressure", "providerTimeout")),
            "java-diagnostic-resource-observation-unavailable")
    from tools.static_api.node import policy
    empty = {"formatVersion": 1, "tenant": TENANT, "rules": []}
    generation = policy(client, "policy", "java-domain-allow", empty, generation)["generation"]
    result["missingGrant"] = context.capture_http(client, host, expected=(403, 409, 503))
    service_grant(client, node, publications, generation=generation)
    result["explicitRebinding"] = rebind(client, targets, releases, publications)
    route(client, host, publications["adapter"])
    result["freshAfterRestoration"] = fresh_status(client, targets, host, "java-diagnostic-after-restoration")
    result["history"] = history_diagnostics.qualify(client, host, output / "history")
    result["status"] = "passed"
    return result


def execute(native_directory, native_receipt, builds, releases, output, *, approved_sha256):
    candidate = _review(output / "candidate.json", approved_sha256)
    cutoff = deadline(candidate["clock"])
    binaries, material = inputs(native_directory, native_receipt, builds, releases, cutoff)
    require(material == candidate["inputs"], "java-diagnostic-reviewed-input-drift")
    result = {"schemaVersion": "latent.java-preparation-diagnostics.execution.v1", "status": "in-progress",
        "approvedCandidateSha256": approved_sha256, "inputs": material, "cases": {},
        "packagedDistributionQualified": False, "allAcceptanceCriteriaPassed": False}
    peer = None
    try:
        with owned_cancellation() as cancellation:
            peer_root = fresh(output / "execute-peer")
            owner = RecordingClient(binaries["latent"], peer_root, cancellation, cutoff, evidence=peer_root / "controls",
                                    invocation_timeout_millis=120000)
            peer, port = start_provider(owner, peer_root, maximum_seconds=1200, port=candidate["recipientPort"])
            for name in (("former", "current") if "former" in candidate["cases"] else ("current",)):
                prepared = candidate["cases"][name]
                work = output / (name + "-node")
                require(prepared["configFile"] == "node.json", "java-diagnostic-original-config-name")
                config = work / prepared["configFile"]
                require(file_identity(config, 262144) == prepared["configSha256"], "java-diagnostic-retained-config-drift")
                require(private_store(work, cutoff) == prepared["physical"]["privateStoreCapture"],
                        "java-diagnostic-retained-private-store-drift")
                observed_output = output / (name + "-execute")
                with session(binaries["latentd"], binaries["latent"], work, config, observed_output,
                             candidate["clock"], ordinal=2) as (client, node, physical):
                    targets, generation = _admit(client, node, releases, prepared, port, service_required=name == "former")
                    host = prepared["host"] or candidate["cases"]["current"]["host"]
                    observed = _former(client, targets, host) if name == "former" else _current(
                        client, node, targets, prepared, releases, host, port, peer_root, observed_output, generation)
                    result["cases"][name] = {"observations": observed, "physical": physical}
            result["peerShutdown"] = provider_timeout.stop_peer(peer)
            peer = None
        require(material == inputs(native_directory, native_receipt, builds, releases, deadline(candidate["clock"]))[1],
                "java-diagnostic-executed-inputs-changed")
        result.update(status="passed", runtimeScenarioProgramPassed="former" in result["cases"],
                      allAcceptanceCriteriaPassed=False)
        write_json(output / "execution.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        if peer is not None:
            result["peerFailureCleanup"] = close_failed_provider(peer)
        write_json(output / "EXECUTION-FAILED.json", result)
        raise

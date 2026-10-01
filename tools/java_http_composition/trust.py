"""Actual verifier and admission evidence for independently signed Java builds.

Python constructs bounded test permutations. The Rust policy constructors alone
produce canonical bytes and digests; no application ordering rule is reproduced.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_http_composition.node import TENANT, configure
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, inventory
from tools.run_security_profile_workflow import replace_config
from tools.rust_capsule_node import RecordingClient
from tools.rust_capsule_project import ROOT, fresh, snapshot
from tools.run_rust_capsule_workflow import write_workflow_receipt


class Verifier:
    def __init__(self, executable: Path, output: Path):
        self.executable, self.output = executable, fresh(output)
        self.environment = build_environment(output)
        self.calls = 0
        self.retained = 0
        self.deadline = time.monotonic() + 600

    def call(self, name, *arguments, accepted=True):
        require(self.calls < 64 and time.monotonic() < self.deadline, "java-paired-verifier-work-bound")
        self.calls += 1
        result = run_bounded_result([str(self.executable), "--output", "json", "--tenant", TENANT,
            *map(str, arguments)], cwd=ROOT, env=self.environment,
            timeout_seconds=min(30, self.deadline - time.monotonic()), max_output_bytes=262144)
        self.retained += len(result.stdout) + len(result.stderr)
        require(self.retained <= 4 * 1024 * 1024, "java-paired-verifier-retention")
        stem = f"{self.calls:02d}-{name}"
        for stream in ("stdout", "stderr"):
            with (self.output / (stem + "." + stream + ".log")).open("xb") as file:
                file.write(getattr(result, stream))
        response = json.loads(result.stdout)
        require(response["schemaVersion"] == "latent.cli.result.v1" and response["outcomeKnown"],
            "java-paired-verifier-result")
        require((result.returncode == 0) == accepted and
            (response["category"] == "success") == accepted, "java-paired-verifier-unexpected-outcome")
        write_json(self.output / (stem + ".json"), response)
        return response

    def canonical(self, name, policy):
        directory = fresh(self.output / name)
        for role in ("publisher", "builder"):
            write_json(directory / (role + ".json"), policy[role])
        result = self.call(name, "package", "canonical-policy", "--publisher-policy", directory / "publisher.json",
            "--builder-policy", directory / "builder.json")["data"]
        require(result["schemaVersion"] == "latent.signing.canonical-policy.v1"
            and not any(result[field] for field in ("trustEstablished", "evidenceCreated", "executionAuthorized")),
            "java-paired-canonical-is-not-authority")
        return {role: result[role] for role in ("publisher", "builder")}

    def verify(self, name, source, policy, *, accepted=True):
        return self.call(name, "package", "verify", source / "package", "--evidence-index",
            source / "evidence/index.json", "--evidence-root", source / "evidence", "--policy", policy,
            accepted=accepted)


def reversed_properties(value):
    if isinstance(value, dict):
        return {key: reversed_properties(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reversed_properties(item) for item in value]
    return value


def copy_artifact(source, destination):
    files = snapshot(source)
    require(len(files) <= 4096 and sum(map(len, files.values())) <= 32 * 1024 * 1024,
        "java-paired-negative-copy-bound")
    destination = fresh(destination)
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as file:
            file.write(data)
        target.chmod(0o600)
    require(snapshot(source) == files, "java-paired-original-artifact-changed")
    return destination


def admission(binaries, releases, output, cases):
    observations = {}
    for name, source, policy in cases:
        evidence = fresh(output / name)
        with owned_cancellation() as cancellation_owner:
            with tempfile.TemporaryDirectory(prefix="lsf-java-paired-admission-") as temporary:
                work = Path(temporary)
                (work / "node").mkdir(mode=0o700)
                (work / "client").mkdir(mode=0o700)
                client = RecordingClient(binaries["latent"], work / "client", cancellation_owner,
                    time.monotonic() + 90, evidence=evidence / "controls")
                config, _ = configure(work / "node", releases, http=False)
                override = work / "node/policy-override.json"
                write_json(override, read_json(policy))
                settings = read_json(config)
                settings["supplyChain"]["policyFile"] = override.name
                replace_config(config, settings)
                node = None
                record = {"schemaVersion": "latent.java-paired.admission.v1", "status": "in-progress", "case": name}
                try:
                    node = connect(client, binaries["latentd"], work / "node", config, TENANT, 1)
                    operation = "paired-negative-" + name
                    response = client.call("release", "publish-package", source / "package", "--evidence",
                        source / "evidence/index.json", "--operation-id", operation, "--expected-generation", 0,
                        codes=(2, 4))
                    require(response["outcomeKnown"] and response["category"] != "success",
                        "java-paired-invalid-admission-accepted")
                    record["admission"] = response
                    # The original operation is read once. No publication replay,
                    # changed precondition or replacement operation is attempted.
                    if response["requestDispatched"]:
                        recovered = client.call("release", "operation", operation)["data"]
                        require(recovered["receipt"] is not None and
                            recovered["receipt"]["operationId"] == operation and
                            recovered["receipt"]["disposition"].endswith("REJECTED") and
                            recovered["receipt"]["publication"] is None,
                            "java-paired-rejected-original-operation-recovery")
                        record["originalOperation"] = recovered
                    record["catalog"] = client.call("release", "list")["data"]
                    require(not record["catalog"]["releases"], "java-paired-negative-created-publication")
                    stop(client, node)
                    record.update(status="passed", nodeStopped=node.owner.finished)
                except BaseException as error:
                    record.update(status="failed", reason=str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__)
                    raise
                finally:
                    if node is not None:
                        client.node = None
                        node.close()
                        with (evidence / "node.stderr.log").open("xb") as file:
                            file.write(bytes(node.buffers[1]))
                    write_workflow_receipt(evidence / "admission.json", record)
                observations[name] = record
    return observations


def qualify(binaries, releases, output):
    output = fresh(output)
    before = inventory(releases, maximum_bytes=128 * 1024 * 1024)
    policy = read_json(releases / "policy.json")
    release_set = read_json(releases / "release-set.json")
    pair = [next(row for row in release_set["releases"] if row["name"] == "java-http-" + name)
        for name in ("domain", "adapter")]
    for field in ("componentDigest", "packageDigest", "sourceSnapshotDigest", "builderId", "builderKeyFingerprint"):
        require(pair[0][field] != pair[1][field], "java-paired-independent-" + field)
    for row in pair:
        matching = [entry for entry in policy["builder"]["requirements"] if entry["builderId"] == row["builderId"]]
        require(len(matching) == 1 and matching[0]["sourceSnapshotDigest"] == row["sourceSnapshotDigest"]
            and matching[0]["buildType"] == row["buildType"] and not matching[0]["requireReproducible"],
            "java-paired-exact-source-authority")
    verifier = Verifier(binaries["latent"], output / "verifier")
    canonical = verifier.canonical("approved", policy)
    for role in ("publisher", "builder"):
        require(canonical[role]["policyDigest"] == policy[role + "Revocations"]["policyDigest"],
            "java-paired-approved-revocation-digest")
    result = {"schemaVersion": "latent.java-paired.qualification.v1", "status": "in-progress",
        "trust": "isolated-short-lived-demo-only", "pair": pair, "canonical": canonical, "permutations": [], "negatives": {}}
    try:
        variants = [copy.deepcopy(policy), reversed_properties(policy), copy.deepcopy(policy)]
        variants[2]["publisher"]["keys"].reverse()
        variants[2]["builder"]["keys"].reverse()
        variants[2]["builder"]["requirements"].reverse()
        for ordinal, variant in enumerate(variants):
            name = f"permutation-{ordinal}"
            observed = verifier.canonical(name, variant)
            require(observed == canonical, "java-paired-canonical-permutation-drift")
            path = output / (name + ".json")
            write_json(path, variant)
            verification = {row["name"]: verifier.verify(name + "-" + row["name"], releases / row["name"], path)
                for row in pair}
            result["permutations"].append({"canonical": observed, "verification": verification})
        negatives = []
        source = releases / pair[0]["name"]
        for name in ("altered-component", "altered-policy", "noncanonical-revocation-digest",
                     "wrong-builder-source", "wrong-builder-key", "missing-provenance",
                     "revoked-builder-key", "revoked-builder", "stale-trust"):
            directory = fresh(output / name)
            changed = copy.deepcopy(policy)
            artifact = source
            if name in ("altered-component", "missing-provenance"):
                artifact = copy_artifact(source, directory / "artifact")
                if name == "altered-component":
                    component = artifact / "package/layers/component.wasm"
                    data = bytearray(component.read_bytes())
                    require(bool(data), "java-paired-component-copy-empty")
                    data[-1] ^= 1
                    component.write_bytes(data)
                else:
                    index = artifact / "evidence/index.json"
                    value = read_json(index)
                    value["provenance"] = []
                    index.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
            elif name == "altered-policy":
                changed["builder"]["generation"] += 1
            elif name == "noncanonical-revocation-digest":
                changed["builder"]["keys"].reverse()
                observed = verifier.canonical(name + "-inputs", changed)
                supplied = file_identity(verifier.output / (name + "-inputs") / "builder.json")["sha256"]
                require(supplied != observed["builder"]["policyDigest"], "java-paired-noncanonical-mistake-not-distinct")
                changed["builderRevocations"]["policyDigest"] = supplied
                result["formerConstructionMistake"] = {"role": "builder",
                    "reason": "revocation-policy-digest-mismatch",
                    "authoritativePolicyDigest": observed["builder"]["policyDigest"],
                    "suppliedRawInputDigest": supplied, "trustCorrected": False}
            elif name == "wrong-builder-source":
                requirements = changed["builder"]["requirements"]
                selected = [next(entry for entry in requirements if entry["builderId"] == row["builderId"]) for row in pair]
                selected[0]["builderId"], selected[1]["builderId"] = selected[1]["builderId"], selected[0]["builderId"]
            elif name == "wrong-builder-key":
                keys = changed["builder"]["keys"]
                selected = [next(entry for entry in keys if entry["builderId"] == row["builderId"]) for row in pair]
                selected[0]["publicKey"], selected[1]["publicKey"] = selected[1]["publicKey"], selected[0]["publicKey"]
            elif name == "revoked-builder-key":
                changed["builderRevocations"]["revokedKeys"].append(pair[0]["builderKeyFingerprint"])
            elif name == "revoked-builder":
                changed["builderRevocations"]["revokedBuilders"].append(pair[0]["builderId"])
            elif name == "stale-trust":
                changed["builderRevocations"]["validUntil"] = int(time.time()) - 1
            if name in ("wrong-builder-source", "wrong-builder-key"):
                changed["builderRevocations"]["policyDigest"] = verifier.canonical(name + "-test-policy", changed)["builder"]["policyDigest"]
            path = directory / "policy.json"
            write_json(path, changed)
            result["negatives"][name] = verifier.verify(name, artifact, path, accepted=False)
            # Digest/expiry failures remain verifier rejections before startup.
            # Valid policy negatives exercise the real node admission boundary.
            if name not in ("altered-policy", "noncanonical-revocation-digest", "stale-trust"):
                negatives.append((name, artifact, path))
        changed = copy.deepcopy(policy)
        changed["builder"]["maxProofAgeSeconds"] = 2
        changed["builderRevocations"]["policyDigest"] = verifier.canonical("stale-proof-policy", changed)["builder"]["policyDigest"]
        stale_policy = output / "stale-proof-policy.json"
        write_json(stale_policy, changed)
        freshness = run_bounded_result([str(binaries["examples/capsule_authoring"]), "demo-check-stale-proofs",
            str(output / "stale-proof"), str(stale_policy), *(str(releases / row["name"]) for row in pair)],
            cwd=ROOT, env=build_environment(output), timeout_seconds=20, max_output_bytes=8192)
        for stream in ("stdout", "stderr"):
            with (output / ("stale-proof." + stream + ".log")).open("xb") as file:
                file.write(getattr(freshness, stream))
        require(freshness.returncode == 0, "java-paired-actual-stale-proof-checkpoint")
        result["staleProofs"] = read_json(output / "stale-proof/stale-proofs.json")
        require(result["staleProofs"]["status"] == "passed" and len(result["staleProofs"]["proofs"]) == 2,
            "java-paired-both-original-grants-fenced")
        result["admission"] = admission(binaries, releases, fresh(output / "admission"), negatives)
        require(before == inventory(releases, maximum_bytes=128 * 1024 * 1024), "java-paired-approved-inputs-changed")
        result["status"] = "passed"
        return result
    except BaseException as error:
        result.update(status="failed", reason=str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__)
        raise
    finally:
        write_workflow_receipt(output / "paired-trust.json", result)

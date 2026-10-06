"""Select actual admitted app publications through the existing operator APIs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import base64
import json
from pathlib import Path
import re

from tools.dev_workflow.transaction_binding import validate
from tools.phase2_operator_process import require, write_json
from tools.phase2_operator_scenario import receipt
from tools.stateful_reference_deployment import derive

WORLD = "examples:order-draft/service@1.0.0"
BUILD_TYPES = {language: "https://latent.dev/build/" + name + "/v1" for language, name in (
    ("rust", "rust-capsule"), ("c", "c-guest"), ("typescript", "typescript-capsule"),
    ("go", "go-capsule"), ("java", "java-capsule"), ("dotnet", "dotnet-capsule"))}


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def regular(directory: Path, name: str, maximum: int) -> bytes:
    require(directory.is_dir() and not directory.is_symlink(), "app-build-root-required")
    path = directory / name
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()),
            "app-build-regular-owned-input")
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    require(len(data) <= maximum, "app-build-input-byte-limit")
    return data


def decode(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate-app-build-field")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite-app-build-field")))
    require(isinstance(value, dict), "app-build-object-required")
    return value


@dataclass(frozen=True)
class Backend:
    language: str
    entity: str
    directory: Path
    publication: str
    component_digest: str
    compiler_inputs_digest: str
    source_snapshot_digest: str
    host_abi_digest: str
    companion: bytes
    deployment: dict

    @classmethod
    def read(cls, language: str, entity: str, directory: Path, publication: str) -> "Backend":
        require(language in BUILD_TYPES and entity in ("alice", "bob"), "finite-app-backend-selection")
        require(isinstance(publication, str) and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", publication),
                "actual-app-publication-required")
        complete = decode(regular(directory, "BUILD-COMPLETE.json", 1_048_576))
        observation_raw = regular(directory, "build-observation.json", 262_144)
        observation = decode(observation_raw)
        source = regular(directory, "source-inputs.json", 4 * 1024 * 1024)
        component = regular(directory, "component.wasm", 32 * 1024 * 1024)
        manifest = decode(regular(directory, "capsule.json", 262_144))
        deployment = decode(regular(directory, "deployment.json", 262_144))
        companion = regular(directory, "transaction-binding.json", 128 * 1024)
        require(complete.get("formatVersion") == 1 and complete.get("packageAssembled") is True,
                "ordinary-assembled-app-build-required")
        require(observation.get("formatVersion") == 1 and observation.get("buildType") == BUILD_TYPES[language]
                and complete.get("observationDigest") == digest(observation_raw)
                and complete.get("sourceDigest") == digest(source) == observation.get("source", {}).get("snapshotDigest"),
                "actual-app-compiler-and-source-identity")
        require(component.startswith(b"\0asm\x0d\0\x01\0") and 0 < len(component) <= 32 * 1024 * 1024
                and digest(component) == complete.get("componentDigest") == observation.get("componentDigest")
                == manifest.get("component", {}).get("digest") == deployment.get("spec", {}).get("release")
                and manifest["component"].get("world") == WORLD
                and observation.get("componentSize") == len(component), "actual-app-component-identity")
        require(manifest.get("metadata", {}).get("tenant") == "examples"
                and deployment.get("metadata", {}).get("tenant") == "examples", "app-component-tenant")
        declaration = decode(companion)
        declaration = validate(companion, capsule=manifest["metadata"]["name"],
                               deployment=deployment["metadata"]["name"], binding=declaration.get("binding"))
        require(declaration["namespace"] == "order-drafts-" + entity, "app-component-entity-namespace")
        profile = declaration["hostAbiDigest"]
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", profile), "app-component-host-identity")
        materials = observation.get("materials")
        parameters = observation.get("parameters")
        require(isinstance(materials, list) and 0 < len(materials) <= 256 and isinstance(parameters, dict),
                "actual-app-compiler-materials-required")
        # This is explicitly derived from the ordinary compiler's recorded
        # material/parameter bytes. It is not a claim of another tool execution.
        compiler_inputs = json.dumps({"materials": materials, "parameters": parameters},
                                    sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return cls(language, entity, directory, publication, digest(component), digest(compiler_inputs),
                   digest(source), profile, companion, deployment)

    def observation(self) -> dict:
        return {"language": self.language, "entity": self.entity, "publication": self.publication,
                "componentDigest": self.component_digest, "compilerInputsDigest": self.compiler_inputs_digest,
                "compilerIdentityKind": "ordinary-build-recorded-materials-and-parameters",
                "sourceSnapshotDigest": self.source_snapshot_digest, "hostAbiDigest": self.host_abi_digest,
                "companionDigest": digest(self.companion)}


def select(client, backend: Backend, *, result_policy: str, state_policies: list[str], grants: list[dict],
           install_triggers: bool = True) -> dict:
    """One explicit deployment mutation and bounded trigger CAS, without retry."""
    require(type(install_triggers) is bool, "explicit-app-trigger-switch")
    release = client.call("release", "get", "--publication", backend.publication)["data"]["release"]
    require(isinstance(release, dict) and release["publication"]["id"] == backend.publication
            and release["publication"]["tenant"] == "examples" and release["digest"] == backend.component_digest
            and release.get("admitted") is True and release.get("world") == WORLD
            and release.get("service") == decode(backend.companion)["capsule"]
            and isinstance(release.get("packageDigest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", release["packageDigest"]), "actual-admitted-app-publication")
    manifest = json.loads(json.dumps(backend.deployment))
    manifest["spec"]["publication"] = backend.publication
    require(isinstance(grants, list) and 2 <= len(grants) <= 16
            and all(isinstance(row, dict) and set(row) == {"capability", "policy"}
                    and isinstance(row["capability"], str) and isinstance(row["policy"], str)
                    and re.fullmatch(r"[a-z][a-z0-9-]{0,127}", row["policy"]) for row in grants)
            and len({row["capability"] for row in grants}) == len(grants)
            and {"latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"}
                <= {row["capability"] for row in grants}, "explicit-app-state-and-intent-policy-grants")
    manifest["spec"]["grants"] = [dict(row) for row in grants]
    name = manifest["metadata"]["name"]
    prior = client.call("deployment", "get", name, "--operation-snapshot", codes=(0, 6))["data"]
    path = client.directory / f"app-deployment-{client.calls}.json"
    write_json(path, manifest)
    operation = f"app-deploy-{client.calls}"
    changed = client.call("--rpc-timeout-ms", "300000", "deployment", "apply", path,
                          "--operation-id", operation, "--expected-generation",
                          prior["deployment"]["generation"] if prior.get("deployment") else "0",
                          "--expected-state-version", prior["stateVersion"], timeout=310)
    receipt(changed, operation)
    deployed = client.call("deployment", "get", name)["data"]["deployment"]
    require(deployed["publication"]["id"] == backend.publication and deployed["manifest"]["spec"]["release"]
            == backend.component_digest, "selected-app-deployment-identity")
    routes = client.call("route", "get")["data"]["snapshot"]["services"]
    selected = [row for row in routes if row["routeId"] == name]
    require(len(selected) == 1 and len(selected[0]["revisions"]) == 1, "one-selected-app-revision")
    published = {"componentDigest": backend.component_digest, "publication": backend.publication,
                 "revision": selected[0]["revisions"][0]["revisionId"],
                 "deploymentGeneration": int(deployed["generation"]), "companionDigest": digest(backend.companion)}
    inputs = derive(backend.companion, published, entity=backend.entity, incarnation="1",
                    result_policy=result_policy, state_policies=state_policies)
    mutations = []
    for trigger in inputs["triggers"] if install_triggers else []:
        trigger_name = trigger["metadata"]["name"]
        previous = client.call("trigger", "get", trigger_name, codes=(0, 6))["data"]
        source = client.directory / f"app-trigger-{client.calls}.json"
        write_json(source, trigger)
        operation = f"app-trigger-{client.calls}"
        result = client.call("trigger", "apply", source, "--operation-id", operation,
                             "--expected-generation", previous["trigger"]["generation"] if previous["trigger"] else "0",
                             "--expected-state-version", previous["stateVersion"])
        mutations.append(receipt(result, operation))
    return {"backend": backend.observation(), "published": published, "deployment": deployed,
            "triggerReceipts": mutations, "nodeSelectionObserved": True, "httpTriggersSelected": install_triggers,
            "browserQualified": False}


def attest_originals(client, backend: Backend, browser: dict) -> list[dict]:
    """Use the current Alice client profile for real original-command lookup."""
    require(backend.entity == "alice" and browser.get("language") == backend.language,
            "original-browser-backend-association")
    records = []
    for key, expected in (("lostCommit", "COMMAND_OUTCOME_COMMITTED"),
                          ("lostRejection", "COMMAND_OUTCOME_REJECTED")):
        observed = browser[key]
        require(isinstance(observed, dict) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", observed["clientKey"]),
                "original-browser-client-key")
        actual = client.call("transaction", "lookup", "--namespace", "order-drafts-alice",
                             "--incarnation", "1", "--authorization-publication", backend.publication,
                             "--operation", "edit", "--entity", "alice",
                             "--client-key", observed["clientKey"])["data"]["command"]
        require(isinstance(actual, dict) and actual["commandId"] == observed["commandId"]
                and actual["metadataDurable"] is True and actual["outcome"] == expected
                and actual["applicationStateCommitted"] is (key == "lostCommit")
                and actual["source"]["publicationId"] == backend.publication
                and actual["source"]["componentDigest"] == backend.component_digest
                and actual["source"]["stateSchema"] == decode(backend.companion)["stateSchema"]
                and actual["key"]["entity"] == "alice"
                and actual["key"]["clientKey"] == observed["clientKey"], "actual-original-app-command")
        retained = actual["retainedResult"]
        require(retained["kind"] == ("success" if key == "lostCommit" else "business-rejection")
                and retained["value"]["payload"]["encoding"] == "base64", "actual-original-app-result")
        encoded = retained["value"]["payload"]["data"]
        body = base64.b64decode(encoded, validate=True)
        require(base64.b64encode(body).decode() == encoded and len(body) <= 192 * 1024
                and digest(body) == observed["resultDigest"], "original-app-result-byte-identity")
        effects = observed["effectIds"]
        require(isinstance(effects, list) and len(effects) == (2 if key == "lostCommit" else 0),
                "original-app-effect-count")
        if key == "lostCommit":
            require(actual["commit"]["effectIds"] == effects, "original-app-atomic-effect-set")
        effect_records = []
        for effect_id in effects:
            require(isinstance(effect_id, str) and re.fullmatch(r"[0-9a-f]{64}", effect_id), "original-app-effect-id")
            effect = client.call("transaction", "effect", "--namespace", "order-drafts-alice",
                                 "--incarnation", "1", "--authorization-publication", backend.publication,
                                 "--operation", "edit", "--entity", "alice", "--client-key", observed["clientKey"],
                                 "--effect-id", effect_id)["data"]["effect"]
            require(effect["effectId"] == effect_id and effect["commandId"] == actual["commandId"]
                    and effect["commandAttemptId"] == actual["attemptId"], "actual-original-app-effect-link")
            effect_records.append(effect)
        records.append({"command": actual, "effects": effect_records, "browserResultDigest": observed["resultDigest"]})
    return records

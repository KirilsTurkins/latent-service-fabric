"""Authenticate supplied standalone native/build bytes without rebuilding them."""
from pathlib import Path
import re

from tools.phase2_operator_process import read_json, require
from tools.phase3_resource_identity import file_identity, inventory
from tools.rust_capsule_project import ROOT

EXECUTABLES = ("latent", "latentd", "latent-aot-compiler", "capsule_authoring", "capsule_contracts", "transaction_recovery")
COMPONENTS = ("domain", "adapter", "adapter-next", "context-required")


def native(directory, receipt):
    observed = read_json(receipt)
    require(observed["allOriginal23VectorsPassed"] is True and observed["allAddedRegressionVectorsPassed"] is True
            and observed["allExecutableBytesReverified"] is True, "java-diagnostic-native-owner-proof")
    source = observed["sourceIdentity"]
    require(source["sourceDirty"] is False and source["sourceVolumeReadOnly"] is True
            and all(isinstance(source[key], str) and re.fullmatch(r"[0-9a-f]{40}", source[key])
                    for key in ("commit", "tree")), "java-diagnostic-native-source-proof")
    require(set(observed["outputs"]) == set(EXECUTABLES), "java-diagnostic-native-executable-set")
    identities = {}
    for name in EXECUTABLES:
        path = directory / name
        actual = file_identity(path, 268435456)
        expected = observed["outputs"][name]
        require(actual == {"sha256": "sha256:" + expected["sha256"], "bytes": expected["bytes"]},
                "java-diagnostic-native-executable-changed")
        with path.open("rb") as stream:
            require(stream.read(4) == b"\x7fELF", "java-diagnostic-native-elf-required")
        identities[name] = actual
    binaries = {name: directory / name for name in ("latent", "latentd", "latent-aot-compiler")}
    binaries.update({"examples/" + name: directory / name for name in ("capsule_authoring", "capsule_contracts")})
    return binaries, {"producerCommit": source["commit"], "producerTree": source["tree"],
        "receipt": file_identity(receipt, 262144), "binaries": identities,
        "completeCI": observed["completeCI"], "scope": "explicit-native-standalone",
        "authenticatedPackagedRuntime": False}


def compiler(builds, *, deadline=None):
    adaptations_path = builds.parent / "diagnostic-adaptations.json"
    adaptations = read_json(adaptations_path)
    require(set(adaptations) == {"domain", "adapter", "adapter-next"},
            "java-diagnostic-explicit-adapted-builds-required")
    domain = adaptations["domain"]
    require(type(domain["providerTimeoutMillis"]) is int and domain["providerTimeoutMillis"] == 250
            and type(domain["domainOutboundRequests"]) is int and domain["domainOutboundRequests"] == 1
            and domain["templateDigest"] == file_identity(ROOT / "sdk/java-guest/templates/http-status.java", 32768)["sha256"]
            and domain["recipeDigest"] == file_identity(ROOT / "tools/java_http_composition/provider_timeout.py", 1048576)["sha256"],
            "java-diagnostic-original-adaptation-owner")
    result = {}
    for name in COMPONENTS:
        root = builds / name
        complete = read_json(root / "BUILD-COMPLETE.json")
        require(type(complete["formatVersion"]) is int and complete["formatVersion"] == 1
                and isinstance(complete["commands"], list)
                and complete["commands"] and all(type(row.get("exitCode")) is int and row["exitCode"] == 0
                                                  for row in complete["commands"]),
                "java-diagnostic-original-compiler-receipt")
        component = file_identity(root / "component.wasm", 33554432)
        require(component["sha256"] == complete["componentDigest"], "java-diagnostic-compiled-component-changed")
        observation = file_identity(root / "build-observation.json", 1048576)
        source = file_identity(root / "source-inputs.json", 8388608)
        require(observation["sha256"] == complete["observationDigest"] and source["sha256"] == complete["sourceDigest"],
                "java-diagnostic-original-compiler-materials-changed")
        captured = read_json(root / "source-inputs.json", 8388608)
        if name in adaptations:
            adapted = adaptations[name]
            require(captured["src/dev/latent/app/Capsule.java"]["digest"] == adapted["sourceDigest"],
                    "java-diagnostic-adapted-source-not-compiled")
            if name == "domain":
                require(captured["wit/world.wit"]["digest"] == adapted["witDigest"]
                        and "latent:http/client@0.2.0" in read_json(root / "surface.json")["imports"],
                        "java-diagnostic-actual-provider-import-required")
            else:
                require(type(adapted["adapterOutboundRequests"]) is int and adapted["adapterOutboundRequests"] == 2
                        and captured["capsule-project.json"]["digest"] == adapted["descriptorDigest"],
                        "java-diagnostic-adapter-child-allowance-not-compiled")
        result[name] = {"complete": file_identity(root / "BUILD-COMPLETE.json", 262144),
                       "component": component, "observation": observation, "source": source}
    return {"components": result, "adaptations": file_identity(adaptations_path, 262144),
            "sourceObserved": True, "hermetic": False,
            "implicitCompilerInputs": "not-attested",
            "retainedFiles": inventory(builds, maximum_files=8192, maximum_bytes=134217728,
                                       deadline=deadline)["filesDigest"]}


def signed(releases, compiled, *, deadline=None):
    """Bind supplied signing inputs to original completed component/source bytes.

    This is a descriptive association. The ordinary native publication owner
    still validates the real package/evidence against the enforced policy.
    """
    marker = read_json(releases / "release-set.json")
    require(marker["schemaVersion"] == "latent.capsule.demo.v1" and marker["tenant"] == "examples"
            and marker["trust"] == "isolated-short-lived-demo-only"
            and type(marker["expiresAtUnixSeconds"]) is int and marker["expiresAtUnixSeconds"] > 0,
            "java-diagnostic-original-signing-marker")
    rows = marker["releases"]
    expected = {"java-http-" + name for name in COMPONENTS}
    require(isinstance(rows, list) and len(rows) == 4 and {row["name"] for row in rows} == expected,
            "java-diagnostic-original-signed-component-set")
    policy = file_identity(releases / "policy.json", 262144)
    require(policy["sha256"] == marker["policyDigest"], "java-diagnostic-original-signing-policy")
    for row in rows:
        name = row["name"][len("java-http-"):]
        original = compiled["components"][name]
        observation = read_json(releases / row["name"] / "build-observation.json")
        require(row["componentDigest"] == observation["componentDigest"] == original["component"]["sha256"]
                and row["sourceSnapshotDigest"] == observation["source"]["snapshotDigest"] == original["source"]["sha256"],
                "java-diagnostic-signed-compiler-association")
    return {"releaseMarker": file_identity(releases / "release-set.json", 262144), "signingPolicy": policy,
            "proofExpiresAtUnixSeconds": marker["expiresAtUnixSeconds"], "ordinaryNativeAdmissionRequired": True,
            "retained": inventory(releases, maximum_files=8192, maximum_bytes=134217728, deadline=deadline)}

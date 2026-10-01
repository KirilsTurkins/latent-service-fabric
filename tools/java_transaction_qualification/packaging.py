"""Package the reviewed preserved components; no guest compiler is invoked."""
from __future__ import annotations

import json
from pathlib import Path
import time

from tools.build_observation import build_environment, file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import fresh, inventory, read_file, snapshot, write_json
from tools.transaction_guest_project import package_companion

from .inputs import ComponentInput, COMPILER_SOURCE, WORLD, decode, digest, load, require

COMPANION_MEDIA = "application/vnd.latent.transaction-binding.v1+json"
LAYER_MEDIA = {"component.wasm": ("component", "application/wasm"),
               "capsule.json": ("capsule-manifest", "application/vnd.latent.capsule.manifest.v1+json"),
               "contracts.json": ("contracts", "application/vnd.latent.contracts.v1+json"),
               "wit-lock.json": ("wit-lock", "application/vnd.latent.wit-lock.v1+json")}
REPOSITORY = "https://github.com/KirilsTurkins/latent-service-fabric"
SCHEMA_ASSETS = ("application-schema-inputs.json", "schemas/application-aggregate-v1.schema.json",
                 "schemas/application-aggregate-v2.schema.json", "src/dev/latent/app/Capsule.java")
CODEC_ASSET = "src/dev/latent/app/AggregateCodec.java"


def schema_assets(files):
    """Retain exact compiler-captured declarations/source; this grants no review."""
    if "application-schema-inputs.json" not in files:
        return {}
    require(all(path in files and 0 < len(files[path]) <= 262144 for path in SCHEMA_ASSETS),
            "complete-original-schema-source-assets-required")
    declaration = decode(files[SCHEMA_ASSETS[0]])
    require(declaration.get("schemaVersion") == "latent.java.application-schema-inputs.v1"
            and declaration.get("variant") in ("legacy-v1", "compatible-v2", "writer-v2")
            and declaration.get("sourceDigest") == digest(files["src/dev/latent/app/Capsule.java"])
            and all(declaration.get(name) is False for name in
                    ("publicationReviewGranted", "componentCompiled", "stateExecutionQualified")),
            "captured-schema-declaration-is-not-native-review")
    selected = {path: files[path] for path in SCHEMA_ASSETS}
    if declaration["variant"] != "legacy-v1":
        require(CODEC_ASSET in files and 0 < len(files[CODEC_ASSET]) <= 262144,
                "original-compatible-reader-codec-required")
        selected[CODEC_ASSET] = files[CODEC_ASSET]
    return selected


def prepare(item: ComponentInput, output: Path, contracts: Path, signer: Path, command: Commands):
    output.mkdir()
    files = snapshot(item.directory / "project")
    project = decode(files["capsule-project.json"])
    component = read_file(item.directory / "component.wasm", 32 * 1024 * 1024)
    require(digest(component) == item.component_digest, "original-component-recheck")
    for name in ("source-inputs.json", "source.tar.gz", "recipe-inputs.json", "compiler-inputs.json"):
        (output / name).write_bytes(read_file(item.directory / name, 32 * 1024 * 1024))
    report_raw = read_file(item.directory / "report.json")
    (output / "compiler-report.json").write_bytes(report_raw)
    report = decode(report_raw)
    (output / "component.wasm").write_bytes(component)
    write_json(output / "wit-inputs.json", {"world": WORLD, "sources": [
        {"path": path, "content": raw.decode("utf-8")} for path, raw in files.items()
        if path.startswith("wit/") and path.endswith(".wit")]})
    command.run(item.name + "-contracts", contracts, output / "wit-inputs.json", output / "derived")
    for name in ("contracts.json", "wit-lock.json"):
        (output / name).write_bytes(read_file(output / "derived" / name))
    surface = decode(read_file(output / "derived/surface.json"))
    seed = decode(read_file(Path(__file__).resolve().parents[2] / "examples/echo-contract/capsule.json"))
    seed["metadata"] = {"tenant": project["tenant"], "name": project["service"]}
    seed["component"] = {"digest": item.component_digest, "version": project["version"], "world": WORLD}
    seed["exports"], seed["imports"] = surface["exports"], [{"contract": name, "optional": False} for name in surface["imports"]]
    seed["execution"].update(limits=project["limits"], threading="single-threaded", snapshotEligible=False, fusionEligible=False)
    write_json(output / "capsule.json", seed)
    layers = [{"path": name, "source": name, "role": role, "mediaType": media}
              for name, (role, media) in LAYER_MEDIA.items()]
    companion = package_companion(output, project, files)
    require(companion == ("transaction-binding.json", "asset", COMPANION_MEDIA), "actual-companion-layer-contract")
    assets = {path: raw for path, raw in files.items() if path.startswith("wit/") and path.endswith(".wit")}
    assets.update({name: files[name] for name in ("state-schema.json", "transaction-profile.json")})
    assets.update(schema_assets(files))
    if item.requirements_digest:
        assets["deferred-http-requirements.json"] = files["deferred-http-requirements.json"]
    if "application-schema-inputs.json" in files:
        recipe = Path(__file__).resolve().parents[2] / "contracts/state/java-aggregate-v1-to-v2-migration.json"
        assets["java-aggregate-v1-to-v2-migration.json"] = read_file(recipe)
    layers.append({"path": companion[0], "source": companion[0], "role": companion[1], "mediaType": companion[2]})
    for path, raw in assets.items():
        (output / path).parent.mkdir(parents=True, exist_ok=True)
        (output / path).write_bytes(raw)
        layers.append({"path": path, "source": path, "role": "asset",
                       "mediaType": "text/plain" if path.endswith((".wit", ".java")) else "application/json"})
    write_json(output / "package-source.json", {"formatVersion": 1, "kind": "capsule", "name": "java718-" + item.name,
               "version": project["version"], "entrypoint": "component.wasm", "annotations": {}, "layers": layers})
    seed = decode(read_file(Path(__file__).resolve().parents[2] / "examples/echo-contract/deployment.json"))
    seed["metadata"] = {"tenant": project["tenant"], "name": project["name"]}
    seed["spec"].update(service=project["service"], release=item.component_digest, grants=[], resources=project["limits"])
    write_json(output / "deployment.json", seed)
    _fixture(item, output, files, report, contracts, signer)


def _fixture(item, output, files, report, contracts, signer):
    # These are actual retained compiler material identities, plus the current
    # native metadata/signing tools. The model is synthetic test trust, expressly
    # not an observation of another Java compiler execution.
    materials = list(report["details"]["tools"])
    for name, data in (("source-snapshot", read_file(output / "source-inputs.json", 4*1024*1024)),
                       ("build-recipe", read_file(output / "recipe-inputs.json", 4*1024*1024)),
                       ("compiler-closure", read_file(output / "compiler-inputs.json", 4*1024*1024)),
                       ("toolchain-config", files["vendor/lsf/tools/toolchain.toml"]),
                       ("dependency-lock", files["vendor/lsf/sdk/java-guest/feasibility/dependencies.lock.json"]),
                       ("generated-bindings", json.dumps(report["details"]["bindings"], sort_keys=True).encode())):
        materials.append({"name": name, "digest": digest(data), "size": len(data)})
    source = decode(read_file(output / "package-source.json"))
    package_files = {"package-source.json": read_file(output / "package-source.json")}
    package_files.update({layer["source"]: read_file(output / layer["source"], 32*1024*1024) for layer in source["layers"]})
    raw = inventory(package_files)
    (output / "package-inputs.json").write_bytes(raw)
    materials.append({"name": "package-inputs", "digest": digest(raw), "size": len(raw)})
    materials += [file_identity(contracts, "contracts-tool"), file_identity(signer, "packager")]
    model = {"formatVersion": 1, "buildType": "https://latent.dev/build/java-capsule/v1",
             "source": {"repository": REPOSITORY, "revision": item.source_digest[7:], "snapshotDigest": item.source_digest,
                        "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
             "componentDigest": item.component_digest, "componentSize": len(read_file(output / "component.wasm")),
             "materials": sorted(materials, key=lambda row: row["name"]),
             "parameters": {"compiler": "teavm-c", "entryPoint": "dev.latent.app.Capsule", "target": "wasm32-wasip1",
                            "bindings": "lsf-java-wit-v1", "optimization": "O2", "javaHeapBytes": 4194304},
             "startedAt": 0, "finishedAt": 0, "reproducibility": "not-checked", "hermetic": False,
             "dependencyCompleteness": "declared-inputs-incomplete"}
    write_json(output / "fixture-provenance-input.json", {
        "schemaVersion": "latent.component.signing-fixture-input.v1", "evidenceKind": "synthetic-native-package-trust",
        "compilerSource": COMPILER_SOURCE, "compilerReportDigest": digest(read_file(output / "compiler-report.json")),
        "sourceArchiveDigest": digest(read_file(output / "source.tar.gz", 32*1024*1024)),
        "sourceSnapshotDigest": item.source_digest, "componentDigest": item.component_digest,
        "companionDigest": item.companion_digest, "requirementsDigest": item.requirements_digest,
        "compilerExecutedBySigner": False, "packagedDistributionQualified": False,
        "signedNodeExecutionQualified": False, "provenanceModel": model})


def package(portable: Path, output: Path, contracts_tool: Path, signer: Path, *, timeout=600) -> Path:
    require(type(timeout) is int and 0 < timeout <= 1800, "original-packaging-deadline")
    items = load(portable)
    output = fresh(output)
    command = Commands(output, output, build_environment(output), deadline_seconds=timeout, command_seconds=min(timeout,600))
    record = {"schemaVersion": "latent.java-transaction-package-fixture.v1", "passed": False,
              "compiledAgain": False, "signedNodeExecutionQualified": False, "packagedDistributionQualified": False,
              "inputs": [item.observation() for item in items], "profileRejections": [],
              "tools": [file_identity(contracts_tool,"contracts-tool"), file_identity(signer,"signer")]}
    start = time.monotonic()
    try:
        for item in items:
            if item.name == "forbidden-http":
                _forbidden_profile(item, output, contracts_tool, signer, command, record)
            else:
                prepare(item, output / item.name, contracts_tool, signer, command)
        accepted = [item for item in items if item.name != "forbidden-http"]
        command.run("fixture-sign-java-inputs", signer, "fixture-sign-java-inputs", output / "signed", *[output / item.name for item in accepted])
        signed = decode(read_file(output / "signed/release-set.json"))
        require(signed["schemaVersion"] == "latent.component.signing-fixture.v1"
                and signed["trust"] == "ephemeral-native-package-test-only", "explicit-fixture-trust-required")
        require({entry["componentDigest"] for entry in signed["releases"]} == {item.component_digest for item in accepted}, "signed-original-components")
        require(all(inventory(snapshot(item.directory / "project")) == read_file(item.directory / "source-inputs.json", 4*1024*1024)
                    and digest(read_file(item.directory / "component.wasm")) == item.component_digest for item in items),
                "preserved-input-recheck")
        require(record["tools"] == [file_identity(contracts_tool,"contracts-tool"), file_identity(signer,"signer")],
                "native-packaging-tool-recheck")
        record["passed"] = True
        return output / "signed"
    finally:
        record["commands"], record["seconds"] = command.records, round(time.monotonic()-start,6)
        write_json(output / "package-fixture-receipt.json", record)


def _forbidden_profile(item, output, contracts, signer, command, record):
    ordinal = len(command.records)
    try:
        prepare(item, output / item.name, contracts, signer, command)
    except ValueError:
        require(len(command.records) == ordinal + 1, "expected-profile-rejection-at-contract-validation")
        observation = command.records[-1]
        stderr = read_file(output / "logs" / f"{ordinal:02d}-forbidden-http-contracts.stderr.txt", 256)
        require(observation["stage"] == "forbidden-http-contracts" and observation["exitCode"] == 1
                and stderr == b"capsule contract generation failed: unsupported-host-import\n",
                "concrete-strict-profile-refusal-required")
        rejected = {"variant": item.name, "componentDigest": item.component_digest,
                    "stage": "native-contract-validation", "reason": "unsupported-host-import",
                    "diagnosticDigest": digest(stderr), "signed": False,
                    "signedNodeExecutionQualified": False}
        record["profileRejections"].append(rejected)
        write_json(output / item.name / "profile-rejection.json", rejected)
        return
    raise ValueError("strict-profile-must-refuse-immediate-http-import")

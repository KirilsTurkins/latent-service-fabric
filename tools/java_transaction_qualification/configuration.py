"""Explicit disposable production configuration; declarations do not grant access."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import socket

from tools.build_observation import file_identity
from tools.phase2_operator_process import read_json, write_json
from tools.phase2_operator_scenario import configure_node
from tools.rust_capsule_project import read_file

from .inputs import ComponentInput, decode, digest, require

TENANT = "examples"
SERVICE = "examples/transaction-java-aggregate"
CONTRACT = "examples:transactional-aggregate/api@1.0.0"
NAMESPACE = "transactional-aggregate"
DEPLOYMENT = "transaction-java-aggregate"
RESULT_POLICY = "java-original-result-v1"
STATE_POLICY = "java-state"
STAGING_POLICY = "java-staging"
DISPATCH_POLICY = "java-dispatch"
RECIPIENT_CREDENTIAL = "java-put-once"
ALICE = "java-transaction-alice"
BOB = "java-transaction-bob"
FOREIGN = "java-transaction-foreign"
OPERATOR = "workflow-operator"
# These credentials belong only to this private disposable test configuration.
TOKENS = {ALICE: "LSF-PUBLIC-JAVA-TRANSACTION-ALICE-TEST-ONLY",
          BOB: "LSF-PUBLIC-JAVA-TRANSACTION-BOB-TEST-ONLY",
          FOREIGN: "LSF-PUBLIC-JAVA-TRANSACTION-FOREIGN-TEST-ONLY"}
CLOCKS = {"clockMonotonic": ("latent:clock/monotonic@0.1.0", "now-nanos"),
          "clockWall": ("latent:clock/wall@0.1.0", "now-unix-millis")}


@dataclass(frozen=True)
class Configuration:
    path: Path
    value: dict
    authority: str
    recipient_origin: dict

    def selected(self, path: Path, operations: list[dict]) -> Path:
        require(isinstance(operations, list) and len(operations) <= 12,
                "bounded-installed-operation-set")
        value = dict(self.value)
        value["state"] = dict(value["state"], operations=operations)
        require(len(json.dumps(value).encode()) <= 65536, "native-config-byte-bound")
        write_json(path, value)
        return path


def configure(directory: Path, signed: Path, compiler: Path, tls: Path,
              checkpoint: Path, recipient_port: int, credential: Path) -> Configuration:
    require(type(recipient_port) is int and 1 <= recipient_port <= 65535,
            "actual-recipient-listener-port")
    require(checkpoint.is_file() and not checkpoint.is_symlink()
            and compiler.is_file() and not compiler.is_symlink(), "native-owned-configuration-inputs")
    original = configure_node(directory, signed, TENANT)
    value = read_json(original)
    # Provision private empty directories only. The native protected owner must
    # still exclusively create both actual file anchors and certify emptiness.
    data = directory / "data"
    data.mkdir(mode=0o700)
    (data / "state").mkdir(mode=0o700)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    authority = f"localhost:{port}"
    origin = {"scheme": "https", "host": "localhost", "port": recipient_port}
    value.update(securityProfile="external-capsule-v1",
        limits={"maximumComponentBytes": 32 * 1024 * 1024, "maximumPayloadBytes": 2 * 1024 * 1024},
        budgetProfile={"mode": "phase4", "maximumStateReadBytes": 4194304,
                       "maximumStateWriteBytes": 2097152, "maximumEffects": 1},
        capabilityPolicies={"formatVersion": 1, "maximumControlJobs": 2,
            "store": {"maximumRecords": 64, "maximumOutcomes": 256, "maximumCatalogBytes": 4194304,
                      "maximumReadOwners": 64, "maximumPageRecords": 16}})
    value["cells"][0].update(capacity=2, queueCapacity=4, maximumMemoryBytes=134217728)
    value["execution"].update(maximumWallTimeMillis=120000)
    value["cache"].update(sourceBytes=128 * 1024 * 1024, compiledImageBytes=256 * 1024 * 1024)
    value["catalogs"].update(releaseEntries=8, deployments=8)
    value["audit"].update(records=4096, diskBytes=67108864)
    value["retention"].update(terminalEntries=128, terminalTtlMillis=120000)
    value["shutdownGraceMillis"] = 5000
    key = directory / "native.key"
    with key.open("xb") as target:
        target.write(bytes([83]) * 32)
    key.chmod(0o600)
    value["isolatedAot"] = {"compilerExecutable": str(compiler.resolve()),
        "compilerDigest": file_identity(compiler, "aot-compiler", 256 * 1024 * 1024)["digest"], "keyFile": "native.key",
        "blobRoot": "native-blobs", "receiptRoot": "native-receipts",
        "process": {"jobTimeoutMillis": 300000, "maximumOutputBytes": 134217728,
                    "addressSpaceBytes": 4294967296},
        "cache": {"entries": 8, "diskBytes": 536870912},
        "images": {"maximumImages": 4, "maximumImageBytes": 134217728, "maximumTotalBytes": 536870912}}
    value["credentials"] += [{"token": token, "subject": subject,
        "tenant": "foreign" if subject == FOREIGN else TENANT, "role": "invoke"}
        for subject, token in TOKENS.items()]
    value["httpIngress"] = {"formatVersion": 1, "bind": f"127.0.0.1:{port}",
        "transport": {"mode": "loopback"}, "authentication": {"mode": "bearer"},
        "limits": {"maximumConnections": 16, "maximumExchanges": 4,
                   "maximumBufferBytes": 50331648, "maximumRequestsPerConnection": 8}}
    providers = {"formatVersion": 1, "bindings": []}
    for name, (contract, _operation) in CLOCKS.items():
        providers[name] = {"identity": {"id": name, "tenant": TENANT, "service": "runtime-host", "epoch": 1}}
        providers["bindings"].append({"name": name + "-transaction", "tenant": TENANT,
            "consumerService": SERVICE, "providerService": "runtime-host",
            "contract": contract, "providerBinding": name + "-installed"})
    providers["http"] = {"identity": {"id": "http", "tenant": TENANT,
        "service": "runtime-host", "epoch": 1},
        "configuration": {"formatVersion": 1, "publicRoots": False,
            "extraRoots": [list(read_file(tls / "ca.der", 65536))],
            "limits": {"maximumRequestBodyBytes": 32768, "maximumResponseBodyBytes": 32768,
                "maximumEncodedResponseBytes": 32768, "maximumHeaderBytes": 8192,
                "maximumHeaders": 32, "maximumRedirects": 0},
            "destinations": [{"origin": origin,
                "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
                "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
                "allowedRequestHeaders": [], "redirectDestinations": []}]},
        "credentialDirectory": str(credential.parent),
        "credentials": [{"reference": RECIPIENT_CREDENTIAL, "file": credential.name,
                         "destination": 0, "header": "authorization"}]}
    value["providers"] = providers
    value["state"] = {"formatVersion": 1, "createIfMissing": True, "configurationEpoch": 1,
                      "clockCheckpoint": str(checkpoint.resolve()), "operations": []}
    path = directory / "bootstrap-node.json"
    write_json(path, value)
    return Configuration(path, value, authority, origin)


def installed(items: tuple[ComponentInput, ...], publications: dict[str, str],
              recipient_incarnation: str) -> list[dict]:
    import re
    require(re.fullmatch(r"[0-9a-f]{64}", recipient_incarnation), "actual-recipient-incarnation")
    result = []
    accepted = tuple(item for item in items if item.name != "forbidden-http")
    require(set(publications) == {item.name for item in accepted}, "exact-admitted-publication-set")
    for item in accepted:
        require(re.fullmatch(r"publication:sha256:[0-9a-f]{64}", publications[item.name]),
                "actual-admitted-publication-required")
        raw = read_file(item.directory / "project/transaction-binding.json", 128 * 1024)
        require(digest(raw) == item.companion_digest, "original-companion-recheck")
        companion = decode(raw)
        require(companion["capsule"] == SERVICE and companion["namespace"] == NAMESPACE
                and companion["deployment"] == DEPLOYMENT and companion["binding"] == DEPLOYMENT,
                "exact-signed-operation-links")
        for operation in companion["operations"]:
            name = operation["operation"]
            require(name in {"update", "query", "scan"}
                    and operation["mode"] == ("strict-command" if name == "update" else "fresh-query"),
                    "exact-original-operation-mode")
            row = {"tenant": TENANT, "componentDigest": item.component_digest,
                "publication": publications[item.name], "contract": CONTRACT, "function": name,
                "deployment": DEPLOYMENT, "route": DEPLOYMENT, "binding": DEPLOYMENT,
                "companionDigest": item.companion_digest, "incarnation": 1,
                "resultPolicy": RESULT_POLICY, "statePolicies": [STATE_POLICY]}
            if name == "update" and item.requirements_digest:
                row["deferredHttp"] = {"requirementsDigest": item.requirements_digest,
                    "providerId": "http", "providerIncarnation": recipient_incarnation,
                    "credentialReference": RECIPIENT_CREDENTIAL, "stagingBinding": "java-staging-installed",
                    "stagingPolicies": [STAGING_POLICY], "dispatchBinding": "java-dispatch-installed",
                    "dispatchPolicies": [DISPATCH_POLICY]}
            result.append(row)
    require(len(result) == 12 and len({(row["publication"], row["function"]) for row in result}) == 12,
            "exact-original-twelve-operation-set")
    return result

"""Check the original portable compiler outputs without compiling or granting access."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from tools.rust_capsule_project import inventory, read_file, snapshot

VARIANTS = ("aggregate", "forbidden-http", "put-once-legacy-v1",
            "put-once-compatible-v2", "put-once-writer-v2")
REQUIRED_IMPORTS = {"latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"}
WORLD = "examples:transactional-aggregate/service@1.0.0"
MAX_COMPONENT_BYTES = 32 * 1024 * 1024
COMPILER_SOURCE = "ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6"
TOOL_PRODUCER_SOURCE = "761172002e4a4d02102f8c757235b888fe4859e1"
COMPONENT_DIGESTS = dict(zip(VARIANTS, ("sha256:" + value for value in (
    "3d7f1e8795c09088645e5ae10e75a913b2078ae77fe2822504a533b8f22c5c6a",
    "ac625772e9dacf2b28284f20088c637f3761b920471c4889e8b9d3e7d30cd6dc",
    "112e60fbf29c131d221f21de677d0e3b268cacf5bc17db184b94655c0513734d",
    "1221ffac1d4f8db71327d56fba1624df19bff849a26f687a57888ccc4a0279ae",
    "ec6ac5b4a95957406f664f7df9feb4a92829fb26e8634cde97f8b44ae21082ce"))))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate-qualification-json-field")
        result[key] = value
    return result


def decode(raw: bytes, maximum=262144):
    require(0 < len(raw) <= maximum, "qualification-document-byte-bound")
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite-json")))


@dataclass(frozen=True)
class ComponentInput:
    name: str
    directory: Path
    component_digest: str
    companion_digest: str
    source_digest: str
    compiler_source: str
    host_abi_digest: str
    requirements_digest: str | None

    def observation(self) -> dict:
        return {"variant": self.name, "componentDigest": self.component_digest,
                "companionDigest": self.companion_digest, "sourceDigest": self.source_digest,
                "compilerSource": self.compiler_source, "hostAbiDigest": self.host_abi_digest,
                "requirementsDigest": self.requirements_digest,
                "signedNodeExecutionQualified": False}


def load(directory: Path) -> tuple[ComponentInput, ...]:
    """Verify exact captured bytes; the node must still verify packages and authority."""
    receipt = decode(read_file(directory / "controller-receipt-r3.json"))
    require(receipt.get("schemaVersion") == 1
            and receipt.get("evidenceKind") == "authored-component-compiler"
            and receipt.get("compiled") is True
            and receipt.get("signedNodeExecutionQualified") is False
            and receipt.get("admissionRejectionQualified") is False,
            "compiler-proof-is-not-signed-runtime-proof")
    source = receipt.get("compilerSource")
    require(source == COMPILER_SOURCE and receipt.get("toolProducerSource") == TOOL_PRODUCER_SOURCE,
            "exact-compiler-source-required")
    require(isinstance(receipt.get("variants"), dict)
            and set(receipt["variants"]) == set(VARIANTS), "exact-five-component-set-required")
    selected = []
    for name in VARIANTS:
        current = directory / name
        report = decode(read_file(current / "report.json"))
        record = receipt["variants"][name]
        require(report.get("schemaVersion") == "latent.transaction-guest.compiler.v1"
                and report.get("language") == "java" and report.get("variant") == name
                and report.get("world") == WORLD and report.get("status") == "compiled"
                and report.get("compiled") is True and report.get("workingTreeChanged") is False
                and report.get("signedNodeExecutionQualified") is False
                and report.get("admissionRejectionQualified") is False,
                "exact-authored-java-compiler-report-required")
        component = read_file(current / "component.wasm", MAX_COMPONENT_BYTES)
        require(component.startswith(b"\0asm\x0d\0\x01\0"), "actual-component-header-required")
        require(type(report.get("componentBytes")) is int
                and len(component) == report["componentBytes"] == record.get("componentBytes")
                and digest(component) == report.get("componentDigest") == record.get("componentDigest"),
                "compiled-component-byte-identity")
        require(report["componentDigest"] == COMPONENT_DIGESTS[name], "reviewed-component-selection")
        captured = snapshot(current / "project")
        source_inputs = read_file(current / "source-inputs.json", 4 * 1024 * 1024)
        require(inventory(captured) == source_inputs, "captured-java-project-changed")
        for field, raw in (("sourceDigest", source_inputs),
                           ("sourceArchiveDigest", read_file(current / "source.tar.gz", 32 * 1024 * 1024)),
                           ("companionDigest", captured["transaction-binding.json"])):
            require(digest(raw) == report.get(field) == record.get(field), "original-compiler-material-mismatch")
        recipe = read_file(current / "recipe-inputs.json", 4 * 1024 * 1024)
        require(digest(recipe) == report.get("recipeDigest"), "original-compiler-recipe-mismatch")
        require(report.get("sourceRevision") == record.get("sourceRevision") == source,
                "mixed-java-source-revisions")
        profile = decode(captured["transaction-profile.json"])
        require(profile["hostAbiDigest"] == report.get("hostAbiDigest"), "captured-transaction-profile-mismatch")
        imports = report.get("actualImports")
        require(isinstance(imports, list) and 0 < len(imports) <= 16
                and all(isinstance(item, str) for item in imports)
                and len(imports) == len(set(imports)) and REQUIRED_IMPORTS <= set(imports),
                "actual-transaction-imports-required")
        require(("latent:http/client@0.2.0" in imports) == (name == "forbidden-http"),
                "forbidden-immediate-http-component-required")
        requirements = None
        if name.startswith("put-once-"):
            raw = captured["deferred-http-requirements.json"]
            requirements = digest(raw)
            require(requirements == report.get("deferredHttpRequirementsDigest"),
                    "original-signed-requirements-mismatch")
            value = decode(raw)
            require(value.get("authority") == {"installed": False, "ruleGranted": False,
                                               "executionQualified": False},
                    "requirements-cannot-grant-authority")
        selected.append(ComponentInput(name, current, report["componentDigest"], report["companionDigest"],
                                       report["sourceDigest"], source, report["hostAbiDigest"], requirements))
    require(len({item.component_digest for item in selected}) == len(selected), "distinct-components-required")
    return tuple(selected)

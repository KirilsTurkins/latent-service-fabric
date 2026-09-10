"""Independent fixed Echo variants, canonical revision IDs and route selection."""
from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
import hashlib

from tools.optimization_evidence.common import canonical, fields, require, sha256, uint
from . import model

TENANT = "examples"
CONTRACT = "examples:echo/api@0.1.0"
NAME = b"latent.scale.identity.v1"
COMPONENT_HEADER = b"\0asm\r\0\1\0"


def name(index):
    require(type(index) is int and 0 <= index < 100000, "catalog-fixture-index")
    return f"scale-{index:06}"


def service(index, shape):
    require(shape in model.SHAPES, "catalog-fixture-shape")
    identifier = name(index)
    return identifier if shape == "distinct" else "scale-shared"


def component(base, index):
    name(index)
    require(isinstance(base, bytes) and base.startswith(COMPONENT_HEADER)
            and 8 <= len(base) <= 16 * 1024**2 - 31, "catalog-base-component-bound")
    return base + bytes((0, len(NAME) + 5, len(NAME))) + NAME + index.to_bytes(4, "little")


def input_case(count, case, ordinal, shape):
    require(type(count) is int and 1 <= count <= 100000 and case in model.CASES
            and type(ordinal) is int and 0 <= ordinal < 10000, "catalog-resolver-input")
    index = ordinal * 7919 % count
    target = {"tenant": TENANT, "service": service(index, shape), "contract": CONTRACT,
              "function": "missing-function" if case == "export-miss" else "echo",
              "route": name(index) if case == "named-success" else "missing-route" if case == "route-miss" else None}
    return index, target, f"catalog-key-{ordinal:05}"


def selection_word(target, key):
    data = bytearray(b"lsf-route-selection-v1\0")
    for part in (target["tenant"], target["service"], target["route"] or "default",
                 target["contract"], target["function"], key or ""):
        encoded = part.encode("utf-8")
        data.extend(len(encoded).to_bytes(8, "big"))
        data.extend(encoded)
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


def contract_schema(metadata):
    """The maintained one-function Echo schema, not a generic type interpreter."""
    contract = metadata["contracts"][0]
    interface = contract["interfaces"][0]
    function = interface["functions"][0]
    expected = {"id": "echo", "name": "echo", "asynchronous": False,
                "parameters": [{"name": "message", "value_type": "String", "documentation": None}],
                "results": [{"name": "result", "value_type": {
                    "Result": {"ok": "String", "error": {"Variant": "echo-error"}}}, "documentation": None}],
                "documentation": None, "attributes": {}}
    require(function == expected and contract["id"] == interface["id"] == CONTRACT
            and len(metadata["contracts"]) == len(contract["interfaces"]) == len(interface["functions"]) == 1
            and contract["dependencies"] == [], "catalog-maintained-contract-crossed")
    canonical_function = {**expected,
        "parameters": [{"name": "message", "type": "string", "documentation": None}],
        "results": [{"name": "result", "type": ["result", "string", ["variant", "echo-error"]],
                     "documentation": None}]}
    return sha256(canonical({"id": contract["id"], "package": contract["package_name"],
        "version": contract["semantic_version"], "digest": contract["digest"], "dependencies": [],
        "interfaces": [{"id": interface["id"], "digest": interface["digest"],
                        "documentation": interface["documentation"], "functions": [canonical_function]}]}))


@dataclass(frozen=True)
class Fixture:
    base: bytes
    capsule: dict
    contracts: dict
    deployment_template: dict
    exports_json: str

    def template(self):
        capsule = deepcopy(self.capsule)
        if capsule["execution"]["limits"].get("wallTimeLimitMillis") is None:
            capsule["execution"]["limits"].pop("wallTimeLimitMillis", None)
        deployment = self.deployment(0, "distinct")
        deployment["metadata"]["name"] = "measurement-echo"
        deployment["spec"].update(service="measurement-echo", release=sha256(self.base),
                                   route=deepcopy(self.deployment_template["spec"]["route"]))
        return {"component_digest": sha256(self.base), "component_bytes": str(len(self.base)),
                "capsule": capsule, "deployment": deployment, "contracts": self.contracts,
                "identity_section": {"name": NAME.decode(), "index_encoding": "u32-little-endian",
                                     "added_bytes": "31"}}

    def release(self, index):
        return sha256(component(self.base, index))

    def publication_digest(self, first, count, shape):
        require(type(first) is int and type(count) is int and 0 <= first < 100000
                and 1 <= count <= 256 and first + count <= 100000, "catalog-publication-chunk-bound")
        digest = hashlib.sha256(b"lsf-catalog-publication-v1\0")
        template = self.template()["capsule"]
        for index in range(first, first + count):
            release = self.release(index)
            capsule = deepcopy(template)
            capsule["component"]["digest"] = release
            capsule["metadata"]["name"] = service(index, shape)
            row = {"index": str(index), "descriptor": {"reference": f"local://scale/{index:06}",
                   "release": release, "size": str(len(self.base) + 31),
                   "media_type": "application/vnd.wasm.component.v1+wasm"},
                   "capsule_digest": sha256(canonical(capsule)),
                   "deployment_digest": sha256(canonical(self._deployment(index, shape, 1, release)))}
            encoded = canonical(row)
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return "sha256:" + digest.hexdigest()

    def deployment(self, index, shape, weight=1):
        return self._deployment(index, shape, weight, self.release(index))

    def _deployment(self, index, shape, weight, release):
        require(type(weight) is int and weight in (1, 2), "catalog-fixture-weight")
        value = deepcopy(self.deployment_template)
        value["metadata"]["name"] = name(index)
        value["metadata"]["tenant"] = TENANT
        spec = value["spec"]
        spec.update(service=service(index, shape), release=release, route={"weight": weight})
        spec["resources"] = deepcopy(self.capsule["execution"]["limits"])
        if spec["resources"].get("wallTimeLimitMillis") is None:
            spec["resources"].pop("wallTimeLimitMillis", None)
        spec["grants"] = [{"capability": row["contract"], "policy": "measurement/activation-scoped"}
                          for row in sorted(self.capsule["imports"], key=lambda row: row["contract"])]
        for key in ("architectures", "regions", "zones", "requiredFeatures"):
            if spec["placement"].get(key):
                spec["placement"][key] = sorted(set(spec["placement"][key]))
            else:
                spec["placement"].pop(key, None)
        return value

    def revision(self, index, shape):
        encoded = canonical(self.deployment(index, shape, 1))
        return "revision-v1:" + sha256(b"lsf-deployment-revision-v1\0" + len(encoded).to_bytes(8, "big") + encoded)

    def attributes(self, index, shape, weight=1):
        return {"lsf.deployment": canonical(self.deployment(index, shape, weight)).decode("utf-8"),
                "lsf.exports": self.exports_json}

    def ordered_revisions(self, count, shape, *, updated=False):
        require(type(count) is int and 1 <= count <= 100000 and type(updated) is bool,
                "catalog-selection-bound")
        rows = sorted((self.revision(index, shape), index) for index in range(count))
        total, ends = 0, []
        for _, index in rows:
            total += 2 if updated and index == 0 else 1
            ends.append(total)
        return rows, ends

    @staticmethod
    def selected(ordered, target, key):
        rows, ends = ordered
        require(bool(rows) and len(rows) == len(ends), "catalog-selection-empty")
        return rows[bisect_right(ends, selection_word(target, key) % ends[-1])][1]


def load(echo, artifacts):
    fields(echo, "component capsule contracts deployment build")
    require(8 <= uint(echo["component"]["bytes"]) <= 16 * 1024**2 - 31, "catalog-echo-bound")
    base = artifacts.path(echo["component"]).read_bytes()
    require(base.startswith(COMPONENT_HEADER) and sha256(base) == echo["component"]["sha256"],
            "catalog-echo-component-crossed")
    def source(name):
        path = "builds/harness/source/examples/echo-contract/" + name
        require(path in artifacts.rows, "catalog-fixture-source-missing")
        return artifacts.json(artifacts.rows[path])
    capsule = artifacts.json(echo["capsule"])
    expected = source("capsule.json")
    expected["component"]["digest"] = sha256(base)
    expected["metadata"].setdefault("annotations", {}).update({
        "latent.dev/purpose": "phase-0-echo-fixture", "latent.dev/trust": "local-build",
        "latent.dev/artifact": "echo-capsule.wasm"})
    require(capsule == expected, "catalog-built-capsule-crossed")
    contracts = artifacts.json(echo["contracts"])
    require(contracts == source("contracts.json"), "catalog-built-contract-crossed")
    template = source("deployment.json")
    original = deepcopy(template)
    original["spec"]["release"] = sha256(base)
    require(artifacts.json(echo["deployment"]) == original, "catalog-built-deployment-crossed")
    return normalize(base, capsule, contracts, template)


def normalize(base, capsule, contracts, template):
    """Project the common Rust Fixture::echo from independently retained inputs."""
    normalized = deepcopy(capsule)
    normalized["metadata"].update(name="measurement-echo", tenant=TENANT)
    normalized["execution"]["limits"].update(cpuFuel=10_000_000_000, memoryBytes=67_108_864)
    normalized["execution"].update(threading="single-threaded", snapshotEligible=False, fusionEligible=False)
    exports = canonical({CONTRACT: {"schema": contract_schema(contracts), "functions": ["echo"]}}).decode("utf-8")
    return Fixture(base, normalized, contracts, template, exports)

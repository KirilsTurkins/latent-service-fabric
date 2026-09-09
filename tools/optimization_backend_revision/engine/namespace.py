"""Independently replay the closed outer-export fixture transformation."""
import copy
import re

from tools.optimization_evidence.common import EvidenceError, require
from tools.optimization_runner.fixtures import signed

HEADER = b"\0asm\r\0\1\0"
MAX_BYTES = 16 * 1024**2
MAX_SECTIONS = 4096
MAX_NAME_BYTES = 256
NAMESPACE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
PACKAGES = {"echo": ("examples", "echo", ("api",)),
            "optimization": ("optimization", "benchmark", ("workloads",)),
            "generic": ("tests", "generic", ("alternate", "values")),
            "capabilities": ("tests", "capabilities", ("api",)),
            "engine-memory": ("tests", "engine-memory", ("memory",))}


def valid_namespace(value):
    return isinstance(value, str) and len(value) <= 64 and NAMESPACE.fullmatch(value) is not None


def owned_name(value, original, tenant):
    require(isinstance(value, str) and value.startswith(original + ":")
            and len(value) > len(original) + 1, "engine-owned-namespace-crossed")
    return tenant + value[len(original):]


def exports(family, tenant=None):
    original, package, interfaces = PACKAGES[family]
    return tuple(f"{tenant or original}:{package}/{name}@0.1.0" for name in interfaces)


def leb(value):
    require(type(value) is int and 0 <= value <= 0xFFFFFFFF, "engine-namespace-u32-bound")
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


class Reader:
    def __init__(self, data):
        self.data, self.position = data, 0

    def take(self, count):
        end = self.position + count
        require(end <= len(self.data), "engine-namespace-truncated")
        value = self.data[self.position:end]
        self.position = end
        return value

    def byte(self):
        return self.take(1)[0]

    def u32(self):
        value = 0
        for index in range(5):
            byte = self.byte()
            require(index != 4 or byte <= 15, "engine-namespace-u32-bound")
            value |= (byte & 127) << (index * 7)
            if byte < 128:
                return value
        raise EvidenceError("engine-namespace-u32-bound")

    def name(self):
        size = self.u32()
        require(size <= MAX_NAME_BYTES, "engine-namespace-name-bound")
        try:
            return self.take(size).decode("utf-8")
        except UnicodeError as error:
            raise EvidenceError("engine-namespace-invalid-name") from error


def rewrite_exports(data, original, tenant, expected, seen):
    reader = Reader(data)
    count = reader.u32()
    require(count <= len(expected) - len(seen), "engine-namespace-export-count")
    output = bytearray(data[:reader.position])
    for _ in range(count):
        entry_start = reader.position
        discriminator = reader.byte()
        require(discriminator in (0, 1), "engine-namespace-name-options")
        name = reader.name()
        suffix = reader.position
        require(reader.byte() == 5, "engine-namespace-export-kind")
        reader.u32()
        require(reader.byte() == 0, "engine-namespace-export-type")
        require(name in expected and name not in seen, "engine-namespace-export-set")
        seen.add(name)
        renamed = owned_name(name, original, tenant).encode("ascii")
        require(len(renamed) <= MAX_NAME_BYTES, "engine-namespace-name-bound")
        if renamed == name.encode("ascii"):
            output.extend(data[entry_start:reader.position])
        else:
            output.extend(bytes((discriminator,)) + leb(len(renamed)) + renamed + data[suffix:reader.position])
    require(reader.position == len(data), "engine-namespace-export-trailing")
    return bytes(output)


def retarget(base, original, tenant, expected):
    require(isinstance(base, bytes) and len(base) <= MAX_BYTES and base.startswith(HEADER)
            and valid_namespace(original) and valid_namespace(tenant), "engine-namespace-input-bound")
    require(isinstance(expected, (list, tuple)) and 1 <= len(expected) <= 8,
            "engine-namespace-expected-exports")
    for index, name in enumerate(expected):
        require(isinstance(name, str) and len(name) <= MAX_NAME_BYTES
                and all(33 <= ord(char) <= 126 for char in name)
                and name.startswith(original + ":") and len(name) > len(original) + 1
                and name not in expected[:index], "engine-namespace-expected-exports")
    reader, output, count, seen = Reader(base), bytearray(HEADER), 0, set()
    reader.take(len(HEADER))
    while reader.position < len(base):
        start, count = reader.position, count + 1
        require(count <= MAX_SECTIONS, "engine-namespace-section-bound")
        kind = reader.byte()
        require(kind <= 11, "engine-namespace-section-kind")
        payload = reader.take(reader.u32())
        if kind == 11:
            rewritten = rewrite_exports(payload, original, tenant, expected, seen)
            if rewritten != payload:
                output.extend(b"\x0b" + leb(len(rewritten)) + rewritten)
            else:
                output.extend(base[start:reader.position])
        else:
            output.extend(base[start:reader.position])
        require(len(output) <= MAX_BYTES, "engine-namespace-output-bound")
    require(seen == set(expected), "engine-namespace-missing-exports")
    return bytes(output)


def component(base, family, tenant):
    """Both tenants are retargeted; the B identity marker follows that change."""
    require(tenant in ("engine-a", "engine-b") and family in PACKAGES, "engine-fixture-selector")
    output = retarget(base, PACKAGES[family][0], tenant, exports(family))
    if tenant == "engine-b":
        name = b"latent.engine-fixture.tenant-b"
        payload = leb(len(name)) + name + (family + "/v1").encode("ascii")
        output += b"\0" + leb(len(payload)) + payload
    require(len(output) <= MAX_BYTES, "engine-tenant-component-byte-bound")
    return output


def contracts(metadata, original, tenant):
    """Rename owned descriptor identities only; imported types stay untouched."""
    require(valid_namespace(original) and valid_namespace(tenant), "engine-metadata-namespace")
    require(isinstance(metadata, dict), "engine-metadata-document")
    value = copy.deepcopy(metadata)
    require(value.get("format_version") == 1 and isinstance(value.get("contracts"), list)
            and 1 <= len(value["contracts"]) <= 8, "engine-metadata-contract-count")
    for descriptor in value["contracts"]:
        require(isinstance(descriptor, dict) and descriptor.get("dependencies") == []
                and isinstance(descriptor.get("interfaces"), list)
                and 1 <= len(descriptor["interfaces"]) <= 8, "engine-metadata-descriptor-shape")
        for key in ("id", "package_name"):
            descriptor[key] = owned_name(descriptor.get(key), original, tenant)
        for interface in descriptor["interfaces"]:
            require(isinstance(interface, dict), "engine-metadata-interface-shape")
            interface["id"] = owned_name(interface.get("id"), original, tenant)
            interface.pop("digest", None)
            interface.update(signed(interface))
        descriptor.pop("digest", None)
        descriptor.update(signed(descriptor))
    return value

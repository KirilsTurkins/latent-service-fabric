"""Private, exact-preimage CLR hash entropy with separately declared authority."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
import xml.etree.ElementTree as XML

from tools.build_observation import file_identity
from tools.dotnet_guest import runtime
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json

PROFILE = "dotnet-hash-entropy-v1"
ENTRYPOINT = "SystemNative_GetNonCryptographicallySecureRandomBytes"
WRAP = "-Wl,--wrap=" + ENTRYPOINT
MAX_SOURCE = 64 * 1024
MAX_OBJECT = 128 * 1024
MAX_RESPONSE = 1024 * 1024
UPSTREAM = {
    "formatVersion": 1, "package": "runtime.wasi-wasm.microsoft.dotnet.ilcompiler.llvm",
    "version": "10.0.0-rc.1.26306.1", "repository": "https://github.com/dotnet/runtimelab",
    "revision": "8449ba666dd991e495d8363d9852f18eb86a1aa1",
    "path": "runtimes/wasi-wasm/native-hidden/libSystem.Native.a",
    "archiveDigest": "sha256:48b05195164bf556bf6cf41456f7a531275a8ad192ca74a1f0388d375955ae95",
    "archiveSize": 254498, "member": "pal_random.c.obj",
    "memberDigest": "sha256:5012866cd28f6e0e7eb173cf764d77b7fdefc4b4198eeb7fd26a9db716fa0093",
    "memberSize": 2325, "entrypoint": ENTRYPOINT, "profile": PROFILE,
}


def msbuild_literal(path: Path) -> str:
    value = str(path)
    if len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise ValueError("noncrypto-entropy-path-limit")
    for char, escaped in (("%", "%25"), ("$", "%24"), ("@", "%40"), (";", "%3B"),
                          ("*", "%2A"), ("?", "%3F"), ("'", "%27"), ("(", "%28"), (")", "%29")):
        value = value.replace(char, escaped)
    return value


def archive_identity(archive: Path) -> dict:
    identity = file_identity(archive, "noncrypto-entropy-original-native-archive", 1024 * 1024)
    if identity["digest"] != UPSTREAM["archiveDigest"] or identity["size"] != UPSTREAM["archiveSize"]:
        raise ValueError("noncrypto-entropy-unsupported-native-preimage")
    return identity


@dataclass
class NativeEntropyPort:
    source: Path
    private_source: Path
    archive: Path
    object: Path
    retained: Path
    targets: Path
    object_identity: dict
    source_identity: bytes
    native_identity: bytes
    target_identity: bytes
    evidence: dict

    def recheck(self) -> None:
        if inventory(snapshot(self.source)) != self.source_identity:
            raise ValueError("noncrypto-entropy-source-changed")
        if read_file(self.private_source, MAX_SOURCE) != self.native_identity:
            raise ValueError("noncrypto-entropy-private-source-changed")
        archive_identity(self.archive)
        if (file_identity(self.object, "noncrypto-entropy-object", MAX_OBJECT) != self.object_identity
                or file_identity(self.retained, "noncrypto-entropy-object", MAX_OBJECT) != self.object_identity):
            raise ValueError("noncrypto-entropy-object-changed")
        if read_file(self.targets, MAX_SOURCE) != self.target_identity:
            raise ValueError("noncrypto-entropy-targets-changed")

    def finish(self, project: Path, evidence: Path) -> dict:
        self.recheck()
        responses = list((project / "obj").rglob("link.rsp"))
        if len(responses) != 1:
            raise ValueError("noncrypto-entropy-link-response-count")
        body = read_file(responses[0], MAX_RESPONSE)
        arguments = shlex.split(body.decode("utf-8-sig"))
        if (len(arguments) > 8192 or arguments.count(str(self.object)) != 1
                or arguments.count(WRAP) != 1
                or any("--wrap=" in argument and argument != WRAP for argument in arguments)):
            raise ValueError("noncrypto-entropy-native-link-binding")
        result = {**self.evidence, "nativeLinkBinding": {"responseDigest": digest(body), "responseSize": len(body),
            "objectOccurrences": 1, "wrapOccurrences": 1}, "ordinaryLibraryExecutionQualified": False}
        write_json(evidence / "noncrypto-entropy-port.json", result)
        return result


def prepare(compiler, declared: list[str], project: Path, output: Path) -> NativeEntropyPort | None:
    if runtime.RANDOM not in declared:
        return None
    source = compiler.sdk / "tools/native-entropy"
    descriptor = json.loads(read_file(source / "upstream.json", MAX_SOURCE))
    if descriptor != UPSTREAM:
        raise ValueError("noncrypto-entropy-unreviewed-upstream")
    source_identity = inventory(snapshot(source))
    archive = compiler.package_cache / UPSTREAM["package"] / UPSTREAM["version"] / UPSTREAM["path"]
    original = archive_identity(archive)
    member = compiler.run("noncrypto-native-preimage", compiler.wasi_sdk / "bin/llvm-ar", "p", archive, UPSTREAM["member"])
    if len(member) != UPSTREAM["memberSize"] or digest(member) != UPSTREAM["memberDigest"]:
        raise ValueError("noncrypto-entropy-unsupported-member-preimage")
    owned = output / "noncrypto-entropy-port"
    owned.mkdir(mode=0o700)
    native, targets, obj = owned / "entropy.c", owned / "NativeEntropy.targets", owned / "noncrypto-entropy.o"
    native_identity = read_file(source / "entropy.c", MAX_SOURCE)
    native.write_bytes(native_identity)
    target_identity = read_file(source / "NativeEntropy.targets", MAX_SOURCE)
    targets.write_bytes(target_identity)
    if compiler.isolation:
        compiler.isolation.protect_inputs(native, targets)
    compiler.run("noncrypto-entropy-compile", compiler.wasi_sdk / "bin/clang", "--target=wasm32-wasip2",
        "-Oz", "-fvisibility=hidden", "-fno-ident", "-c", native, "-o", obj)
    identity = file_identity(obj, "noncrypto-entropy-object", MAX_OBJECT)
    retained = compiler.commands.output / "noncrypto-entropy.o"
    with retained.open("xb") as destination:
        destination.write(read_file(obj, MAX_OBJECT))
    if compiler.isolation:
        compiler.isolation.protect_inputs(obj)
    document = XML.fromstring(read_file(project / "Capsule.csproj", MAX_SOURCE))
    properties = XML.SubElement(document, "PropertyGroup")
    XML.SubElement(properties, "LsfInternalNoncryptoEntropyProfile").text = PROFILE
    XML.SubElement(properties, "LsfInternalNoncryptoEntropyObject").text = msbuild_literal(obj)
    XML.SubElement(document, "Import", Project=msbuild_literal(targets))
    (project / "Capsule.csproj").write_bytes(XML.tostring(document, encoding="utf-8", xml_declaration=True))
    value = {"schemaVersion": "lsf.dotnet.noncrypto-entropy.v1", "profile": PROFILE,
        "entrypoint": ENTRYPOINT, "requiredDeclaration": runtime.RANDOM, "secureRandom": "unchanged-denial",
        "original": original, "originalMember": {"digest": digest(member), "size": len(member)},
        "sourceDigest": digest(source_identity), "targetsDigest": digest(target_identity), "derived": identity,
        "upstream": descriptor, "nativeLinkBinding": None, "ordinaryLibraryExecutionQualified": False}
    write_json(compiler.commands.output / "noncrypto-entropy-preparation.json", value)
    return NativeEntropyPort(source, native, archive, obj, retained, targets, identity, source_identity,
                             native_identity, target_identity, value)

"""Publisher authentication using an independently provisioned OpenSSL and key."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile

from .common import document, execute, require
from . import files

TARGET = "x86_64-unknown-linux-gnu"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")
PLATFORM = {"osId": "ubuntu", "osVersion": "24.04", "minimumKernel": "6.8",
            "minimumGlibc": "2.39", "cpuFeatures": ["sse2"], "pythonMinimum": "3.12"}
REQUIRED = {"bin/latent", "bin/latentd", "bin/latent-aot-compiler", "lsf-install.pyz",
            "systemd/lsf.service", "config/local-experimental-v1.json",
            "config/external-capsule-v1.json", "LICENSE", "NOTICE", "INSTALL.md",
            "sbom.spdx.json", "build-provenance.json", "release-source.json",
            "examples/echo/echo-capsule.wasm", "examples/echo/capsule.json",
            "examples/echo/contracts.json", "examples/echo/deployment.json", "examples/echo/input.json"}


def version(value: str) -> str:
    require(isinstance(value, str) and len(value) <= 80 and VERSION.fullmatch(value), "invalid-version")
    return value


def relative(value: str) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 240, "archive-path-limit")
    require(all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", part)
                for part in value.split("/")), "unsafe-archive-path")
    require(len(value.split("/")) <= 12, "archive-path-depth")
    return value


def manifest(value: dict, selected: str) -> dict:
    require(set(value) == {"schemaVersion", "version", "sourceCommit", "target", "toolchain",
                           "engine", "platform", "compatibility", "archive", "bootstrap", "files"},
            "release-manifest-members")
    require(value["schemaVersion"] == "latent.native-release.v1" and value["version"] == version(selected),
            "release-version-mismatch")
    require(isinstance(value["sourceCommit"], str) and SOURCE.fullmatch(value["sourceCommit"]),
            "release-source-identity")
    require(value["target"] == TARGET and value["platform"] == PLATFORM, "unsupported-release-platform")
    require(set(value["toolchain"]) == {"rust", "lockSha256"}
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["toolchain"]["rust"])
            and SHA256.fullmatch(value["toolchain"]["lockSha256"]), "release-toolchain-identity")
    engine = value["engine"]
    require(set(engine) == {"wasmtimeVersion", "hostAbiProfile", "compilerSha256", "dynamicDependencies"}
            and isinstance(engine["wasmtimeVersion"], str) and isinstance(engine["hostAbiProfile"], str)
            and SHA256.fullmatch(engine["compilerSha256"]), "release-engine-identity")
    require(isinstance(engine["dynamicDependencies"], list)
            and set(engine["dynamicDependencies"]) <= {"libc.so.6", "libgcc_s.so.1", "libm.so.6",
                                                       "libpthread.so.0", "libdl.so.2", "librt.so.1"},
            "unsupported-dynamic-dependency")
    compatibility = value["compatibility"]
    require(set(compatibility) == {"installerFormat", "nodeConfigFormat", "migration", "upgradeFrom"}
            and compatibility["installerFormat"] == 1 and compatibility["nodeConfigFormat"] == 1
            and compatibility["migration"] == "none", "unsupported-release-format")
    require(isinstance(compatibility["upgradeFrom"], list) and len(compatibility["upgradeFrom"]) <= 16,
            "upgrade-policy-limit")
    for predecessor in compatibility["upgradeFrom"]:
        require(set(predecessor) == {"version", "sourceCommit", "archiveSha256"}, "upgrade-policy-members")
        version(predecessor["version"])
        require(SOURCE.fullmatch(predecessor["sourceCommit"]) and SHA256.fullmatch(predecessor["archiveSha256"]),
                "upgrade-policy-identity")
    for key, name in (("archive", f"lsf-{selected}-{TARGET}.tar.gz"), ("bootstrap", "lsf-install.pyz")):
        entry = value[key]
        require(set(entry) == {"name", "size", "sha256"} and entry["name"] == name
                and type(entry["size"]) is int and 0 < entry["size"] <= files.MAX_FILE
                and SHA256.fullmatch(entry["sha256"]), "release-artifact-identity")
    entries = value["files"]
    require(isinstance(entries, list) and len(REQUIRED) <= len(entries) <= 4096, "release-inventory-limit")
    names = set()
    total = 0
    for entry in entries:
        require(set(entry) == {"path", "size", "sha256", "mode"}, "release-file-members")
        name = relative(entry["path"])
        require(name not in names, "duplicate-release-file")
        names.add(name)
        require(type(entry["size"]) is int and 0 <= entry["size"] <= files.MAX_FILE
                and SHA256.fullmatch(entry["sha256"]), "release-file-identity")
        require(entry["mode"] == (0o755 if name in {"bin/latent", "bin/latentd", "bin/latent-aot-compiler"}
                                  else 0o644), "release-file-mode")
        total += entry["size"]
    require(total <= 1_073_741_824 and REQUIRED <= names, "release-inventory-incomplete-or-large")
    require(not any("/".join(name.split("/")[:depth]) in names for name in names
                    for depth in range(1, len(name.split("/")))), "release-path-conflict")
    compiler = next(entry for entry in entries if entry["path"] == "bin/latent-aot-compiler")
    bootstrap = next(entry for entry in entries if entry["path"] == "lsf-install.pyz")
    require(compiler["sha256"] == engine["compilerSha256"]
            and bootstrap["sha256"] == value["bootstrap"]["sha256"]
            and bootstrap["size"] == value["bootstrap"]["size"], "release-tool-identity-mismatch")
    return value


def authenticate(checksums: bytes, signature: bytes, key: Path) -> str:
    require(len(checksums) <= 8192 and len(signature) == 64, "signature-input-limit")
    with files.regular(key, 16384, owners={0, os.geteuid()}) as key_fd:
        with tempfile.TemporaryFile() as sum_file, tempfile.TemporaryFile() as signature_file:
            sum_file.write(checksums)
            sum_file.flush()
            signature_file.write(signature)
            signature_file.flush()
            key_name = f"/proc/self/fd/{key_fd}"
            status, der = execute(["/usr/bin/openssl", "pkey", "-pubin", "-in", key_name,
                                   "-pubout", "-outform", "DER"], pass_fds=(key_fd,), maximum=16384)
            require(status == 0 and len(der) == 44 and der[:12] == bytes.fromhex("302a300506032b6570032100"),
                    "ed25519-publisher-key-required")
            os.lseek(key_fd, 0, os.SEEK_SET)
            status, _output = execute([
                "/usr/bin/openssl", "pkeyutl", "-verify", "-pubin", "-inkey", key_name, "-rawin",
                "-in", f"/proc/self/fd/{sum_file.fileno()}",
                "-sigfile", f"/proc/self/fd/{signature_file.fileno()}",
            ], pass_fds=(key_fd, sum_file.fileno(), signature_file.fileno()), maximum=16384)
            require(status == 0, "publisher-signature-rejected")
    return hashlib.sha256(der).hexdigest()


@dataclass(frozen=True)
class VerifiedRelease:
    metadata: dict
    archive_fd: int
    publisher: str
    checksums: bytes
    signature: bytes


@contextmanager
def release(root: Path, selected: str, key: Path):
    version(selected)
    files.absolute(root)
    sums = files.read(root / "SHA256SUMS", 8192)
    signature = files.read(root / "SHA256SUMS.sig", 64)
    publisher = authenticate(sums, signature, key)
    try:
        lines = sums.decode("ascii").splitlines(keepends=True)
    except UnicodeDecodeError:
        lines = []
    expected_names = {"release.json", "lsf-install.pyz", f"lsf-{selected}-{TARGET}.tar.gz"}
    expected = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9.+_-]+)\n", line)
        require(match is not None and match[2] in expected_names and match[2] not in expected,
                "signed-checksum-format")
        expected[match[2]] = match[1]
    require(set(expected) == expected_names, "signed-checksum-inventory")
    with ExitStack() as opened:
        descriptors = {}
        for name in sorted(expected):
            descriptor = opened.enter_context(files.regular(root / name))
            actual, _size = files.digest_fd(descriptor)
            require(actual == expected[name], "signed-artifact-digest-mismatch")
            descriptors[name] = descriptor
        data = os.read(descriptors["release.json"], 1_048_577)
        metadata = manifest(document(data), selected)
        for entry in (metadata["archive"], metadata["bootstrap"]):
            require(entry["sha256"] == expected[entry["name"]]
                    and os.fstat(descriptors[entry["name"]]).st_size == entry["size"],
                    "manifest-artifact-mismatch")
        yield VerifiedRelease(metadata, descriptors[metadata["archive"]["name"]], publisher, sums, signature)

"""Offline GitHub/Sigstore verification using independently provisioned trust."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile

from .common import document, encode, execute, require
from . import files

TARGET = "x86_64-unknown-linux-gnu"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = "KirilsTurkins/latent-service-fabric"
ISSUER = "https://token.actions.githubusercontent.com"
RELEASE_WORKFLOW = ".github/workflows/native-runtime-release.yml"
CANDIDATE_WORKFLOW = ".github/workflows/native-runtime.yml"
PREDICATE = "https://slsa.dev/provenance/v1"
PLATFORM = {"osId": "ubuntu", "osVersion": "24.04", "minimumKernel": "6.8",
            "minimumGlibc": "2.39", "cpuFeatures": ["sse2"], "pythonMinimum": "3.12"}
DEVELOPMENT_TEST = {"formatVersion": 1, "purpose": "disposable-development-tests",
                    "features": ["latentd/development-test-node"], "fixtures": ["guest-clock-v1"]}
REQUIRED = {"bin/latent", "bin/latentd", "bin/latent-aot-compiler", "lsf-install.pyz",
            "systemd/lsf.service", "config/local-experimental-v1.json",
            "config/external-capsule-v1.json", "LICENSE", "NOTICE", "INSTALL.md",
            "sbom.spdx.json", "build-provenance.json", "release-source.json",
            "examples/echo/echo-capsule.wasm", "examples/echo/capsule.json",
            "examples/echo/contracts.json", "examples/echo/deployment.json", "examples/echo/input.json",
            "examples/echo/wit/echo.wit", "examples/echo/wit/context.wit", "examples/echo/wit/log.wit"}


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
    require(set(value) - {"developmentTest"} == {"schemaVersion", "version", "sourceCommit", "target", "toolchain",
                           "engine", "platform", "compatibility", "archive", "bootstrap", "files"},
            "release-manifest-members")
    if "developmentTest" in value:
        fixture = value["developmentTest"]
        require(isinstance(fixture, dict) and type(fixture.get("formatVersion")) is int
                and fixture == DEVELOPMENT_TEST, "development-test-candidate-profile")
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
                                                       "libpthread.so.0", "libdl.so.2", "librt.so.1", "ld-linux-x86-64.so.2"},
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


def publisher_policy(value: dict, selected: str, allow_candidate: bool = False) -> dict:
    require(set(value) == {"schemaVersion", "repository", "workflow", "sourceRef", "sourceCommit", "version", "purpose"},
            "publisher-policy-members")
    require(value["schemaVersion"] == "latent.native-publisher-policy.v1" and value["repository"] == REPOSITORY
            and value["version"] == version(selected) and isinstance(value["sourceCommit"], str)
            and SOURCE.fullmatch(value["sourceCommit"]), "publisher-policy-exact-source-required")
    if value["purpose"] == "release":
        require(value["workflow"] == RELEASE_WORKFLOW and value["sourceRef"] == "refs/tags/" + selected,
                "publisher-policy-release-workflow-and-tag-required")
    else:
        require(allow_candidate and value["purpose"] == "candidate" and value["workflow"] == CANDIDATE_WORKFLOW
                and isinstance(value["sourceRef"], str) and len(value["sourceRef"]) <= 240
                and re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*", value["sourceRef"])
                and ".." not in value["sourceRef"] and "//" not in value["sourceRef"],
                "candidate-is-not-a-release-explicit-test-policy-required")
    return value


def publisher_id(policy: dict) -> str:
    identity = {name: policy[name] for name in ("repository", "workflow", "purpose")}
    return hashlib.sha256(encode({**identity, "issuer": ISSUER})).hexdigest()


def development_publisher(metadata: dict, policy: dict) -> None:
    require("developmentTest" not in metadata or policy["purpose"] == "candidate",
            "development-test-artifact-is-not-a-release")


def verification_command(verifier: str, checksums: Path, attestation: Path, roots: Path, policy: dict) -> list[str]:
    return [verifier, "attestation", "verify", str(checksums), "--bundle", str(attestation),
            "--custom-trusted-root", str(roots), "--repo", REPOSITORY, "--hostname", "github.com",
            "--cert-identity", f"https://github.com/{REPOSITORY}/{policy['workflow']}@{policy['sourceRef']}",
            "--cert-oidc-issuer", ISSUER, "--source-ref", policy["sourceRef"],
            "--source-digest", policy["sourceCommit"], "--signer-digest", policy["sourceCommit"],
            "--deny-self-hosted-runners", "--predicate-type", PREDICATE, "--digest-alg", "sha256", "--format", "json"]


@dataclass(frozen=True)
class PublisherTrust:
    policy: Path
    roots: Path
    verifier: Path = Path("/usr/bin/gh")
    allow_candidate: bool = False


def authenticate(checksums: bytes, attestation: bytes, trust: PublisherTrust, policy: dict) -> dict:
    require(0 < len(checksums) <= 8192 and 0 < len(attestation) <= 1_048_576, "attestation-input-limit")
    roots = files.read(trust.roots, 262144, owners={0, os.geteuid()})
    with files.regular(trust.verifier, 134_217_728, owners={0, os.geteuid()}) as verifier_fd:
        verifier_sha256, _size = files.digest_fd(verifier_fd)
        require(os.fstat(verifier_fd).st_mode & 0o111, "independently-provisioned-gh-executable-required")
        with tempfile.TemporaryDirectory(prefix="lsf-verify-") as temporary:
            root = Path(temporary)
            environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": temporary,
                           "GH_CONFIG_DIR": str(root / "gh"), "GH_HOST": "github.com", "NO_COLOR": "1",
                           "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
            verifier_name = f"/proc/self/fd/{verifier_fd}"
            status, observed = execute([verifier_name, "--version"], pass_fds=(verifier_fd,),
                                       environment=environment, maximum=4096)
            match = re.match(rb"gh version ([0-9]+)\.([0-9]+)\.([0-9]+)\b", observed)
            require(status == 0 and match and tuple(int(part) for part in match.groups()) >= (2, 96, 0),
                    "independently-provisioned-gh-2.96.0-or-newer-required")
            for name, data in (("SHA256SUMS", checksums), ("attestation.json", attestation), ("trusted_root.jsonl", roots)):
                files.create(root / name, data)
            command = verification_command(verifier_name, root / "SHA256SUMS", root / "attestation.json",
                                           root / "trusted_root.jsonl", policy)
            status, _output = execute(command, pass_fds=(verifier_fd,), environment=environment,
                                      timeout=60, maximum=2_097_152)
            require(status == 0, "publisher-attestation-rejected-check-independent-root-and-exact-identity-policy")
    return {"method": "github-artifact-attestation", "policy": policy,
            "issuer": ISSUER, "predicateType": PREDICATE, "githubHostedRunnerRequired": True,
            "verifierVersion": ".".join(part.decode() for part in match.groups()),
            "verifierSha256": verifier_sha256, "trustedRootSha256": hashlib.sha256(roots).hexdigest(),
            "attestationSha256": hashlib.sha256(attestation).hexdigest(),
            "checksumsSha256": hashlib.sha256(checksums).hexdigest()}


@dataclass(frozen=True)
class VerifiedRelease:
    metadata: dict
    archive_fd: int
    publisher: str
    checksums: bytes
    attestation: bytes
    authentication: dict


@contextmanager
def release(root: Path, selected: str, trust: PublisherTrust):
    version(selected)
    files.absolute(root)
    for path in (trust.policy, trust.roots, trust.verifier):
        require(not files.absolute(path).is_relative_to(root), "publisher-trust-must-be-provisioned-separately-from-bundle")
    policy = publisher_policy(document(files.read(trust.policy, 8192, owners={0, os.geteuid()})),
                              selected, trust.allow_candidate)
    sums = files.read(root / "SHA256SUMS", 8192)
    attestation = files.read(root / "SHA256SUMS.sigstore.json", 1_048_576)
    authentication = authenticate(sums, attestation, trust, policy)
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
        development_publisher(metadata, policy)
        require(metadata["sourceCommit"] == policy["sourceCommit"], "attested-release-source-mismatch")
        for entry in (metadata["archive"], metadata["bootstrap"]):
            require(entry["sha256"] == expected[entry["name"]]
                    and os.fstat(descriptors[entry["name"]]).st_size == entry["size"],
                    "manifest-artifact-mismatch")
        yield VerifiedRelease(metadata, descriptors[metadata["archive"]["name"]], publisher_id(policy),
                              sums, attestation, authentication)

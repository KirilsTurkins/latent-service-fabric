"""Authenticate developer artifacts using the runtime's exact-source identity contract."""
from __future__ import annotations

from contextlib import ExitStack
import io
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from tools.native_runtime.verify import verification_command, REPOSITORY, SOURCE
from . import paths, process
from .common import DevError, HOST_ABI, decode, digest, encode, members, require, sha

MAX_BUNDLE = 1024 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_MANIFEST = 2 * 1024 * 1024
WORKFLOW = ".github/workflows/developer-tools.yml"
TARGETS = {"windows-x86_64", "linux-x86_64", "linux-x86_64-wsl-rootfs"}


def policy(value: dict, version: str, *, allow_candidate: bool) -> dict:
    members(value, {"schemaVersion", "repository", "workflow", "sourceRef", "sourceCommit", "version", "purpose"})
    require(value["schemaVersion"] == "latent.native-publisher-policy.v1" and value["repository"] == REPOSITORY
            and value["workflow"] == WORKFLOW and value["version"] == version
            and isinstance(value["sourceCommit"], str) and SOURCE.fullmatch(value["sourceCommit"]),
            "developer-publisher-exact-source-required")
    # No new public release authorization. This workflow emits candidates only.
    require(allow_candidate and value["purpose"] == "candidate" and isinstance(value["sourceRef"], str)
            and re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}", value["sourceRef"])
            and ".." not in value["sourceRef"] and "//" not in value["sourceRef"],
            "explicit-independent-candidate-policy-required")
    return value


def manifest(value: dict, *, target: str, version: str, commit: str) -> dict:
    members(value, {"schemaVersion", "version", "sourceCommit", "target", "hostAbi", "protocol", "archive",
                    "files", "licenses", "sbom"})
    require(value["schemaVersion"] == "latent.dev.bundle.v1" and value["version"] == version
            and value["sourceCommit"] == commit, "developer-bundle-identity")
    require(target in TARGETS and value["target"] == target, "developer-bundle-target")
    require(value["hostAbi"] == HOST_ABI and value["protocol"] == "latent.dev.protocol.v1", "developer-bundle-abi")
    archive = members(value["archive"], {"name", "size", "sha256"})
    paths.relative(archive["name"])
    require("/" not in archive["name"] and type(archive["size"]) is int
            and 0 < archive["size"] <= MAX_BUNDLE, "developer-archive-limit")
    sha(archive["sha256"])
    require(isinstance(value["files"], list) and 0 < len(value["files"]) <= MAX_ENTRIES, "developer-inventory-limit")
    names, aliases, total = set(), set(), 0
    for entry in value["files"]:
        members(entry, {"path", "size", "sha256", "executable"})
        name = paths.relative(entry["path"])
        require(paths.alias(name) not in aliases, "developer-inventory-alias")
        names.add(name)
        aliases.add(paths.alias(name))
        sha(entry["sha256"])
        require(type(entry["size"]) is int and 0 <= entry["size"] <= MAX_BUNDLE
                and type(entry["executable"]) is bool, "developer-entry-limit")
        total += entry["size"]
    require(total <= MAX_BUNDLE * 2, "developer-expanded-byte-limit")
    require(isinstance(value["licenses"], list) and value["licenses"] and set(value["licenses"]) <= names
            and value["sbom"] in names, "developer-sbom-and-licenses-required")
    require(not any("/".join(name.split("/")[:n]) in names for name in names for n in range(1, len(name.split("/")))),
            "developer-file-directory-collision")
    return value


def cached(root: Path) -> dict:
    value = decode(paths.read(root, "verified-bundle.json", MAX_MANIFEST), MAX_MANIFEST)
    return manifest(value, target=value.get("target"), version=value.get("version"), commit=value.get("sourceCommit"))


def authenticate(root: Path, selected_policy: Path, roots: Path, verifier: Path, verifier_sha256: str,
                 *, target: str, version: str, allow_candidate: bool) -> dict:
    policy_value = policy(decode(paths.read(selected_policy.parent, selected_policy.name)), version,
                          allow_candidate=allow_candidate)
    files = {name: paths.read(root, name, maximum) for name, maximum in
             (("SHA256SUMS", 8192), ("attestation.json", 1048576), ("developer-bundle.json", MAX_MANIFEST))}
    manifest_value = manifest(decode(files["developer-bundle.json"], MAX_MANIFEST), target=target, version=version,
                              commit=policy_value["sourceCommit"])
    archive = manifest_value["archive"]
    expected = {"developer-bundle.json": digest(files["developer-bundle.json"])[7:], archive["name"]: archive["sha256"][7:]}
    require(files["SHA256SUMS"] == "".join(f"{checksum}  {name}\n" for name, checksum in sorted(expected.items())).encode(),
            "developer-checksum-inventory")
    # Independently provisioned verifier remains held against replacement on Windows.
    with paths.opened(verifier.parent, verifier.name), tempfile.TemporaryDirectory(prefix="lsf-dev-verify-") as temporary:
        require(digest(paths.read(verifier.parent, verifier.name, 134217728)) == sha(verifier_sha256),
                "independent-verifier-digest-mismatch")
        verification_root = Path(temporary)
        for name, raw in files.items():
            paths.write_new(verification_root / name, raw)
        paths.write_new(verification_root / "trusted_root.jsonl", paths.read(roots.parent, roots.name, 262144))
        environment = process.environment(verification_root)
        environment.update({"GH_CONFIG_DIR": str(verification_root / "gh"), "GH_PROMPT_DISABLED": "1",
                            "GH_NO_UPDATE_NOTIFIER": "1", "GH_HOST": "github.com"})
        observed = process.run([str(verifier), "--version"], verification_root, env=environment, maximum=4096)
        match = re.match(rb"gh version (\d+)\.(\d+)\.(\d+)\b", observed.stdout)
        require(observed.returncode == 0 and match and tuple(map(int, match.groups())) >= (2, 96, 0),
                "independent-gh-2-96-or-newer-required")
        verified = process.run(verification_command(str(verifier), verification_root / "SHA256SUMS",
            verification_root / "attestation.json", verification_root / "trusted_root.jsonl", policy_value),
            verification_root, env=environment, timeout=60, maximum=2097152)
        require(verified.returncode == 0, "developer-publisher-attestation-rejected")
    return manifest_value


def extract(root: Path, selected: dict, destination: Path) -> None:
    archive = selected["archive"]
    with paths.opened(root, archive["name"]) as descriptor:
        import os
        import hashlib
        hasher = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            require(size <= archive["size"], "developer-archive-size")
            hasher.update(chunk)
        require(size == archive["size"] and "sha256:" + hasher.hexdigest() == archive["sha256"],
                "developer-archive-digest")
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "rb") as source, zipfile.ZipFile(source) as zipped:
            entries = zipped.infolist()
            require(len(entries) == len(selected["files"]), "developer-archive-inventory")
            expected = {entry["path"]: entry for entry in selected["files"]}
            seen = set()
            for entry in entries:
                require(entry.filename in expected and entry.filename not in seen and not entry.is_dir(),
                        "developer-archive-member")
                require(stat.S_IFMT(entry.external_attr >> 16) in {0, stat.S_IFREG}
                        and not entry.flag_bits & 1, "developer-archive-type")
                record = expected[entry.filename]
                require(entry.file_size == record["size"], "developer-archive-member-size")
                seen.add(entry.filename)
            paths.new_directory(destination)
            for entry in entries:
                record = expected[entry.filename]
                path = destination / entry.filename
                current = destination
                for part in Path(entry.filename).parts[:-1]:
                    current /= part
                    if not current.exists():
                        paths.new_directory(current)
                # Read bounded chunks; compressed bombs cannot exceed signed sizes.
                hasher = hashlib.sha256()
                copied = 0
                with zipped.open(entry) as source, path.open("xb") as output:
                    while raw := source.read(min(1024 * 1024, record["size"] + 1 - copied)):
                        copied += len(raw)
                        require(copied <= record["size"], "developer-expanded-byte-limit")
                        hasher.update(raw)
                        output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                require(copied == record["size"] and "sha256:" + hasher.hexdigest() == record["sha256"],
                        "developer-member-digest")
                if os.name != "nt":
                    path.chmod(0o700 if record["executable"] else 0o600)
            paths.write_new(destination / "verified-bundle.json", encode(selected))

"""Capture pinned Java/.NET compiler distributions and their locked dependencies."""
from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import zipfile

from tools.dev_distribution import file_digest
from tools.dev_managed_tools import MAX_BYTES, MAX_FILE, MAX_FILES, manifest
from tools.dev_workflow import paths
from tools.dev_workflow.common import digest, encode, require

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "wasi-sdk": {"url": "https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-29/"
        "wasi-sdk-29.0-x86_64-linux.tar.gz", "version": "29.0", "maximum": 119441678,
        "sha256": "sha256:87d1d1a2879d139cdc624b968efad3d4a97b8078cdff95e63ac88ecafd1a0171"},
    "jdk": {"url": "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/"
        "OpenJDK25U-jdk_x64_linux_hotspot_25.0.4.1_1.tar.gz", "version": "25.0.4.1+1", "maximum": 141329719,
        "sha256": "sha256:dbb698396d478e7fa2b1e50f4103324b2a99b90569ee27c33f2261f9215cf41e"},
    "gradle": {"url": "https://services.gradle.org/distributions/gradle-9.1.0-bin.zip", "version": "9.1.0",
        "maximum": 134528013, "sha256": "sha256:a17ddd85a26b6a7f5ddb71ff8b05fc5104c0202c6e64782429790c933686c806"},
    "dotnet": {"url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.100/dotnet-sdk-10.0.100-linux-x64.tar.gz",
        "version": "10.0.100", "maximum": 239125653,
        "sha256": "sha256:a9631cc6bfad0ef167383ac654b54254bad95a6fb4b6f4309fa78f558055e637"},
}


def sources(language: str) -> dict:
    require(language in {"java", "dotnet"}, "managed-distribution-language")
    names = ("wasi-sdk", "jdk", "gradle") if language == "java" else ("wasi-sdk", "dotnet")
    return {name: SOURCES[name] for name in names}


def dependency_packages(language: str) -> list[dict]:
    """Describe the exact declared compiler locks alongside the file inventory."""
    rows = {}
    if language == "java":
        lock = json.loads((ROOT / "sdk/java-guest/feasibility/dependencies.lock.json").read_bytes())
        for entry in lock["artifacts"]:
            parts = entry["path"].split("/")
            name, version = ".".join(parts[:-3]) + ":" + parts[-3], parts[-2]
            rows[name + "/" + version] = (name, version, lock["maven"] + entry["path"], "SHA256", entry["sha256"])
    else:
        lock = json.loads((ROOT / "sdk/dotnet-guest/probes/smoke/packages.lock.json").read_bytes())
        for target in lock["dependencies"].values():
            for name, entry in target.items():
                rows[name + "/" + entry["resolved"]] = (name, entry["resolved"], "NOASSERTION", "SHA512",
                                                        base64.b64decode(entry["contentHash"], validate=True).hex())
    return [{"SPDXID": "SPDXRef-managed-dependency-" + hashlib.sha256(key.encode()).hexdigest(),
        "name": name, "versionInfo": version, "downloadLocation": location, "filesAnalyzed": False,
        "licenseDeclared": "NOASSERTION", "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION",
        "checksums": [{"algorithm": algorithm, "checksumValue": checksum}],
        "comment": "Exact declared compiler dependency. sdk/managed-inputs.json identifies the files actually redistributed; notices remain with those files."}
        for key, (name, version, location, algorithm, checksum) in sorted(rows.items())]


def extract(archive: Path, destination: Path, name: str, *, source: dict | None = None) -> Path:
    """Builder-only upstream extraction, after exact release checksum verification."""
    require(file_digest(archive)[0] == (source or SOURCES[name])["sha256"], "managed-upstream-digest")
    destination.mkdir(mode=0o700)
    total = 0
    if name == "gradle":
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            require(len(entries) <= MAX_FILES, "managed-upstream-file-limit")
            for entry in entries:
                relative = paths.relative(entry.filename.rstrip("/"))
                total += entry.file_size
                require(total <= MAX_BYTES and entry.file_size <= MAX_FILE, "managed-upstream-size-limit")
                mode = entry.external_attr >> 16
                require(not stat.S_ISLNK(mode), "managed-upstream-zip-link")
                target = destination / relative
                if entry.is_dir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with package.open(entry) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    target.chmod(0o700 if mode & 0o111 else 0o600)
    else:
        with tarfile.open(archive, "r:*") as package:
            entries = package.getmembers()
            require(len(entries) <= MAX_FILES, "managed-upstream-file-limit")
            for entry in entries:
                total += entry.size
                require(total <= MAX_BYTES and entry.size <= MAX_FILE, "managed-upstream-size-limit")
                # data_filter rejects devices and links escaping this staging
                # root. Packing below materializes all retained internal links.
                require(entry.isdir() or entry.isfile() or entry.issym() or entry.islnk(), "managed-upstream-type")
            package.extractall(destination, members=entries, filter="data")
    if name == "dotnet":
        return destination
    children = list(destination.iterdir())
    require(len(children) == 1 and children[0].is_dir(), "managed-upstream-root")
    return children[0]


def pack(roots: dict[str, Path], sdk: Path) -> dict:
    """Flatten only internal links; installable inputs contain regular files only."""
    files, total = [], 0
    with zipfile.ZipFile(sdk / "managed.zip", "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for prefix, root in sorted(roots.items()):
            root = root.resolve(strict=True)
            pending = [(root, prefix, frozenset())]
            while pending:
                directory, label, ancestors = pending.pop()
                resolved = directory.resolve(strict=True)
                require(resolved.is_relative_to(root) and resolved not in ancestors, "managed-compiler-link-cycle-or-escape")
                for source in sorted(directory.iterdir()):
                    target = source.resolve(strict=True)
                    require(target.is_relative_to(root), "managed-compiler-link-escape")
                    name = paths.relative(label + "/" + source.name)
                    if source.is_dir():
                        pending.append((source, name, ancestors | {resolved}))
                        continue
                    require(source.is_file(), "managed-compiler-special-file")
                    size = source.stat().st_size
                    total += size
                    require(size <= MAX_FILE and total <= MAX_BYTES and len(files) < MAX_FILES, "managed-compiler-capture-limit")
                    executable = bool(source.stat().st_mode & 0o111)
                    entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFREG | (0o700 if executable else 0o600)) << 16
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    checksum, copied = hashlib.sha256(), 0
                    with source.open("rb") as incoming, archive.open(entry, "w") as output:
                        while raw := incoming.read(1024 * 1024):
                            copied += len(raw)
                            require(copied <= size, "managed-compiler-input-changed")
                            checksum.update(raw)
                            output.write(raw)
                    require(copied == size, "managed-compiler-input-changed")
                    files.append({"path": name, "sha256": "sha256:" + checksum.hexdigest(), "size": size, "executable": executable})
    value = {"schemaVersion": "latent.dev.managed-tools.v1", "files": files}
    value["identity"] = digest(encode(value))
    manifest(value)
    (sdk / "managed-inputs.json").write_bytes(encode(value))
    return value


def prepare(payload: Path, output: Path, language: str, download) -> dict:
    require(language in {"java", "dotnet"}, "managed-distribution-language")
    stage = output / "managed-source"
    stage.mkdir(mode=0o700)
    roots = {}
    for name, source in sources(language).items():
        archive = output / (name + ".archive")
        download(archive, source)
        roots[name] = extract(archive, stage / name, name)
    original = dict(os.environ)
    try:
        os.environ["PATH"] = str(payload / "sdk/bin") + os.pathsep + original["PATH"]
        if language == "java":
            from tools.java_capsule_project import create
            from tools.java_guest.compiler import Compiler
            project = create(output / "managed-dependency-project", "greeting")
            os.environ.update(JAVA_HOME=str(roots["jdk"]), PATH=str(roots["jdk"] / "bin") + os.pathsep + os.environ["PATH"])
            compiler = Compiler(output / "managed-dependencies", roots["wasi-sdk"], gradle=str(roots["gradle"] / "bin/gradle"))
            compiler.compile(project / "src", project / "wit", "examples:greeting/service@1.0.0", output / "managed-dependency-build")
            compiler.check_unchanged()
            roots["gradle-cache"] = compiler.directory / "gradle-home/caches/modules-2"
        else:
            from tools.dotnet_capsule import install
            os.environ["PATH"] = str(roots["dotnet"]) + os.pathsep + os.environ["PATH"]
            installed = install(output / "managed-dependencies", roots["wasi-sdk"])
            retained = stage / "tools"
            retained.mkdir(mode=0o700)
            for name in ("packages", "package-hash", "package-hash-source"):
                shutil.copytree(installed / name, retained / name)
            for name in ("runtime.wasm", "runtime-inputs.json", "wasi-sdk.json"):
                shutil.copyfile(installed / name, retained / name)
            roots["tools"] = retained
        value = pack(roots, payload / "sdk")
        # Full upstream notices, NuGet archives and Maven dependency metadata
        # remain inside the captured archive, with their exact byte inventory.
        license_dir = payload / "licenses/managed"
        license_dir.mkdir(parents=True)
        (license_dir / "README.txt").write_text(
            "Compiler license and notice files are retained in sdk/managed.zip.\n"
            "sdk/managed-inputs.json binds every retained file and executable.\n", encoding="utf-8")
        lock = ROOT / ("sdk/java-guest/feasibility/dependencies.lock.json" if language == "java"
                       else "sdk/dotnet-guest/probes/smoke/packages.lock.json")
        shutil.copyfile(lock, license_dir / "dependencies.lock.json")
        return value
    finally:
        os.environ.clear()
        os.environ.update(original)

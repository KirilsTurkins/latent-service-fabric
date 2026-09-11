"""Bounded, byte-preserving build import and cached-base image preparation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
from urllib.parse import quote
import uuid

from tools.artifact_identity_runner.files import fingerprint, reference
from tools.optimization_evidence.common import decode, read_json, verify_artifact
from . import build, fixtures, images
from .model import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES

BENCH = Path("/bench")
MAXIMUM_TAR = 512 * 1024**2
MAXIMUM_SCRATCH = 1024**3
METADATA_RESERVE = 64 * 1024**2
OWNER_LABEL = "latent.benchmark.owner"
ROLE_LABEL = "latent.benchmark.role"


def _check(condition, message):
    if not condition:
        raise ValueError("docker-setup-" + message)


def _regular(path):
    info = path.lstat()
    _check(stat.S_ISREG(info.st_mode) and not path.is_symlink()
           and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
           "regular-file-required")
    return info


def _root(path, *, fresh=False):
    _check(isinstance(path, Path) and path.is_absolute() and path.parent == BENCH
           and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", path.name) is not None
           and path.name != "scratch", "owned-root-path")
    _check(not any(item.is_symlink() for item in (path, *path.parents)), "root-symlink")
    _check(not fresh or not path.exists(), "root-not-fresh")


def _space(path, additional):
    _check(shutil.disk_usage(path).free >= additional, "disk-reservation")


def _usage(root):
    """Metadata-only budget checks avoid repeatedly hashing retained executables."""
    total, count, pending = 0, 0, [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        _check(not directory.is_symlink() and directory.is_dir(), "retained-directory")
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                _check(count <= MAX_FILES, "retained-file-count")
                info = entry.stat(follow_symlinks=False)
                _check(not stat.S_ISLNK(info.st_mode)
                       and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                       "retained-entry-type")
                if stat.S_ISDIR(info.st_mode):
                    _check(depth < 12, "retained-depth-bound")
                    pending.append((Path(entry.path), depth + 1))
                else:
                    _check(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE_BYTES, "retained-file-bound")
                    total += info.st_size
                    _check(total <= MAX_TOTAL_BYTES, "retained-total-bound")
    return total, count


def _scratch(path, *, import_tar):
    """Only an import tar and one active context tar share this explicit budget."""
    directory = BENCH / "scratch"
    _check(not any(item.is_symlink() for item in (directory, *directory.parents)), "scratch-symlink")
    directory.mkdir(exist_ok=True)
    _check(path.parent == directory and not path.exists() and not path.is_symlink(), "scratch-not-fresh")
    rows = []
    with os.scandir(directory) as entries:
        for entry in entries:
            _check(len(rows) < 2, "scratch-file-count")
            item = Path(entry.path)
            info = _regular(item)
            _check(info.st_size <= MAXIMUM_TAR, "scratch-file-bound")
            _check(item.name.endswith(("-import.tar", "-context.tar")), "scratch-file-name")
            rows.append((item.name, info.st_size))
    _check(not any(name.endswith("-context.tar") for name, _ in rows), "previous-context-retained")
    _check(sum(name.endswith("-import.tar") for name, _ in rows) <= 1, "scratch-import-count")
    _check(not import_tar or not rows, "previous-import-retained")
    _check(sum(size for _, size in rows) + MAXIMUM_TAR <= MAXIMUM_SCRATCH, "scratch-total-bound")
    _space(directory, MAXIMUM_TAR)


def _bytes(root, path, data):
    _check(isinstance(data, bytes) and len(data) <= 8 * 1024**2, "metadata-file-bound")
    total, count = _usage(root)
    _check(total + len(data) <= MAX_TOTAL_BYTES and count + 4 <= MAX_FILES, "retained-output-bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(data)
    return reference(path, root)


def _json(root, path, value):
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode()
    return _bytes(root, path, data)


def _name(value):
    _check(isinstance(value, str) and 0 < len(value.encode()) <= 4096
           and not value.startswith("/") and "\\" not in value and ":" not in value
           and all(part not in ("", ".", "..", ".git", "target") for part in value.split("/"))
           and not any(ord(char) < 32 or ord(char) == 127 for char in value), "archive-member-path")
    return value


def _pax(data):
    result, position = {}, 0
    while position < len(data):
        space = data.find(b" ", position, position + 12)
        _check(space > position and data[position:space].isdigit(), "pax-length")
        length = int(data[position:space])
        end = position + length
        _check(space + 2 < end <= len(data) and data[end - 1:end] == b"\n", "pax-record")
        key, separator, value = data[space + 1:end - 1].partition(b"=")
        _check(separator == b"=" and key in (b"path", b"mtime", b"atime", b"ctime", b"uid", b"gid", b"uname", b"gname")
               and key not in result, "pax-field")
        result[key] = value.decode("utf-8")
        position = end
    return result


def _members(path, root_name):
    """Scan physical headers first, so even PAX metadata has a finite allocation."""
    size = _regular(path).st_size
    _check(1024 <= size <= MAXIMUM_TAR and size % 512 == 0, "archive-byte-bound")
    rows, seen, total, headers, pending = [], set(), 0, 0, None
    with path.open("rb") as source:
        while True:
            block = source.read(512)
            _check(len(block) == 512, "archive-truncated-header")
            if block == bytes(512):
                _check(pending is None and source.read(512) == bytes(512), "archive-end-marker")
                while tail := source.read(65536):
                    _check(not any(tail), "archive-trailing-content")
                break
            headers += 1
            _check(headers <= 2 * MAX_FILES, "archive-header-bound")
            try:
                info = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            except (tarfile.TarError, UnicodeError, ValueError) as error:
                raise ValueError("docker-setup-archive-header") from error
            _check(info.size >= 0 and source.tell() + ((info.size + 511) // 512) * 512 <= size,
                   "archive-truncated-member")
            if info.type == tarfile.XHDTYPE:
                _check(pending is None and info.size <= 65536, "pax-byte-bound")
                pending = _pax(source.read(info.size))
                source.seek((-info.size) % 512, 1)
                continue
            _check(info.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE)
                   and not info.linkname and info.mode & ~0o777 == 0, "archive-member-type-or-mode")
            name = (pending or {}).get(b"path", info.name)
            pending = None
            name = name[:-1] if info.isdir() and name.endswith("/") else name
            _name(name)
            _check(name == root_name or name.startswith(root_name + "/"), "archive-root-name")
            relative = name[len(root_name) + 1:] if name != root_name else "."
            _check(relative not in seen and len(rows) < MAX_FILES, "archive-duplicate-or-count")
            seen.add(relative)
            _check(not info.isdir() or info.size == 0, "archive-directory-payload")
            _check(info.size <= MAX_FILE_BYTES, "archive-file-bound")
            total += info.size
            _check(total <= MAX_TOTAL_BYTES - METADATA_RESERVE, "archive-total-bound")
            rows.append({"path": relative, "kind": "directory" if info.isdir() else "file",
                         "mode": format(info.mode, "04o"), "bytes": str(info.size), "offset": source.tell()})
            source.seek(((info.size + 511) // 512) * 512, 1)
    _check(any(row["path"] == "." and row["kind"] == "directory" for row in rows), "archive-root-missing")
    return rows


def _member_bytes(archive, row, maximum):
    size = int(row["bytes"])
    _check(row["kind"] == "file" and size <= maximum, "manifest-byte-bound")
    with archive.open("rb") as source:
        source.seek(row["offset"])
        data = source.read(size)
    _check(len(data) == size, "archive-truncated-member")
    return data


def _closure(value):
    """No arbitrary receipt path can import a target cache or Git administration."""
    _check(isinstance(value, dict) and value.get("schema") == build.SCHEMA, "build-schema")
    expected = {}

    def add(row, path=None):
        _check(isinstance(row, dict) and set(row) == {"path", "sha256", "bytes"}, "artifact-reference")
        name = _name(row["path"])
        _check(path is None or name == path, "artifact-path-binding")
        _check(isinstance(row["sha256"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", row["sha256"])
               and isinstance(row["bytes"], str) and re.fullmatch(r"0|[1-9][0-9]{0,9}", row["bytes"])
               and int(row["bytes"]) <= MAX_FILE_BYTES, "artifact-identity")
        _check(name not in expected or expected[name] == row, "artifact-reference-conflict")
        expected[name] = row

    inputs = value.get("inputs")
    _check(isinstance(inputs, dict) and 1 <= len(inputs) <= 3500
           and all(name in inputs for name in build.SOURCE_FILES), "input-count")
    for name, row in inputs.items():
        _name(name)
        _check(name in build.SOURCE_FILES or name.endswith("Cargo.toml")
               or name.startswith("tools/") and name.endswith(".py")
               or any(name.startswith(prefix + "/") for prefix in build.SOURCE_PREFIXES), "input-scope")
        add(row, "source/" + name)
    _check(isinstance(value.get("executables"), dict) and set(value["executables"]) == set(images.BINARIES),
           "executable-set")
    for key, row in value["executables"].items():
        add(row, "binaries/" + images.BINARIES[key])
    add(value["component"], "component.wasm")
    add(value["log"], "build.log")
    fixture = value.get("fixtures")
    _check(isinstance(fixture, dict) and set(fixture) == {"schema", "base_component", "node_config", "token", "publications"}
           and fixture["schema"] == "latent.optimization.docker-fixtures.v1", "fixture-envelope")
    add(fixture["base_component"], "component.wasm")
    add(fixture["node_config"], "fixtures/node.json")
    add(fixture["token"], "fixtures/token")
    _check(isinstance(fixture["publications"], list) and len(fixture["publications"]) == 32, "publication-count")
    for index, row in enumerate(fixture["publications"]):
        _check(isinstance(row, dict) and set(row) == {"index", "service", "component", "capsule", "contracts", "deployment"}
               and type(row["index"]) is int and row["index"] == index
               and row["service"] == fixtures.SERVICES[index], "publication-binding")
        for key, path in (("component", f"component-{index}.wasm"), ("capsule", f"capsule-{index}.json"),
                          ("contracts", "contracts.json"), ("deployment", f"deployment-{index}.json")):
            add(row[key], "fixtures/" + path)
    return expected


def _extract(archive, destination, rows, expected):
    files = {row["path"] for row in rows if row["kind"] == "file"}
    _check(files == set(expected) | {"docker-builds.json", "build.log.process.json", "fixtures/fixtures.json"},
           "archive-file-set")
    directories = {"."}
    for name in files:
        directories.update(parent.as_posix() for parent in PurePosixPath(name).parents)
    _check({row["path"] for row in rows if row["kind"] == "directory"} == directories, "archive-directory-set")
    _space(destination, sum(int(row["bytes"]) for row in rows) + METADATA_RESERVE)
    result = []
    with archive.open("rb") as source:
        for row in sorted(rows, key=lambda item: (item["kind"] != "directory", item["path"])):
            path = destination / row["path"]
            if row["kind"] == "directory":
                path.mkdir(exist_ok=True)
                result.append({key: row[key] for key in ("path", "kind", "mode")})
                continue
            source.seek(row["offset"])
            left, digest = int(row["bytes"]), hashlib.sha256()
            with path.open("xb") as output:
                while left:
                    block = source.read(min(left, 65536))
                    _check(bool(block), "archive-truncated-member")
                    output.write(block)
                    digest.update(block)
                    left -= len(block)
            checksum = "sha256:" + digest.hexdigest()
            if row["path"] in expected:
                _check(expected[row["path"]] == {"path": row["path"], "sha256": checksum, "bytes": row["bytes"]},
                       "extracted-source-hash")
            path.chmod(int(row["mode"], 8))
            _check(fingerprint(path, MAX_FILE_BYTES) == (checksum, int(row["bytes"])), "extracted-copy-hash")
            _check(stat.S_IMODE(path.stat().st_mode) == int(row["mode"], 8), "extracted-copy-mode")
            result.append({key: row[key] for key in ("path", "kind", "mode", "bytes")} | {"sha256": checksum})
    for row in sorted((item for item in rows if item["kind"] == "directory"), key=lambda item: -len(item["path"])):
        path = destination / row["path"]
        path.chmod(int(row["mode"], 8))
        _check(stat.S_IMODE(path.stat().st_mode) == int(row["mode"], 8), "extracted-directory-mode")
    return sorted(result, key=lambda item: item["path"])


def import_build(engine, implementation_id, source_path, destination: Path, repository: Path):
    _root(destination, fresh=True)
    _check(isinstance(implementation_id, str) and re.fullmatch(r"[0-9a-f]{64}", implementation_id), "container-id")
    _check(isinstance(source_path, str) and source_path.startswith("/")
           and len(source_path.encode()) <= 4096 and "\\" not in source_path
           and all(part not in ("", ".", "..") for part in source_path[1:].split("/"))
           and not any(ord(char) < 32 or ord(char) == 127 for char in source_path)
           and source_path == str(PurePosixPath(source_path)) and PurePosixPath(source_path).name == destination.name,
           "source-directory")
    archive = BENCH / "scratch" / (destination.name + "-import.tar")
    _scratch(archive, import_tar=True)
    destination.mkdir()
    try:
        try:
            download = engine.download_archive(implementation_id, source_path, archive, maximum=MAXIMUM_TAR)
        finally:
            _json(destination, destination / "import/download.http.json", engine.last_receipt)
        checksum, length = fingerprint(archive, MAXIMUM_TAR)
        _check(download.get("connection_closed") is True and download.get("file_closed") is True
               and download.get("response_complete") is True and download.get("status") == 200
               and download.get("failure") is None
               and (download.get("response_sha256"), download.get("response_bytes")) == (checksum, str(length)),
               "archive-download-receipt")
        archive_ref = {"source_path": str(archive), "sha256": checksum, "bytes": str(length), "retained": True}
        _json(destination, destination / "import/archive.json", archive_ref)
        rows = _members(archive, destination.name)
        manifest_rows = [row for row in rows if row["path"] == "docker-builds.json"]
        _check(len(manifest_rows) == 1, "build-manifest-missing")
        value = decode(_member_bytes(archive, manifest_rows[0], 8 * 1024**2), 8 * 1024**2)
        members = _extract(archive, destination, rows, _closure(value))
        build.validate_receipt(value, destination)
        _check(read_json(destination / "fixtures/fixtures.json") == value["fixtures"], "fixture-sidecar")
        for name in ("app.Dockerfile", "client.Dockerfile"):
            relative = "tools/optimization-docker/" + name
            original = verify_artifact(destination, value["inputs"][relative], 65536)
            _check(fingerprint(original, 65536) == fingerprint(repository / relative, 65536), "recipe-source")
        _check(fingerprint(archive, MAXIMUM_TAR) == (checksum, length), "import-archive-changed")
        receipt = {"schema": "latent.optimization.docker-build-import.v1", "implementation_id": implementation_id,
                   "source_path": source_path, "destination": str(destination), "archive": archive_ref,
                   "download_http": reference(destination / "import/download.http.json", destination),
                   "build": reference(destination / "docker-builds.json", destination), "members": members}
        _json(destination, destination / "import.json", receipt)
        return receipt
    except BaseException as error:
        _json(destination, destination / "import/failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
        raise


def _api(engine, root, name, call, *, stream=False):
    """Persist exact HTTP bytes even if the Engine reports a stream error."""
    try:
        value, receipt = call()
    finally:
        suffix = ".body.jsonl" if stream else ".body.json"
        body_ref = _bytes(root, root / "images/requests" / (name + suffix), engine.last_body)
        http_ref = _json(root, root / "images/requests" / (name + ".http.json"), engine.last_receipt)
    _check(receipt.get("connection_closed") is True and receipt.get("response_complete") is True
           and receipt.get("failure") is None and receipt.get("status") == 200
           and (receipt.get("response_sha256"), receipt.get("response_bytes")) == (body_ref["sha256"], body_ref["bytes"]),
           "http-receipt")
    return value, receipt, http_ref, body_ref


def _context_tar(root, context, archive):
    directory = root / context["context"]
    inventory = fixtures.inventory(directory)
    expected = {"Dockerfile"} | {str(PurePosixPath(row["path"]).relative_to(context["context"]))
                               for row in context["executables"].values()}
    _check({row["path"] for row in inventory["entries"] if row["kind"] == "file"} == expected, "context-file-set")
    rows = [row for row in inventory["entries"] if row["path"] != "."]
    predicted = 1024 + sum(512 + ((int(row.get("bytes", "0")) + 511) // 512) * 512 for row in rows)
    predicted = ((predicted + tarfile.RECORDSIZE - 1) // tarfile.RECORDSIZE) * tarfile.RECORDSIZE
    _check(predicted <= MAXIMUM_TAR, "context-tar-bound")
    _scratch(archive, import_tar=False)
    with archive.open("xb") as output, tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as target:
        for row in rows:
            path = directory / row["path"]
            info = tarfile.TarInfo(row["path"])
            info.mode, info.uid, info.gid, info.mtime = int(row["mode"], 8), 0, 0, 0
            if row["kind"] == "directory":
                info.type = tarfile.DIRTYPE
                target.addfile(info)
            else:
                _check(row["path"] == "Dockerfile" or info.mode == 0o755, "context-executable-mode")
                info.size = int(row["bytes"])
                with path.open("rb") as source:
                    target.addfile(info, source)
    _check(fixtures.inventory(directory) == inventory, "context-source-changed")
    checksum, length = fingerprint(archive, MAXIMUM_TAR)
    _check(length == predicted, "context-tar-size")
    return {"source_path": str(archive), "sha256": checksum, "bytes": str(length)}, inventory["entries"]


def prepare_images(engine, buildroot: Path, repository: Path):
    _root(buildroot)
    _check(not (buildroot / "images.json").exists() and not (buildroot / "images").exists(), "images-not-fresh")
    value = build.validate_receipt(read_json(buildroot / "docker-builds.json"), buildroot)
    sizes = {key: int(row["bytes"]) for key, row in value["executables"].items()}
    added = sum(sizes.values()) + sizes["wrapper"] + 3 * 65536 + METADATA_RESERVE
    _check(_usage(buildroot)[0] + added <= MAX_TOTAL_BYTES, "images-reservation")
    _space(buildroot, added + MAXIMUM_TAR)
    contexts = images.prepare_contexts(value, buildroot, repository)
    owner = "lsf111-images-" + uuid.uuid4().hex[:20]
    result = {"schema": "latent.optimization.docker-images.v1", "owner": owner,
              "build": reference(buildroot / "docker-builds.json", buildroot), "images": {}, "builds": {}}
    try:
        version_http = _json(buildroot, buildroot / "images/requests/version.http.json", engine.version_receipt)
        version_body = _bytes(buildroot, buildroot / "images/requests/version.body.json", engine.version_body)
        result["engine"] = {"api_version": engine.api_version, "server_version": engine.server_version,
                            "version_http": version_http, "version_response": version_body}
        base, _, base_http, base_body = _api(engine, buildroot, "base-inspect", lambda: engine.request(
            "GET", "/images/" + quote(images.BASE, safe="") + "/json", maximum=2 * 1024**2))
        digest = images.BASE.split("@", 1)[1]
        _check(isinstance(base, dict) and base.get("Os") == "linux" and base.get("Architecture") == "amd64"
               and (digest in (base.get("Id"), (base.get("Descriptor") or {}).get("digest"))
                    or any(isinstance(item, str) and item.endswith("@" + digest) for item in base.get("RepoDigests", []))),
               "base-image-binding")
        result["base"] = {"requested": images.BASE, "inspect_http": base_http, "inspect_response": base_body}
        for kind in images.KINDS:
            archive = BENCH / "scratch" / (buildroot.name + "-" + kind + "-context.tar")
            archive_ref, members = _context_tar(buildroot, contexts[kind], archive)
            query = {"t": owner + ":" + kind, "labels": {OWNER_LABEL: owner, ROLE_LABEL: kind},
                     "dockerfile": "Dockerfile", "networkmode": "none", "pull": "0", "rm": "1",
                     "forcerm": "1", "version": "1", "platform": "linux/amd64"}
            _, http, http_ref, response_ref = _api(engine, buildroot, kind + "-build", lambda: engine.build(archive, query), stream=True)
            _check((http.get("request_sha256"), http.get("request_bytes")) == (archive_ref["sha256"], archive_ref["bytes"]),
                   "build-request-archive")
            inspected, _, inspect_http, inspect_body = _api(engine, buildroot, kind + "-inspect", lambda: engine.request(
                "GET", "/images/" + quote(query["t"], safe="") + "/json", maximum=2 * 1024**2))
            image = images.inspect_receipt(kind, inspected, contexts[kind])
            _check(image["config"].get("Labels", {}).get(OWNER_LABEL) == owner
                   and image["config"].get("Labels", {}).get(ROLE_LABEL) == kind, "image-owner-label")
            _check(fingerprint(archive, MAXIMUM_TAR) == (archive_ref["sha256"], int(archive_ref["bytes"])),
                   "context-archive-changed")
            row = {"context_archive": archive_ref, "context_members": members, "query": query,
                   "build_http": http_ref, "build_response": response_ref,
                   "inspect_http": inspect_http, "inspect_response": inspect_body}
            # This durable record makes no deletion claim. Only the final envelope,
            # written after successful unlink, declares the scratch tar unretained.
            consumed = _json(buildroot, buildroot / "images/requests" / (kind + "-consumed.json"),
                             {"image_id": image["image_id"], "build": row})
            archive.unlink()
            row["context_archive"] = {**archive_ref, "retained": False}
            row["consumed_receipt"] = consumed
            result["images"][kind], result["builds"][kind] = image, row
        _json(buildroot, buildroot / "images.json", result)
        return result
    except BaseException as error:
        _json(buildroot, buildroot / "images/failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
        raise

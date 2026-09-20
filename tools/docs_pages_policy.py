"""Pure, fail-closed policy for publishing an already tested static site.

The publisher owns these checks on the release branch. Candidate site code is
data here: no imports, package installation, shell commands or Markdown execution.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

REPOSITORY = "KirilsTurkins/latent-service-fabric"
SITE_URL = "https://kirilsturkins.github.io/latent-service-fabric/"
BASE_URL = "/latent-service-fabric/"
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_ENTRIES = 6000
RECEIPTS = {
    ".generated/build-evidence.json", ".generated/theme-review/evidence.json",
    ".generated/code-example-review/evidence.json",
    ".generated/version-review/evidence.json", ".generated/discovery-review/evidence.json",
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def commit(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "source-commit")
    return value


def integer(value):
    require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value), "positive-id")
    return int(value)


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_run(run, repository_id, source, attempt, workflow_id, *, publisher=False):
    require(run.get("repository", {}).get("id") == repository_id
            and run.get("head_repository", {}).get("id") == repository_id, "run-repository")
    require(run.get("workflow_id") == workflow_id, "run-workflow")
    require(run.get("head_branch") == ("release" if publisher else "development"), "run-branch")
    require(run.get("event") == ("workflow_dispatch" if publisher else "push"), "run-event")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "run-result")
    require(run.get("run_attempt") == attempt, "run-attempt")
    require(run.get("head_sha") == commit(source), "run-source")


def select_artifact(artifacts, run, repository_id, name):
    matches = [item for item in artifacts if item.get("name") == name]
    require(len(matches) == 1, "artifact-selection")
    item = matches[0]
    require(type(item.get("id")) is int and item["id"] > 0, "artifact-id")
    owner = item.get("workflow_run", {})
    require(owner.get("id") == run["id"] and owner.get("head_sha") == run["head_sha"]
            and owner.get("repository_id") == repository_id
            and owner.get("head_repository_id") == repository_id, "artifact-origin")
    require(item.get("expired") is False, "artifact-expired")
    require(type(item.get("size_in_bytes")) is int and 0 < item["size_in_bytes"] <= MAX_ARCHIVE,
            "artifact-size")
    require(isinstance(item.get("digest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]), "artifact-digest")
    return item


def archive_files(data, expected_digest):
    require(0 < len(data) <= MAX_ARCHIVE and digest(data) == expected_digest, "archive-identity")
    files, names, total = {}, set(), 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= MAX_ENTRIES, "archive-count")
        for entry in entries:
            name = entry.orig_filename
            # Python may normalize host separators or truncate a NUL while
            # parsing ZipInfo. Reject any such ambiguous on-wire identity.
            require(name == entry.filename, "archive-path")
            pure = PurePosixPath(name)
            require(name and not pure.is_absolute() and "\\" not in name and ":" not in name
                    and all(part not in (".", "..", "") for part in name.rstrip("/").split("/"))
                    and not any(ord(char) < 32 for char in name), "archive-path")
            require(name.casefold() not in names, "archive-duplicate")
            names.add(name.casefold())
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            require(kind in (0, stat.S_IFREG, stat.S_IFDIR), "archive-file-kind")
            require(not entry.flag_bits & 1, "archive-encrypted")
            if entry.is_dir():
                require(kind != stat.S_IFREG, "archive-directory-kind")
                continue
            require(kind != stat.S_IFDIR and 0 <= entry.file_size <= MAX_FILE, "archive-file-size")
            total += entry.file_size
            require(total <= MAX_EXPANDED, "archive-expanded-size")
            with archive.open(entry) as stream:
                content = stream.read(MAX_FILE + 1)
            require(len(content) == entry.file_size, "archive-file-length")
            files[name] = content
    return files


def stage_site(files, source, output: Path):
    source = commit(source)
    require(RECEIPTS <= files.keys(), "missing-browser-receipts")
    require(all(name.startswith("build/project/") or name in RECEIPTS for name in files),
            "unexpected-artifact-content")
    prefix = "build/project/"
    site = {name[len(prefix):]: value for name, value in files.items() if name.startswith(prefix)}
    require({"index.html", "404.html", "sitemap.xml", "site-manifest.json"} <= site.keys(), "site-files")
    require("publication.json" not in site, "candidate-publication-record")
    manifest = json.loads(site["site-manifest.json"])
    require(manifest.get("schema") == 1 and manifest.get("revision") == source
            and manifest.get("dirty") is False and manifest.get("baseUrl") == BASE_URL
            and manifest.get("channel") == "development", "site-manifest-identity")
    require(isinstance(manifest.get("versions"), list) and manifest["versions"], "site-versions")
    require(all(version.get("profile") != "synthetic-fixture" for version in manifest["versions"]),
            "synthetic-publication")
    for name in RECEIPTS:
        require(isinstance(json.loads(files[name]), (dict, list)), "browser-receipt-json")
    tree = hashlib.sha256()
    for name, data in sorted(site.items()):
        tree.update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    output.mkdir(parents=True, exist_ok=False)
    for name, data in site.items():
        path = output.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    return {"treeDigest": "sha256:" + tree.hexdigest(), "files": len(site),
            "source": source, "manifestDigest": digest(site["site-manifest.json"]),
            "versions": manifest["versions"], "examples": manifest.get("examples")}


def rollback_receipt(files, source, ci_run, attempt, artifact):
    require(set(files) == {"publication.json"}, "rollback-receipt-content")
    require(len(files["publication.json"]) <= 256 * 1024, "rollback-receipt-size")
    receipt = json.loads(files["publication.json"])
    require(receipt.get("schema") == 1 and receipt.get("repository") == REPOSITORY
            and receipt.get("source") == source and receipt.get("ciRun") == ci_run
            and receipt.get("ciAttempt") == attempt and receipt.get("artifactId") == artifact["id"]
            and receipt.get("artifactDigest") == artifact["digest"], "rollback-receipt-identity")
    return receipt


def verify_staged_site(directory: Path, receipt):
    require(directory.is_dir() and not directory.is_symlink(), "staged-directory")
    paths, total = [], 0
    for path in directory.rglob("*"):
        require(not path.is_symlink(), "staged-symlink")
        if path.is_dir():
            continue
        require(path.is_file(), "staged-file-kind")
        size = path.stat().st_size
        total += size
        require(size <= MAX_FILE and total <= MAX_EXPANDED, "staged-size")
        paths.append(path)
        require(len(paths) <= MAX_ENTRIES, "staged-count")
    tree = hashlib.sha256()
    count = 0
    for path in sorted(paths, key=lambda item: item.relative_to(directory).as_posix()):
        name = path.relative_to(directory).as_posix()
        data = path.read_bytes()
        if name == "publication.json":
            require(json.loads(data) == receipt, "staged-publication")
            continue
        tree.update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        count += 1
    require(count == receipt["files"] and "sha256:" + tree.hexdigest() == receipt["treeDigest"],
            "staged-tree-identity")
    require((directory / "publication.json").is_file(), "staged-publication-missing")

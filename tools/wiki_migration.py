#!/usr/bin/env python3
"""Bounded offline Wiki inventory/link checks; optional comparison to preserved Git."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/evidence/wiki-migration-2026-09-20.json"
REPOSITORY = "https://github.com/KirilsTurkins/latent-service-fabric"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    require(isinstance(value, str) and 0 < len(value) <= 512, "invalid Wiki path length")
    require(not re.search(r"%(?:2f|5c|00)", value, re.I), "encoded separator in Wiki path")
    decoded = unquote(value, errors="strict")
    require("\\" not in decoded and not any(ord(c) < 32 for c in decoded), "unsafe Wiki path")
    path = PurePosixPath(decoded)
    require(not path.is_absolute() and all(p not in ("", ".", "..") for p in decoded.split("/")),
            "Wiki path traversal")
    return str(path)


def legacy_link(value, source, files):
    """Preserve original fragments; destination notices are separate links."""
    require(isinstance(value, str) and len(value) <= 4096, "unbounded Wiki link")
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].split("|", 1)[-1]
    url = urlsplit(value)
    if url.scheme or url.netloc:
        if value.startswith(REPOSITORY + "/wiki/"):
            value = value[len(REPOSITORY + "/wiki/"):]
            url = urlsplit(value)
        else:
            require(url.scheme in ("https", "http", "mailto"), "unsupported Wiki link scheme")
            return value
    require(not url.query, "ambiguous local Wiki query")
    name = canonical(url.path) if url.path else source
    if name not in files and name + ".md" in files:
        name += ".md"
    require(name in files and files[name].get("sourceReference"), "missing or wrong-case Wiki target: " + name)
    # Original byte-identical headings retain their meaning even when the new
    # authority reorganizes the prose. Never guess a replacement heading.
    return files[name]["sourceReference"] + ("#" + url.fragment if url.fragment else "")


def validate(data, root=ROOT):
    require(data.get("schemaVersion") == "latent.docs.wiki-migration.v1", "Wiki inventory version")
    for key in ("sourceRevision", "publishedRevision", "publishedSourceRevision"):
        require(re.fullmatch(r"[0-9a-f]{40}", data.get(key, "")), "unbound Wiki revision")
    rows = data.get("files", [])
    require(0 < len(rows) <= 128, "Wiki inventory size")
    files = {}
    folded = set()
    for row in rows:
        name = canonical(row["path"])
        require(name not in files and name.casefold() not in folded, "duplicate or case-colliding Wiki destination")
        files[name] = row
        folded.add(name.casefold())
        require(row["mode"] == "100644" and re.fullmatch(r"[0-9a-f]{40}", row["gitBlob"]), "unsafe Wiki file identity")
        require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) and 0 < row["bytes"] <= 8 * 1024 * 1024,
                "unbounded or missing Wiki bytes")
        destination = row["destination"]
        if destination.startswith(REPOSITORY + "/"):
            require(row["disposition"] in ("archived-historical-asset", "publication-record"), "unreviewed external destination")
        else:
            resolved = (root / canonical(destination)).resolve()
            require(resolved.is_relative_to(root.resolve()) and resolved.is_file(), "missing migration authority: " + destination)
        if "sourceReference" in row:
            require(row["sourceReference"] == REPOSITORY + "/blob/" + data["sourceRevision"] + "/" + row["sourcePath"],
                    "mutable or foreign original reference")
    manifest = data["publicationManifest"]
    managed = set(manifest["managed_files"])
    require(len(managed) == len(manifest["managed_files"]), "duplicate published manifest entry")
    require(managed == set(files) - {".latent-service-fabric-wiki.json"}, "incomplete published migration map")
    digest_rows = manifest["managed_digests"]
    digests = {row["path"]: row["sha256"] for row in digest_rows}
    require(len(digests) == len(digest_rows) and set(digests) == managed, "incomplete published digest set")
    require(manifest["source_revision"] == data["publishedSourceRevision"], "publication source mismatch")
    for name in managed:
        require(digests[name] == files[name]["sha256"], "published bytes mismatch")
    links = 0
    for row in rows:
        for value in row.get("links", []):
            legacy_link(value, row["path"], files)
            links += 1
    require(data["cutover"] == "pending-successful-publication-and-reviewed-essential-guides", "unproven cutover status")
    return {"files": len(files), "pages": sum(r["kind"] == "page" for r in rows),
            "assets": sum(r["kind"] == "asset" for r in rows), "legacyLinks": links, "cutover": "pending"}


def compare_git(data, git_directory):
    def git(*args):
        result = subprocess.run(["git", "--git-dir=" + str(git_directory), *args],
                                check=True, capture_output=True, timeout=15)
        require(len(result.stdout) <= 8 * 1024 * 1024, "oversized preserved Wiki input")
        return result.stdout

    revision = data["publishedRevision"]
    names = git("ls-tree", "-r", "--name-only", revision).decode("utf-8").splitlines()
    require(set(names) == {row["path"] for row in data["files"]}, "preserved Wiki file set differs")
    for row in data["files"]:
        identity = revision + ":" + row["path"]
        require(int(git("cat-file", "-s", identity)) == row["bytes"], "preserved Wiki size differs")
        content = git("show", identity)
        require(len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"],
                "preserved Wiki content differs: " + row["path"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-git", type=Path)
    args = parser.parse_args()
    require(INVENTORY.stat().st_size <= 1024 * 1024, "oversized Wiki inventory")
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    result = validate(data)
    if args.wiki_git:
        compare_git(data, args.wiki_git)
        result["preservedGitBytesVerified"] = True
    print(json.dumps(result))


if __name__ == "__main__":
    main()

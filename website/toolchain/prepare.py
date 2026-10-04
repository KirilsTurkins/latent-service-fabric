#!/usr/bin/env python3
"""Prepare a locked npm bundle without running downloaded package code.

npm overrides do not replace bundled dependencies. Replace the complete four
reviewed packages before npm executes, then authenticate the deterministic TAR
against package-lock.json. This is a derived distribution, not an upstream npm
release. All intermediate archives stay under ignored target/.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIMIT = 16 * 1024 * 1024
EXPANDED_LIMIT = 64 * 1024 * 1024
PROFILE = "npm-11.19.1-lsf-bundle-v3"
OUTPUT = ROOT / "target/website-package-manager" / (PROFILE + ".tar")
CACHE = OUTPUT.parent / "inputs"


def integrity(raw: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected registry redirect")


def acquire(pin: dict, cache: Path, offline: bool) -> bytes:
    name, version = pin["name"], pin["version"]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid package identity")
    filename = f"{name}-{version}.tgz"
    cached = cache / filename
    if cached.exists():
        with cached.open("rb") as source:
            raw = source.read(LIMIT + 1)
    else:
        if offline:
            raise ValueError(f"offline input missing: {filename}")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(f"https://registry.npmjs.org/{name}/-/{filename}", timeout=30) as response:
            raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT or integrity(raw) != pin["integrity"]:
        raise ValueError(f"archive integrity/size mismatch: {filename}")
    cache.mkdir(parents=True, exist_ok=True)
    if not cached.exists():
        # A partial download must never become a valid cache input.
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temporary:
            temporary.write(raw)
            pending = Path(temporary.name)
        pending.replace(cached)
    return raw


def unpack(raw: bytes) -> dict[str, tuple[bytes, int]]:
    """Read authenticated tarballs into finite memory, never extract host paths."""
    files: dict[str, tuple[bytes, int]] = {}
    seen: set[str] = set()
    size = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for count, member in enumerate(archive, 1):
            name = member.name.rstrip("/")
            path = PurePosixPath(name)
            if (count > 6000 or not name or "\\" in name or path.is_absolute()
                    or any(part in {"", ".", ".."} for part in name.split("/"))
                    or path.parts[0] != "package" or name in seen):
                raise ValueError("invalid or duplicate archive path")
            seen.add(name)
            if member.isdir():
                continue
            if not member.isfile() or not 0 <= member.size <= 8 * 1024 * 1024:
                raise ValueError("unsupported archive member")
            size += member.size
            if size > EXPANDED_LIMIT:
                raise ValueError("expanded archive bound")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("missing member bytes")
            with source:
                value = source.read(member.size + 1)
            if len(value) != member.size:
                raise ValueError("truncated member")
            files[name] = value, 0o755 if member.mode & 0o111 else 0o644
    return files


def package(files: dict[str, tuple[bytes, int]], prefix: str = "package/") -> dict:
    return json.loads(files[prefix + "package.json"][0])


def repair_source(files: dict[str, tuple[bytes, int]], repair: dict) -> dict[str, tuple[bytes, int]]:
    """Apply one reviewed complete-file repair to authenticated upstream bytes."""
    profiles = {"braces": ("3.0.3", "braces-3.0.3-lsf-depth-v1"),
                "http-cache-semantics": ("4.3.0", "http-cache-semantics-4.3.0-lsf-cache-v1")}
    if (set(repair) != {"schema", "profile", "name", "version", "upstreamIntegrity", "files"}
            or repair["schema"] != 1 or repair["name"] not in profiles
            or (repair["version"], repair["profile"]) != profiles[repair["name"]]):
        raise ValueError("unreviewed source repair identity")
    manifest = package(files)
    expected = {"fill-range": "^7.1.1"} if repair["name"] == "braces" else {}
    if (manifest["name"] != repair["name"] or manifest["version"] != repair["version"]
            or manifest.get("dependencies", {}) != expected
            or manifest.get("optionalDependencies") or manifest.get("peerDependencies")
            or manifest.get("bundleDependencies") or manifest.get("bundledDependencies")
            or any(name.startswith("package/node_modules/") for name in files)
            or any(name in files for name in ("package/package-lock.json", "package/npm-shrinkwrap.json"))):
        raise ValueError("source repair package graph requires review")
    required = {"lib/compile.js", "lib/expand.js", "lib/stringify.js", "lib/parse.js", "lib/utils.js"} if repair["name"] == "braces" else {"index.js"}
    rows = repair["files"]
    if not isinstance(rows, list) or len(rows) != len(required):
        raise ValueError("source repair file coverage")
    result = files.copy()
    seen: set[str] = set()
    for row in rows:
        if (set(row) != {"path", "beforeSha256", "afterSha256", "edits"}
                or row["path"] not in required or row["path"] in seen
                or not all(isinstance(row[field], str) and re.fullmatch(r"[0-9a-f]{64}", row[field])
                           for field in ("beforeSha256", "afterSha256"))):
            raise ValueError("unreviewed source repair file")
        seen.add(row["path"])
        key = "package/" + row["path"]
        raw, mode = result[key]
        if hashlib.sha256(raw).hexdigest() != row["beforeSha256"]:
            raise ValueError("source repair preimage drift")
        edits = row["edits"]
        if not isinstance(edits, list) or not 0 < len(edits) <= 8:
            raise ValueError("source repair edit bound")
        text = raw.decode("utf-8")
        for edit in edits:
            if (set(edit) != {"before", "after", "count"}
                    or not all(isinstance(edit[field], str) and 0 < len(edit[field]) <= 8192 for field in ("before", "after"))
                    or edit["before"] == edit["after"] or type(edit["count"]) is not int
                    or not 0 < edit["count"] <= 4 or text.count(edit["before"]) != edit["count"]):
                raise ValueError("source repair edit drift")
            text = text.replace(edit["before"], edit["after"])
        patched = text.encode("utf-8")
        if patched == raw or hashlib.sha256(patched).hexdigest() != row["afterSha256"]:
            raise ValueError("source repair postimage drift")
        result[key] = patched, mode
    return result


def packed(files: dict[str, tuple[bytes, int]]) -> bytes:
    """Use the original deterministic, uncompressed USTAR format."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, (raw, mode) in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = mode
            member.mtime = member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def compose(base: bytes, patches: list[tuple[dict, bytes]], *, repair: dict | None = None) -> bytes:
    files = unpack(base)
    manifest = package(files)
    if manifest["name"] != "npm" or manifest["version"] != "11.19.1":
        raise ValueError("unexpected npm source")
    if any(name in files for name in ("package/package-lock.json", "package/npm-shrinkwrap.json")):
        raise ValueError("embedded npm lock requires separate review")
    names: set[str] = set()
    for pin, raw in patches:
        name = pin["name"]
        if name not in {"ip-address", "undici", "brace-expansion", "http-cache-semantics"} or name in names:
            raise ValueError("unexpected bundle replacement")
        names.add(name)
        prefix = "package/node_modules/" + name + "/"
        old = package(files, prefix)
        replacement = unpack(raw)
        new = package(replacement)
        if old["name"] != name or old["version"] != pin["from"]:
            raise ValueError("unexpected original bundled package")
        expected = {"balanced-match": "^4.0.2"} if name == "brace-expansion" else {}
        if (new["name"] != name or new["version"] != pin["version"]
                or new.get("dependencies", {}) != expected
                or new.get("optionalDependencies") or new.get("peerDependencies")
                or new.get("bundleDependencies") or new.get("bundledDependencies")
                or any(key.startswith("package/node_modules/") for key in replacement)):
            raise ValueError("replacement package graph requires review")
        if name == "brace-expansion":
            # The authenticated npm archive already contains this exact dependency.
            # Do not resolve or install a new graph during source preparation.
            dependency = package(files, "package/node_modules/balanced-match/")
            if (old.get("dependencies") != expected
                    or dependency.get("name") != "balanced-match" or dependency.get("version") != "4.0.4"
                    or dependency.get("dependencies") or dependency.get("optionalDependencies")
                    or dependency.get("peerDependencies")):
                raise ValueError("replacement dependency graph requires review")
            if any(key.startswith(prefix + "node_modules/") for key in files):
                raise ValueError("shadowed replacement dependency requires review")
        if name == "http-cache-semantics" and repair is not None:
            if repair["upstreamIntegrity"] != pin["integrity"]:
                raise ValueError("source repair archive identity drift")
            replacement = repair_source(replacement, repair)
        files = {key: value for key, value in files.items() if not key.startswith(prefix)}
        for key, value in replacement.items():
            files[prefix + key.removeprefix("package/")] = value
    if names != {"ip-address", "undici", "brace-expansion", "http-cache-semantics"}:
        raise ValueError("incomplete bundle replacement")
    return packed(files)


def library_material(pins: dict, acquired: list[tuple[dict, bytes]], *, offline: bool) -> tuple[dict, dict]:
    """Authenticate the two fixed repair documents and their upstream archives."""
    if set(pins) != {"schema", "profile", "base", "patches", "libraries", "repairs"}:
        raise ValueError("source repair profile fields")
    if not isinstance(pins["libraries"], list) or len(pins["libraries"]) != 1 or pins["libraries"][0].get("name") != "braces":
        raise ValueError("source repair library selection")
    material = {pin["name"]: (pin, raw) for pin, raw in acquired}
    brace = pins["libraries"][0]
    material["braces"] = brace, acquire(brace, CACHE, offline)
    repairs = {}
    if not isinstance(pins["repairs"], list) or len(pins["repairs"]) != 2:
        raise ValueError("source repair document coverage")
    for row in pins["repairs"]:
        if (set(row) != {"path", "sha256"} or row["path"] not in {"repairs/braces.json", "repairs/http-cache-semantics.json"}
                or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("source repair document identity")
        with (HERE / row["path"]).open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("source repair document drift")
        record = json.loads(raw)
        name = row["path"].removeprefix("repairs/").removesuffix(".json")
        if name in repairs or record["name"] != name or record["upstreamIntegrity"] != material[name][0]["integrity"]:
            raise ValueError("source repair upstream identity drift")
        repairs[name] = record
    if set(repairs) != {"braces", "http-cache-semantics"}:
        raise ValueError("source repair coverage")
    libraries = {name: packed(repair_source(unpack(material[name][1]), repair)) for name, repair in repairs.items()}
    return libraries, repairs


def verify_library_locks(libraries: dict, repairs: dict) -> None:
    for directory in (ROOT / "website", ROOT / "examples/framework-compatibility"):
        lock = json.loads((directory / "package-lock.json").read_text(encoding="utf-8"))
        for name, raw in libraries.items():
            archive = "file:" + ("../" if directory == ROOT / "website" else "../../") + "target/website-package-manager/" + repairs[name]["profile"] + ".tar"
            selected = [row for path, row in lock["packages"].items() if path.rsplit("node_modules/", 1)[-1] == name]
            if not selected or any(row.get("version") != repairs[name]["version"] or row.get("resolved") != archive
                                   or row.get("integrity") != integrity(raw) or row.get("link") for row in selected):
                raise ValueError("prepared library differs from reviewed package lock")


def prepare(*, offline: bool = False, refresh: bool = False) -> str:
    pins = json.loads((HERE / "source.json").read_text(encoding="utf-8"))
    if pins.get("schema") != 1 or pins.get("profile") != PROFILE:
        raise ValueError("unsupported bundle source profile")
    acquired = [(pin, acquire(pin, CACHE, offline)) for pin in pins["patches"]]
    libraries, repairs = library_material(pins, acquired, offline=offline)
    raw = compose(acquire(pins["base"], CACHE, offline), acquired, repair=repairs["http-cache-semantics"])
    actual = integrity(raw)
    if not refresh:
        lock = json.loads((HERE / "package-lock.json").read_text(encoding="utf-8"))
        row = lock["packages"]["node_modules/npm"]
        expected_path = "file:../../target/website-package-manager/" + PROFILE + ".tar"
        if row.get("resolved") != expected_path or row.get("integrity") != actual:
            raise ValueError("prepared npm differs from reviewed package lock")
        verify_library_locks(libraries, repairs)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    outputs = {OUTPUT: raw, **{OUTPUT.parent / (repairs[name]["profile"] + ".tar"): value for name, value in libraries.items()}}
    for path, value in outputs.items():
        with tempfile.NamedTemporaryFile(dir=OUTPUT.parent, delete=False) as temporary:
            temporary.write(value)
            pending = Path(temporary.name)
        pending.replace(path)
    return actual


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use only authenticated cached inputs")
    parser.add_argument("--refresh", action="store_true", help="Maintainer-only: prepare an unlocked candidate for explicit lock regeneration")
    args = parser.parse_args()
    actual = prepare(offline=args.offline, refresh=args.refresh)
    print(("UNLOCKED CANDIDATE: " if args.refresh else "Verified npm bundle: ") + actual)


if __name__ == "__main__":
    main()

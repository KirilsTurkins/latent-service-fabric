#!/usr/bin/env python3
"""Prepare a locked npm bundle without running downloaded package code.

npm overrides do not replace bundled dependencies. Replace the complete two
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
PROFILE = "npm-11.19.1-lsf-bundle-v1"
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


def compose(base: bytes, patches: list[tuple[dict, bytes]]) -> bytes:
    files = unpack(base)
    manifest = package(files)
    if manifest["name"] != "npm" or manifest["version"] != "11.19.1":
        raise ValueError("unexpected npm source")
    if any(name in files for name in ("package/package-lock.json", "package/npm-shrinkwrap.json")):
        raise ValueError("embedded npm lock requires separate review")
    names: set[str] = set()
    for pin, raw in patches:
        name = pin["name"]
        if name not in {"ip-address", "undici"} or name in names:
            raise ValueError("unexpected bundle replacement")
        names.add(name)
        prefix = "package/node_modules/" + name + "/"
        old = package(files, prefix)
        replacement = unpack(raw)
        new = package(replacement)
        if old["name"] != name or old["version"] != pin["from"]:
            raise ValueError("unexpected original bundled package")
        if new["name"] != name or new["version"] != pin["version"] or new.get("dependencies"):
            raise ValueError("replacement package graph requires review")
        files = {key: value for key, value in files.items() if not key.startswith(prefix)}
        for key, value in replacement.items():
            files[prefix + key.removeprefix("package/")] = value
    if names != {"ip-address", "undici"}:
        raise ValueError("incomplete bundle replacement")
    # An uncompressed USTAR has stable bytes across zlib/platform versions.
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, (raw, mode) in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = mode
            member.mtime = member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


def prepare(*, offline: bool = False, refresh: bool = False) -> str:
    pins = json.loads((HERE / "source.json").read_text(encoding="utf-8"))
    if pins.get("schema") != 1 or pins.get("profile") != PROFILE:
        raise ValueError("unsupported bundle source profile")
    raw = compose(acquire(pins["base"], CACHE, offline),
                  [(pin, acquire(pin, CACHE, offline)) for pin in pins["patches"]])
    actual = integrity(raw)
    if not refresh:
        lock = json.loads((HERE / "package-lock.json").read_text(encoding="utf-8"))
        row = lock["packages"]["node_modules/npm"]
        expected_path = "file:../../target/website-package-manager/" + PROFILE + ".tar"
        if row.get("resolved") != expected_path or row.get("integrity") != actual:
            raise ValueError("prepared npm differs from reviewed package lock")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=OUTPUT.parent, delete=False) as temporary:
        temporary.write(raw)
        pending = Path(temporary.name)
    pending.replace(OUTPUT)
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

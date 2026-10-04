"""Authenticate and prove one source-patched braces distribution, without npm."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile
import time
import urllib.request

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.security_common import ROOT, decode_json, digest, read_file, require, run

PROFILE = "braces-3.0.3-lsf-depth-v1"
VERSION = "3.0.3+lsf-depth-v1"
SOURCE = "website/toolchain/braces-source.json"
GUARD = "website/toolchain/braces-depth.js"
PROOF = "website/toolchain/braces-proof.cjs"
OUTPUT = "target/website-package-manager/" + PROFILE + ".tar"
CONSUMERS = {
    "website/package.json": "file:../" + OUTPUT,
    "examples/framework-compatibility/package.json": "file:../../" + OUTPUT,
}
LIMIT = 1024 * 1024
EXPANDED_LIMIT = 4 * 1024 * 1024


def integrity(raw: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected derivation source redirect")


def acquire(pin: dict, cache: Path, *, offline: bool = False) -> bytes:
    """Read only a bounded, exact registry archive; never execute its scripts."""
    name, version = pin["name"], pin["version"]
    require(re.fullmatch(r"[a-z][a-z0-9-]*", name) is not None
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is not None,
            "invalid-derivation-source-identity")
    filename = f"{name}-{version}.tgz"
    cached = cache / filename
    if cached.exists():
        raw = read_file(cache, filename, LIMIT)
    else:
        require(not offline, "missing-offline-derivation-source")
        url = f"https://registry.npmjs.org/{name}/-/{filename}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        started = time.monotonic()
        with opener.open(url, timeout=20) as response:
            require(response.status == 200 and response.url == url, "derivation-source-unavailable")
            content = bytearray()
            while chunk := response.read1(65536):
                content.extend(chunk)
                require(len(content) <= LIMIT and time.monotonic() - started <= 30,
                        "derivation-source-bound")
            raw = bytes(content)
    require(len(raw) <= LIMIT and integrity(raw) == pin["integrity"], "derivation-source-integrity")
    cache.mkdir(parents=True, exist_ok=True)
    if not cached.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as pending:
            pending.write(raw)
            temporary = Path(pending.name)
        temporary.replace(cached)
    return raw


def unpack(raw: bytes) -> dict[str, tuple[bytes, int]]:
    require(len(raw) <= LIMIT, "derivation-archive-bound")
    files, seen, expanded = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for count, member in enumerate(archive, 1):
            name = member.name.rstrip("/")
            path = PurePosixPath(name)
            require(count <= 64 and name and "\\" not in name and not path.is_absolute()
                    and path.parts[0] == "package" and name not in seen
                    and all(part not in {"", ".", ".."} for part in name.split("/")),
                    "derivation-archive-path")
            seen.add(name)
            if member.isdir():
                continue
            require(member.isfile() and 0 <= member.size <= LIMIT, "derivation-archive-member")
            expanded += member.size
            require(expanded <= EXPANDED_LIMIT, "derivation-expanded-bound")
            source = archive.extractfile(member)
            require(source is not None, "missing-derivation-member")
            with source:
                value = source.read(member.size + 1)
            require(len(value) == member.size, "truncated-derivation-member")
            files[name] = value, 0o755 if member.mode & 0o111 else 0o644
    return files


def profile(repo: Path) -> dict:
    document = decode_json(read_file(repo, SOURCE, LIMIT))
    require(isinstance(document, dict) and set(document) == {
        "schema", "profile", "version", "base", "source_files", "guard_sha256", "proof_sha256", "proof_dependencies"
    }, "invalid-braces-derivation-profile")
    require(document["schema"] == 1 and document["profile"] == PROFILE and document["version"] == VERSION
            and document["base"]["name"] == "braces" and document["base"]["version"] == "3.0.3"
            and document["base"]["commit"] == "74b2db2938fad48a2ea54a9c8bf27a37a62c350d",
            "braces-derivation-origin-drift")
    for path, field in ((GUARD, "guard_sha256"), (PROOF, "proof_sha256")):
        require(digest(read_file(repo, path).replace(b"\r\n", b"\n")) == document[field],
                "braces-derivation-code-drift")
    require([(pin["name"], pin["version"], pin["dependencies"]) for pin in document["proof_dependencies"]] == [
        ("fill-range", "7.1.1", {"to-regex-range": "^5.0.1"}),
        ("to-regex-range", "5.0.1", {"is-number": "^7.0.0"}),
        ("is-number", "7.0.0", {}),
    ], "braces-proof-dependency-graph")
    return document


def replace_once(raw: bytes, before: bytes, after: bytes) -> bytes:
    require(raw.count(before) == 1, "braces-patch-context-drift")
    return raw.replace(before, after, 1)


def compose(raw: bytes, document: dict, guard: bytes) -> tuple[bytes, dict[str, tuple[bytes, int]]]:
    require(integrity(raw) == document["base"]["integrity"], "braces-source-integrity")
    files = unpack(raw)
    require({name: {"sha256": digest(value), "mode": mode} for name, (value, mode) in files.items()}
            == document["source_files"], "braces-source-file-inventory")
    manifest = decode_json(files["package/package.json"][0])
    require(manifest["name"] == "braces" and manifest["version"] == "3.0.3"
            and manifest["dependencies"] == {"fill-range": "^7.1.1"}
            and manifest["license"] == "MIT" and not manifest.get("optionalDependencies")
            and not manifest.get("peerDependencies") and not manifest.get("bundleDependencies")
            and not any(name.startswith("package/node_modules/") for name in files),
            "braces-source-package-graph")
    for name in ("parse", "compile", "expand", "stringify"):
        key = f"package/lib/{name}.js"
        value, mode = files[key]
        value = replace_once(value, b"'use strict';\n", b"'use strict';\n\nconst depthGuard = require('./depth');\n")
        if name == "parse":
            for token in (b"CHAR_LEFT_PARENTHESES", b"CHAR_LEFT_CURLY_BRACE"):
                before = b"    if (value === " + token + b") {\n"
                value = replace_once(value, before, before + b"      depthGuard.nesting(stack.length);\n")
        else:
            before = (f"const {name} = (ast, options = {{}}) => {{\n" if name != "stringify"
                      else "module.exports = (ast, options = {}) => {\n").encode()
            value = replace_once(value, before, before + b"  depthGuard.ast(ast);\n")
        files[key] = value, mode
    files["package/lib/depth.js"] = guard, 0o644
    attribution = {"profile": PROFILE, "upstream": document["base"],
                   "guard_sha256": document["guard_sha256"], "advisory": "GHSA-vfj7-8cjw-p6xm",
                   "notice": "Local source repair of upstream braces 3.0.3; no upstream patched release is claimed."}
    manifest["version"] = VERSION
    manifest["latentDerivation"] = attribution
    files["package/package.json"] = (json.dumps(manifest, indent=2) + "\n").encode(), files["package/package.json"][1]
    files["package/latent-derivation.json"] = (json.dumps(attribution, indent=2) + "\n").encode(), 0o644
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, (value, mode) in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(value), mode
            member.mtime = member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(value))
    return output.getvalue(), files


def consumer_locks(repo: Path, expected: str) -> list[dict]:
    records = []
    for path, archive in CONSUMERS.items():
        manifest = decode_json(read_file(repo, path))
        lock_path = str(PurePosixPath(path).with_name("package-lock.json"))
        lock = decode_json(read_file(repo, lock_path))
        require(manifest.get("overrides", {}).get("braces") == archive, "braces-consumer-override-drift")
        braces = {location: row for location, row in lock["packages"].items()
                  if location and location.rsplit("node_modules/", 1)[-1] == "braces"}
        require(braces and all(row.get("version") == VERSION and row.get("resolved") == archive
                              and row.get("integrity") == expected
                              and row.get("dependencies") == {"fill-range": "^7.1.1"}
                              and not row.get("link") for row in braces.values()),
                "unlocked-braces-derivation")
        records.append({"path": lock_path, "lock_sha256": digest(read_file(repo, lock_path).replace(b"\r\n", b"\n")),
                        "locations": sorted(braces), "integrity": expected})
    return records


def prepared(repo: Path, *, offline: bool = False) -> tuple[bytes, dict, dict[str, tuple[bytes, int]]]:
    document = profile(repo)
    cache = repo / "target/website-package-manager/braces-inputs"
    raw = acquire(document["base"], cache, offline=offline)
    tar, files = compose(raw, document, read_file(repo, GUARD).replace(b"\r\n", b"\n"))
    return tar, document, files


def prepare(repo: Path, *, offline: bool = False, refresh: bool = False) -> dict:
    raw, document, _ = prepared(repo, offline=offline)
    actual = integrity(raw)
    consumers = [] if refresh else consumer_locks(repo, actual)
    output = repo / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as pending:
        pending.write(raw)
        temporary = Path(pending.name)
    temporary.replace(output)
    return {"profile": PROFILE, "upstream_version": document["base"]["version"], "derived_version": VERSION,
            "integrity": actual, "sha256": digest(raw), "unlocked_candidate": refresh, "consumers": consumers}


def prove(repo: Path, scratch: Path, node: str = "node", *, offline: bool = False) -> dict:
    raw, document, files = prepared(repo, offline=offline)
    actual = integrity(raw)
    consumers = consumer_locks(repo, actual)
    cache = repo / "target/website-package-manager/braces-inputs"
    with tempfile.TemporaryDirectory(prefix="braces-proof-", dir=scratch) as temporary:
        directory = Path(temporary)
        base_files = unpack(acquire(document["base"], cache, offline=offline))
        for label, package_files in (("original", base_files), ("derived", files)):
            for name, (value, _) in package_files.items():
                target = directory / label / name.removeprefix("package/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
        for pin in document["proof_dependencies"]:
            package_files = unpack(acquire(pin, cache, offline=offline))
            manifest = decode_json(package_files["package/package.json"][0])
            require(manifest["name"] == pin["name"] and manifest["version"] == pin["version"]
                    and manifest.get("dependencies", {}) == pin["dependencies"]
                    and not manifest.get("optionalDependencies") and not manifest.get("peerDependencies")
                    and not manifest.get("bundleDependencies")
                    and not any(name.startswith("package/node_modules/") for name in package_files),
                    "braces-proof-package-graph-drift")
            for name, (value, _) in package_files.items():
                target = directory / "node_modules" / pin["name"] / name.removeprefix("package/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
        harness = directory / "proof.cjs"
        harness.write_bytes(read_file(repo, PROOF).replace(b"\r\n", b"\n"))
        _, output = run([node, "--max-old-space-size=128", "--stack_size=512", str(harness), str(directory / "original"),
                         str(directory / "derived")], directory, timeout=30, limit=65536)
        proof = decode_json(output)
        require(isinstance(proof, dict) and proof.get("profile") == PROFILE and proof.get("node") == "24.19.0"
                and proof.get("status") == "pass" and proof.get("upstream_stack_overflow_observed") is True,
                "braces-remediation-proof-failed")
    return {"profile": PROFILE, "upstream": document["base"], "derived_version": VERSION,
            "integrity": actual, "archive_sha256": digest(raw), "consumers": consumers, "proof": proof}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "prove"))
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--scratch", type=Path, default=ROOT / "target/braces-proof")
    parser.add_argument("--node", default="node")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Maintainer-only unlocked candidate, never CI")
    arguments = parser.parse_args()
    require(not arguments.refresh or arguments.command == "prepare", "invalid-braces-refresh-mode")
    arguments.scratch.mkdir(parents=True, exist_ok=True)
    result = (prepare(arguments.repo.resolve(), offline=arguments.offline, refresh=arguments.refresh)
              if arguments.command == "prepare" else prove(arguments.repo.resolve(), arguments.scratch.resolve(),
                                                           arguments.node, offline=arguments.offline))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()

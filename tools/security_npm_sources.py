"""Independently verify maintained npm source repairs without executing them.

This scanner control does not import the project's archive builder. It reads
fresh authenticated upstream archives as data, checks complete-file preimages
and postimages, and reconstructs the exact deterministic distribution pinned by
every selected lock. Upstream package identities remain in all OSV queries.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

from tools.security_common import POLICY, decode_json, digest, read_file, require


def integrity(raw: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected npm repair registry redirect")


def registry_archive(pin: dict) -> bytes:
    name, version = pin["name"], pin["version"]
    require(re.fullmatch(r"[a-z][a-z0-9-]*", name) is not None
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is not None,
            "invalid-npm-repair-upstream-identity")
    url = f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=30) as response:
        require(response.status == 200 and response.url == url, "npm-repair-upstream-unavailable")
        raw = response.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024 and integrity(raw) == pin["integrity"],
            "npm-repair-upstream-integrity")
    return raw


def members(raw: bytes) -> dict[str, tuple[bytes, int]]:
    result, seen, size = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for count, item in enumerate(archive, 1):
            name = item.name.rstrip("/")
            path = PurePosixPath(name)
            require(count <= 6000 and bool(name) and "\\" not in name
                    and not path.is_absolute() and path.parts[0] == "package"
                    and not any(part in {"", ".", ".."} for part in name.split("/"))
                    and name not in seen, "npm-repair-archive-path")
            seen.add(name)
            if item.isdir():
                continue
            require(item.isfile() and 0 <= item.size <= 8 * 1024 * 1024,
                    "npm-repair-archive-member")
            size += item.size
            require(size <= 64 * 1024 * 1024, "npm-repair-expanded-bound")
            stream = archive.extractfile(item)
            require(stream is not None, "npm-repair-missing-member")
            with stream:
                value = stream.read(item.size + 1)
            require(len(value) == item.size, "npm-repair-truncated-member")
            result[name] = value, 0o755 if item.mode & 0o111 else 0o644
    return result


def manifest(files: dict, name: str, version: str, dependencies: dict, prefix="package/") -> dict:
    value = decode_json(files[prefix + "package.json"][0])
    require(value.get("name") == name and value.get("version") == version
            and value.get("dependencies", {}) == dependencies
            and not any(value.get(field) for field in (
                "optionalDependencies", "peerDependencies", "bundleDependencies", "bundledDependencies")),
            "npm-repair-package-graph")
    if prefix == "package/":
        require(not any(key.startswith("package/node_modules/") for key in files)
                and not any(key in files for key in ("package/package-lock.json", "package/npm-shrinkwrap.json")),
                "npm-repair-hidden-package-graph")
    return value


def source_repair(files: dict, repair: dict, pin: dict) -> dict:
    expected = {"braces": {"lib/utils.js", "lib/compile.js", "lib/expand.js", "lib/stringify.js", "lib/parse.js"},
                "http-cache-semantics": {"index.js"}}
    require(set(repair) == {"schema", "profile", "name", "version", "upstreamIntegrity", "files"}
            and repair["schema"] == 1 and repair["name"] == pin["name"]
            and repair["version"] == pin["version"] and repair["upstreamIntegrity"] == pin["integrity"]
            and isinstance(repair["files"], list), "npm-repair-document-identity")
    rows = repair["files"]
    require(len(rows) == len(expected[pin["name"]])
            and {row["path"] for row in rows} == expected[pin["name"]], "npm-repair-file-coverage")
    output = files.copy()
    for row in rows:
        require(set(row) == {"path", "beforeSha256", "afterSha256", "edits"}
                and all(isinstance(row[field], str) and re.fullmatch(r"[0-9a-f]{64}", row[field])
                        for field in ("beforeSha256", "afterSha256")), "npm-repair-file-identity")
        key = "package/" + row["path"]
        raw, mode = files[key]
        require(digest(raw) == row["beforeSha256"], "npm-repair-preimage-drift")
        edits = row["edits"]
        require(isinstance(edits, list) and 0 < len(edits) <= 8, "npm-repair-edit-bound")
        text = raw.decode("utf-8")
        for edit in edits:
            require(set(edit) == {"before", "after", "count"}
                    and all(isinstance(edit[field], str) and 0 < len(edit[field]) <= 8192
                            for field in ("before", "after"))
                    and edit["before"] != edit["after"] and type(edit["count"]) is int
                    and 0 < edit["count"] <= 4 and text.count(edit["before"]) == edit["count"],
                    "npm-repair-edit-drift")
            text = text.replace(edit["before"], edit["after"])
        patched = text.encode("utf-8")
        require(patched != raw and digest(patched) == row["afterSha256"], "npm-repair-postimage-drift")
        output[key] = patched, mode
    return output


def distribution(files: dict) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, (raw, mode) in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(raw), mode
            item.mtime = item.uid = item.gid = 0
            archive.addfile(item, io.BytesIO(raw))
    return output.getvalue()


def verify_sources(repo: Path, packages: list, configuration: dict, fetch=registry_archive) -> list[dict]:
    """Produce receipts only after every selected source/lock byte is verified."""
    selected = [entry for entry in configuration["manifests"]
                if (entry.get("derived_bundle") or entry.get("derived_libraries"))
                and any(package.path == entry["lock"] for package in packages)]
    if not selected:
        return []
    policy = decode_json(read_file(POLICY, "npm-source-repairs.json"))
    require(set(policy) == {"schema", "source_sha256", "builder_sha256", "repairs"}
            and policy["schema"] == 1 and set(policy["repairs"]) == {"braces", "http-cache-semantics"},
            "npm-repair-policy")
    for path, field in (("website/toolchain/source.json", "source_sha256"),
                        ("website/toolchain/prepare.py", "builder_sha256")):
        require(digest(read_file(repo, path).replace(b"\r\n", b"\n")) == policy[field],
                "npm-repair-control-input-drift")
    source = decode_json(read_file(repo, "website/toolchain/source.json"))
    require(set(source) == {"schema", "profile", "base", "patches", "libraries", "repairs"}
            and source["schema"] == 1 and source["profile"] == "npm-11.19.1-lsf-bundle-v3"
            and isinstance(source["patches"], list) and len(source["patches"]) == 4
            and isinstance(source["libraries"], list) and len(source["libraries"]) == 1
            and source["libraries"][0]["name"] == "braces", "npm-repair-source-profile")
    pins = source["patches"] + source["libraries"]
    require(len({pin["name"] for pin in pins}) == 5
            and {pin["name"] for pin in pins} == {"ip-address", "undici", "brace-expansion", "http-cache-semantics", "braces"},
            "npm-repair-upstream-coverage")
    material = {}
    for pin in pins:
        raw = fetch(pin)
        require(integrity(raw) == pin["integrity"], "npm-repair-upstream-integrity")
        files = members(raw)
        dependencies = {"balanced-match": "^4.0.2"} if pin["name"] == "brace-expansion" else (
            {"fill-range": "^7.1.1"} if pin["name"] == "braces" else {})
        manifest(files, pin["name"], pin["version"], dependencies)
        material[pin["name"]] = files
    receipts = []
    require(isinstance(source["repairs"], list) and len(source["repairs"]) == 2, "npm-repair-document-coverage")
    for name, reviewed in policy["repairs"].items():
        require(set(reviewed) == {"version", "profile", "repair_sha256", "integrity", "advisories"},
                "npm-repair-policy-fields")
        path = f"website/toolchain/repairs/{name}.json"
        raw = read_file(repo, path).replace(b"\r\n", b"\n")
        require(len(raw) <= 65536 and digest(raw) == reviewed["repair_sha256"]
                and {"path": f"repairs/{name}.json", "sha256": reviewed["repair_sha256"]} in source["repairs"],
                "npm-repair-document-drift")
        repair = decode_json(raw)
        pin = next(pin for pin in pins if pin["name"] == name)
        require((repair["version"], repair["profile"]) == (reviewed["version"], reviewed["profile"]),
                "npm-repair-reviewed-identity")
        material[name] = source_repair(material[name], repair, pin)
        derived = integrity(distribution(material[name]))
        require(derived == reviewed["integrity"], "npm-repair-distribution-drift")
        receipts.append({"name": name, "version": pin["version"], "profile": repair["profile"],
                         "upstream_integrity": pin["integrity"], "derived_integrity": derived,
                         "repair_sha256": digest(raw), "files": len(repair["files"]), "locks": [],
                         "advisories": reviewed["advisories"]})
    base = source["base"]
    require(base["name"] == "npm" and base["version"] == "11.19.1", "npm-repair-bundle-identity")
    raw = fetch(base)
    require(integrity(raw) == base["integrity"], "npm-repair-upstream-integrity")
    bundle = members(raw)
    owner = decode_json(bundle["package/package.json"][0])
    require(owner["name"] == base["name"] and owner["version"] == base["version"]
            and not any(path in bundle for path in ("package/package-lock.json", "package/npm-shrinkwrap.json")),
            "npm-repair-bundle-graph")
    for pin in source["patches"]:
        name = pin["name"]
        prefix = f"package/node_modules/{name}/"
        old = decode_json(bundle[prefix + "package.json"][0])
        require(old["name"] == name and old["version"] == pin["from"], "npm-repair-original-bundle-member")
        if name == "brace-expansion":
            require(old.get("dependencies") == {"balanced-match": "^4.0.2"}
                    and not any(key.startswith(prefix + "node_modules/") for key in bundle),
                    "npm-repair-shadowed-bundle-dependency")
            manifest(bundle, "balanced-match", "4.0.4", {}, "package/node_modules/balanced-match/")
        bundle = {key: value for key, value in bundle.items() if not key.startswith(prefix)}
        bundle.update({prefix + key.removeprefix("package/"): value for key, value in material[name].items()})
    bundle_integrity = integrity(distribution(bundle))
    for entry in selected:
        lock = decode_json(read_file(repo, entry["lock"]))
        profile = entry.get("derived_bundle") or entry["derived_libraries"]
        require(digest(read_file(repo, entry["lock"]).replace(b"\r\n", b"\n")) == profile["lock_sha256"],
                "npm-repair-lock-drift")
        if entry.get("derived_bundle"):
            require(bundle_integrity == profile["integrity"]
                    and lock["packages"]["node_modules/npm"]["integrity"] == bundle_integrity,
                    "npm-repair-bundle-distribution-drift")
            for receipt in receipts:
                if receipt["name"] == "http-cache-semantics":
                    receipt["locks"].append(entry["lock"])
            continue
        for receipt in receipts:
            pinned = profile["libraries"][receipt["name"]]
            rows = [row for path, row in lock["packages"].items()
                    if path.rsplit("node_modules/", 1)[-1] == receipt["name"]]
            require(pinned["integrity"] == receipt["derived_integrity"] and bool(rows)
                    and all(row.get("integrity") == receipt["derived_integrity"] for row in rows),
                    "npm-repair-library-distribution-drift")
            receipt["locks"].append(entry["lock"])
    return receipts


def resolve_findings(findings: list, observations: list[dict], receipts: list[dict]) -> tuple[list, list]:
    """Resolve an exact reviewed advisory revision only for verified fixed bytes."""
    observed = {(row["package"]["name"], row["package"]["version"], row["package"]["path"], row["id"], row["modified"])
                for batch in observations for row in batch.get("advisories", [])}
    fixed = set()
    for receipt in receipts:
        for advisory in receipt["advisories"]:
            require(set(advisory) == {"id", "modified"}, "npm-repair-advisory-policy")
            for path in receipt["locks"]:
                identity = (receipt["name"], receipt["version"], path, advisory["id"], advisory["modified"])
                if identity in observed:
                    fixed.add((advisory["id"], path, f"npm:{receipt['name']}@{receipt['version']}"))
    remaining, remediated = [], []
    for item in findings:
        key = (item.finding, item.path, item.package)
        (remediated if item.scanner == "osv" and key in fixed else remaining).append(item)
    return remaining, remediated

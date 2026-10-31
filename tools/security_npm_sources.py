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
                "http-cache-semantics": {"index.js"},
                "deepmerge": {"index.js", "dist/cjs.js", "dist/umd.js"}}
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


CHECKOUT_PROFILE = "checkout-deepmerge-source-v1"
CHECKOUT_REFERENCE = "KirilsTurkins/lsf-checkout@842365d0a25bf5a868311e4cb89c908bdcab4bb8"
CHECKOUT_PREFIX = ".github/security/actions/checkout/"
CHECKOUT_ARCHIVE = "file:.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar"
ACTION_PROFILE = "deepmerge-action-source-v1"
ACTION_VERIFIER_SOURCE = ".lsf-source/verify-installed-deepmerge.mjs"
ACTION_REFERENCES = {
    ".github/security/actions/setup-java/":
        "KirilsTurkins/lsf-setup-java@5d910981b146bc2d4fd97fa349210f3e3d454039",
    ".github/security/actions/setup-node/":
        "KirilsTurkins/lsf-setup-node@fdae00b14e855eb751452bc70c64dde286270415",
    ".github/security/actions/setup-python/":
        "KirilsTurkins/lsf-setup-python@14de4ddb02861c1e098a1a260a2de7a6b45b68fb",
    ".github/security/actions/upload-artifact/":
        "KirilsTurkins/lsf-upload-artifact@5c42799caf30eda69cb2db5da0be2400c47cef16",
}


def source_identity(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": digest(raw),
            "gitBlob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def action_source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict | None:
    """Recognize one published action graph; registry-only historical graphs stay ordinary."""
    if entry.get("source_repair") is None:
        return None
    profile = entry["source_repair"]
    prefixes = [prefix for prefix in ACTION_REFERENCES if entry["path"] == prefix + "package.json"
                and entry["lock"] == prefix + "package-lock.json"]
    require((profile == CHECKOUT_PROFILE
             and entry["path"] == CHECKOUT_PREFIX + "package.json"
             and entry["lock"] == CHECKOUT_PREFIX + "package-lock.json")
            or (profile == ACTION_PROFILE and len(prefixes) == 1),
            "unreviewed-action-source-profile")
    target = lock["packages"].get("node_modules/deepmerge", {})
    if target.get("resolved", "").startswith("https://registry.npmjs.org/"):
        return None
    policy = decode_json(read_file(POLICY, "action-source-repairs.json"))
    require(set(policy) == {"schema", "profile", "action", "source_role", "additional_actions",
                            "bindings", "assets", "advisories", "runtime_bundle"}
            and policy["schema"] == 1 and policy["profile"] == CHECKOUT_PROFILE
            and policy["action"] == CHECKOUT_REFERENCE and policy["source_role"] == "development-build-tool"
            and set(policy["bindings"]) == {"manifest", "lock", "metadata"}
            and set(policy["assets"]) == {"archive", "repair", "declaration", "verifier", "workflow", "upstream", "build"},
            "invalid-action-source-policy")
    material = {}
    rows = policy["bindings"] | policy["assets"] if profile == CHECKOUT_PROFILE else {
        key: policy["assets"][key] for key in ("archive", "repair", "declaration", "upstream")}
    for key, row in rows.items():
        require(set(row) == {"snapshot", "source", "role", "bytes", "sha256", "gitBlob"}
                and row["snapshot"].startswith(CHECKOUT_PREFIX if key in policy["bindings"]
                                               else ".github/security/actions/checkout-source/"),
                "invalid-action-source-input")
        raw = read_file(repo, row["snapshot"])
        require(source_identity(raw) == {field: row[field] for field in ("bytes", "sha256", "gitBlob")},
                "action-source-input-drift")
        material[key] = raw
    require((profile != CHECKOUT_PROFILE
             or (policy["bindings"]["manifest"]["snapshot"] == entry["path"]
                 and policy["bindings"]["lock"]["snapshot"] == entry["lock"]))
            and owner.get("devDependencies", {}).get("deepmerge") == CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("overrides", {}) and target.get("version") == "4.3.1"
            and target.get("resolved") == CHECKOUT_ARCHIVE
            and target.get("integrity") == integrity(material["archive"])
            and [path for path in lock["packages"] if path.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "unlocked-action-source-graph")
    actions = decode_json(read_file(repo, ".github/security/actions.json"))["actions"]
    if profile == CHECKOUT_PROFILE:
        reference = CHECKOUT_REFERENCE
        action = actions.get(reference, {})
        expected = [{"snapshot": row["snapshot"], "source": row["source"],
                     "sha256": row["sha256"], "source_sha256": row["sha256"]}
                    for row in policy["bindings"].values()]
        require(action.get("repository") == "KirilsTurkins/lsf-checkout"
                and action.get("revision") == reference.split("@")[1]
                and action.get("kind") == "npm" and isinstance(action.get("files"), list)
                and sorted(action["files"], key=lambda row: row["source"])
                    == sorted(expected, key=lambda row: row["source"])
                and action.get("metadata") == expected[2], "action-source-revision-drift")
        return {"policy": policy, "material": material, "reference": reference, "checkout": True}

    additional = policy["additional_actions"]
    require(set(additional) == {"profile", "source_role", "references", "verifier"}
            and additional["profile"] == ACTION_PROFILE
            and additional["source_role"] == "development-build-tool"
            and additional["references"] == ACTION_REFERENCES, "invalid-additional-action-source-policy")
    verifier = additional["verifier"]
    require(set(verifier) == {"snapshot", "source", "role", "bytes", "sha256", "gitBlob"}
            and verifier["source"] == ACTION_VERIFIER_SOURCE
            and verifier["role"] == "installed-source-verifier"
            and source_identity(read_file(repo, verifier["snapshot"]))
                == {field: verifier[field] for field in ("bytes", "sha256", "gitBlob")},
            "additional-action-source-verifier-drift")
    prefix = prefixes[0]
    reference = ACTION_REFERENCES[prefix]
    action = actions.get(reference, {})
    files = {row.get("source"): row for row in action.get("files", [])}
    expected_sources = {"action.yml", "package.json", "package-lock.json", ACTION_VERIFIER_SOURCE}
    require(action.get("repository") == reference.split("@")[0]
            and action.get("revision") == reference.split("@")[1]
            and action.get("kind") == "npm" and set(files) == expected_sources
            and files["package.json"]["snapshot"] == entry["path"]
            and files["package-lock.json"]["snapshot"] == entry["lock"]
            and files["action.yml"]["snapshot"] == prefix + "action.yml.snapshot"
            and files[ACTION_VERIFIER_SOURCE] == {
                "snapshot": verifier["snapshot"], "source": verifier["source"],
                "sha256": verifier["sha256"], "source_sha256": verifier["sha256"]}
            and action.get("metadata") == files["action.yml"], "action-source-revision-drift")
    for row in files.values():
        require(row["sha256"] == row["source_sha256"]
                and digest(read_file(repo, row["snapshot"])) == row["sha256"],
                "action-source-binding-drift")
    return {"policy": policy, "material": material, "reference": reference, "checkout": False}


def action_library_sources(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    selected = action_source_inputs(repo, entry, owner, lock)
    return {} if selected is None else {"deepmerge": {
        "version": "4.3.1", "resolved": CHECKOUT_ARCHIVE,
        "integrity": integrity(selected["material"]["archive"])}}


def verify_action_sources(repo: Path, packages: list, configuration: dict, fetch=registry_archive) -> list[dict]:
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("source_repair") is None or not any(item.path == entry["lock"] for item in packages):
            continue
        selected = action_source_inputs(repo, entry, decode_json(read_file(repo, entry["path"])),
                                        decode_json(read_file(repo, entry["lock"])))
        if selected is None:
            continue
        policy, material = selected["policy"], selected["material"]
        declaration, repair = (decode_json(material[key]) for key in ("declaration", "repair"))
        pin = {"name": "deepmerge", "version": "4.3.1", "integrity": declaration["upstream"]["integrity"]}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and integrity(upstream) == pin["integrity"],
                "action-source-upstream-drift")
        original = members(upstream)
        manifest(original, pin["name"], pin["version"], {})
        repaired = source_repair(original, repair, pin)
        require(distribution(repaired) == material["archive"]
                and declaration["profile"] == repair["profile"]
                and declaration["repair"]["sha256"] == digest(material["repair"])
                and declaration["derived"]["integrity"] == integrity(material["archive"])
                and declaration["forkBuildVerified"] is False
                and declaration["runtimeOrSignedSDKQualified"] is False
                and declaration["notAnUpstreamFixedRelease"] is True,
                "action-source-reconstruction-drift")
        require(len(declaration["fileIdentities"]) == len(original)
                and {row["path"] for row in declaration["fileIdentities"]}
                    == {path.removeprefix("package/") for path in original}, "action-source-file-coverage")
        for row in declaration["fileIdentities"]:
            key = "package/" + row["path"]
            require(row["before"] == source_identity(original[key][0])
                    and row["after"] == source_identity(repaired[key][0])
                    and row["mode"] == oct(original[key][1]) == oct(repaired[key][1]),
                    "action-source-file-drift")
        receipt = {"name": pin["name"], "version": pin["version"],
                   "profile": policy["profile"] if selected["checkout"] else ACTION_PROFILE,
                   "upstream_integrity": pin["integrity"],
                   "derived_integrity": integrity(material["archive"]),
                   "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                   "locks": [entry["lock"]], "advisories": policy["advisories"],
                   "action": selected["reference"], "source_role": "development-build-tool"}
        if selected["checkout"]:
            build = decode_json(material["build"])
            review = build["artifactReview"]
            installed = review["installed"]
            require(build["repository"] == "KirilsTurkins/lsf-checkout"
                    and build["publishedRevision"] == CHECKOUT_REFERENCE.split("@")[1]
                    and build["builtHead"] == installed["sourceCommit"] == "1d698c70938869d668a809ef4f9670156bf18809"
                    and build["builtTree"] == build["publishedTree"] == "9dc7521dc1111fe9ac5037a37e5bfff2eb77db6e"
                    and build["run"] == 40884108136 and build["job"] == 123483100746
                    and build["jobConclusion"] == "success" and build["node"] == installed["node"] == "24.19.0"
                    and build["npm"] == "11.17.0"
                    and build["existingBuildFormatLintJestAndStrictDistReadmeComparisonPassed"] is True
                    and review["installedSourceVerified"] is True
                    and review["existingJestTestsPassed"] == 128 and review["existingJestSuitesPassed"] == 10
                    and installed["repairSha256"] == digest(material["repair"])
                    and installed["installedPostimages"]
                        == {row["path"]: row["afterSha256"] for row in repair["files"]},
                    "action-source-build-evidence-drift")
            require(policy["runtime_bundle"] == {
                        "source": "dist/index.js", "bytes": 1465687,
                        "sha256": "116aa6f7b8efa570e95179673c8d067b39069df63915f0b805a413723b798cac",
                        "gitBlob": "8f3d1593c2f1b48addb8c63595f6ea2f1d188b85"},
                    "action-source-runtime-identity-drift")
            for name, source in (("manifest", "package.json"), ("lock", "package-lock.json"),
                                 ("runtime_bundle", "dist/index.js")):
                binding = policy[name] if name == "runtime_bundle" else policy["bindings"][name]
                require(review["payloads"]["lsf-checkout/lsf-checkout/" + source]
                        == {field: binding[field] for field in ("bytes", "sha256")},
                        "action-source-built-input-drift")
            receipt.update({"built_tree": build["builtTree"], "build_run": build["run"]})
        else:
            receipt["verifier_sha256"] = policy["additional_actions"]["verifier"]["sha256"]
        receipts.append(receipt)
    return receipts



def verify_sources(repo: Path, packages: list, configuration: dict, fetch=registry_archive) -> list[dict]:
    """Produce receipts only after every selected source/lock byte is verified."""
    action_receipts = verify_action_sources(repo, packages, configuration, fetch)
    selected = [entry for entry in configuration["manifests"]
                if (entry.get("derived_bundle") or entry.get("derived_libraries"))
                and any(package.path == entry["lock"] for package in packages)]
    if not selected:
        return action_receipts
    policy = decode_json(read_file(POLICY, "npm-source-repairs.json"))
    require(set(policy) == {"schema", "source_sha256", "builder_sha256", "repairs"}
            and policy["schema"] == 1 and set(policy["repairs"]) == {"braces", "http-cache-semantics", "deepmerge"},
            "npm-repair-policy")
    for path, field in (("website/toolchain/source.json", "source_sha256"),
                        ("website/toolchain/prepare.py", "builder_sha256")):
        require(digest(read_file(repo, path).replace(b"\r\n", b"\n")) == policy[field],
                "npm-repair-control-input-drift")
    source = decode_json(read_file(repo, "website/toolchain/source.json"))
    require(set(source) == {"schema", "profile", "base", "patches", "libraries", "repairs"}
            and source["schema"] == 1 and source["profile"] == "npm-11.19.1-lsf-bundle-v5"
            and isinstance(source["patches"], list) and len(source["patches"]) == 5
            and isinstance(source["libraries"], list)
            and [pin.get("name") for pin in source["libraries"]] == ["braces", "deepmerge"], "npm-repair-source-profile")
    pins = source["patches"] + source["libraries"]
    require(len({pin["name"] for pin in pins}) == 7
            and {pin["name"] for pin in pins} == {"ip-address", "undici", "brace-expansion", "http-cache-semantics", "braces", "postcss-selector-parser", "deepmerge"},
            "npm-repair-upstream-coverage")
    material = {}
    for pin in pins:
        raw = fetch(pin)
        require(integrity(raw) == pin["integrity"], "npm-repair-upstream-integrity")
        files = members(raw)
        dependencies = {"balanced-match": "^4.0.2"} if pin["name"] == "brace-expansion" else (
            {"fill-range": "^7.1.1"} if pin["name"] == "braces" else
            {"cssesc": "^3.0.0", "util-deprecate": "^1.0.2"} if pin["name"] == "postcss-selector-parser" else {})
        manifest(files, pin["name"], pin["version"], dependencies)
        material[pin["name"]] = files
    receipts = []
    require(isinstance(source["repairs"], list) and len(source["repairs"]) == 3, "npm-repair-document-coverage")
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
        if name == "postcss-selector-parser":
            require(old.get("dependencies") == {"cssesc": "^3.0.0", "util-deprecate": "^1.0.2"}
                    and not any(key.startswith(prefix + "node_modules/") for key in bundle),
                    "npm-repair-shadowed-bundle-dependency")
            for dependency_name, version in (("cssesc", "3.0.0"), ("util-deprecate", "1.0.2")):
                manifest(bundle, dependency_name, version, {}, "package/node_modules/"+dependency_name+"/")
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
    return receipts + action_receipts


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

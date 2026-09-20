#!/usr/bin/env python3
"""Versioned CI suite contracts and conservative, offline Cargo dependency closure.

Selection reads committed manifests, never Cargo metadata, a registry, or a build.
Execution-time Cargo artifacts remain authoritative about what was actually built.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tools/ci/suites.json"
SCHEMA = "latent.ci.suites.v1"
MAX_BYTES = 2 * 1024 * 1024
BOUNDARIES = {"host", "runtime", "product", "qualification"}
FULL_JOBS = {"rust", "oci-registry", "catalog", "msrv", "contracts", "sdks"}
ALL_JOBS = {"profile", "docs", "website", "fast", *FULL_JOBS}


class InventoryError(ValueError):
    """A missing or ambiguous contract may not waive validation."""


def require(condition: object, reason: str) -> None:
    if not condition:
        raise InventoryError(reason)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-inventory-key")
        result[key] = value
    return result


def path_name(name: str) -> bool:
    return (isinstance(name, str) and 0 < len(name.encode("utf-8")) <= 4096
            and not any(ord(c) < 32 for c in name) and "\\" not in name
            and all(p not in {"", ".", ".."} for p in name.split("/")))


def read_json(path: Path) -> dict:
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "inventory-byte-limit")
    result = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(result, dict), "inventory-object")
    return result


def load(path: Path = INVENTORY) -> dict:
    data = read_json(path)
    require(data.get("schemaVersion") == SCHEMA, "inventory-version")
    require(set(data["boundaries"]) == BOUNDARIES, "inventory-boundaries")
    require(set(data["narrowPackages"]) <= set(data["fastPackages"]), "narrow-package-not-fast")
    require(len(data["fastPackages"]) == len(set(data["fastPackages"])), "duplicate-fast-package")
    keys = set()
    for suite in data["suites"]:
        key = suite["id"]
        require(isinstance(key, str) and re.fullmatch(r"[a-z0-9][a-z0-9_.-]+", key), "suite-id")
        require(key not in keys, "duplicate-suite-id")
        keys.add(key)
        require(suite["boundary"] in BOUNDARIES, "suite-boundary")
        require(suite["resourceClass"] in data["resourceClasses"], "suite-resource-class")
        require(type(suite["timeoutSeconds"]) is int and 0 < suite["timeoutSeconds"] <= 7200,
                "suite-timeout")
        require(suite["platforms"] and suite["prerequisites"] and suite["recipe"], "suite-recipe")
        require(path_name(suite["manifest"]) and path_name(suite["source"]), "suite-source")
        require(suite["kind"] in {"lib", "test", "bin", "example", "cdylib"}, "suite-target-kind")
        require(suite["mode"] in {"libtest", "custom", "compile-only"}, "suite-mode")
        if suite["mode"] == "custom":
            require(suite.get("listContract") == "unsupported" and suite.get("runArgs") == []
                    and suite.get("successMarker"), "custom-harness-contract")
        if suite["mode"] == "libtest":
            require(suite.get("minimumCases", 0) > 0, "empty-suite-contract")
        if suite["mode"] != "custom":
            require(isinstance(suite.get("expectedCases"), list) and
                    isinstance(suite.get("expectedIgnored"), list), "missing-exact-discovery-contract")
            require(len(suite["expectedCases"]) == suite["minimumCases"] and
                    len(suite["expectedCases"]) == len(set(suite["expectedCases"])), "case-count-contract")
            require(set(suite["expectedIgnored"]) <= set(suite["expectedCases"]), "ignored-case-contract")
        require(len(suite.get("ignoredLeaves", [])) == len(set(suite.get("ignoredLeaves", []))),
                "duplicate-ignored-case")
    for key, selected in data["selections"].items():
        require(selected["suite"] in keys and selected["names"], "empty-exact-selection")
        require(len(selected["names"]) == len(set(selected["names"])), "duplicate-selected-case")
        require(type(selected["ignored"]) is bool, "selection-ignore-state")
        require(selected["timeoutSeconds"] > 0 and selected["resourceClass"] in data["resourceClasses"],
                "selection-execution-contract")
        require(all(name == selected["filter"] if selected["exact"] else selected["filter"] in name
                    for name in selected["names"]), "selection-filter-mismatch")
    return data


@dataclass(frozen=True)
class Package:
    name: str
    directory: str
    dependencies: frozenset[str]


def workspace(root: Path) -> dict[str, Package]:
    """Include normal, build, dev, optional and every platform's path dependencies.

    Workspace-inherited/renamed dependencies are resolved to package identity.
    An unresolved local dependency, symlink or unsupported member spelling fails
    closed instead of quietly dropping an edge. This deliberately overselects.
    """
    root = root.resolve(strict=True)
    document = tomllib.loads((root / "Cargo.toml").read_text())
    config = document["workspace"]
    members = config["members"]
    require(isinstance(members, list) and 0 < len(members) <= 512, "workspace-members")
    inherited = config.get("dependencies", {})
    documents = {}
    directories = {}
    for member in members:
        require(path_name(member) and not any(c in member for c in "*?[]"), "unsupported-member")
        directory = root / member
        require(directory.resolve(strict=True) == directory and not directory.is_symlink(), "linked-member")
        manifest = directory / "Cargo.toml"
        require(not manifest.is_symlink(), "linked-manifest")
        d = tomllib.loads(manifest.read_text())
        name = d["package"]["name"]
        require(name not in documents, "duplicate-package")
        documents[name] = (member, d)
        directories[directory] = name
    result = {}
    for name, (member, d) in documents.items():
        dependencies = set()
        for scope in (d, *d.get("target", {}).values()):
            for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                for alias, value in scope.get(kind, {}).items():
                    if not isinstance(value, dict):
                        continue
                    base = root / member
                    if value.get("workspace"):
                        require(alias in inherited, "missing-inherited-dependency")
                        value = inherited[alias]
                        base = root
                    if isinstance(value, dict) and "path" in value:
                        directory = (base / value["path"]).resolve(strict=True)
                        require(directory in directories, "unregistered-path-dependency")
                        target = directories[directory]
                        require(value.get("package", alias) == target, "renamed-package-mismatch")
                        dependencies.add(target)
        result[name] = Package(name, member, frozenset(dependencies))
    return result


def closure(graph: dict[str, Package], names: set[str], *, reverse: bool = False) -> set[str]:
    require(names <= graph.keys(), "unknown-package")
    reached = set(names)
    while True:
        additions = ({p.name for p in graph.values() if p.dependencies & reached} if reverse else
                     {d for n in reached for d in graph[n].dependencies})
        if additions <= reached:
            return reached
        reached |= additions


def affected(root: Path, paths: list[str], data: dict | None = None) -> tuple[str, tuple[str, ...], bool]:
    """Return profile, selected host packages, renderer; caller owns docs policy."""
    data = load() if data is None else data
    graph = workspace(root)
    fast = set(data["fastPackages"])
    require(fast <= graph.keys(), "missing-fast-package")
    changed = set()
    unknown = False
    non_cargo = False
    for name in paths:
        if not path_name(name):
            unknown = True
            continue
        owner = next((p for p in graph.values() if name.startswith(p.directory + "/")), None)
        # Manifest/feature/build-recipe changes must inspect the old graph too.
        # Until two-graph selection is qualified, retain full validation.
        if owner and name.endswith(".rs") and name.startswith(owner.directory + "/src/"):
            if not (root / name).is_file() or (root / name).is_symlink():
                unknown = True
            changed.add(owner.name)
        elif owner:
            changed.add(owner.name)
            non_cargo = True
        else:
            non_cargo = True
            unknown = True
    if unknown or not changed:
        return "full", tuple(sorted(fast)), True
    dependents = closure(graph, changed, reverse=True)
    needed = closure(graph, dependents)
    selected = fast & needed
    # Test-free interface packages still compile all affected reverse dependents;
    # core's nonempty host suite exercises their shared value/ownership types.
    selected |= {"latent-core"}
    narrow = (not non_cargo and dependents <= set(data["narrowPackages"]))
    renderer = bool(dependents & set(data["rendererPackages"]))
    return ("fast" if narrow else "full"), tuple(sorted(selected)), renderer


def expected_jobs(profile: str, packages: tuple[str, ...] | list[str]) -> set[str]:
    require(profile in {"docs", "website", "fast", "full"}, "unknown-profile")
    required = {"profile", "docs", "website"}
    if profile == "full":
        required |= FULL_JOBS
    if profile == "fast":
        require(packages, "empty-fast-profile")
        required.add("msrv")
    if packages:
        require(profile not in {"docs", "website"}, "docs-with-rust-selection")
        required.add("fast")
    return required

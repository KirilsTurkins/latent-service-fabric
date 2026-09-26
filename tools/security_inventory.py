"""Inventory resolved SDK/build dependencies without invoking package managers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
import tomllib
from urllib.parse import urlsplit

from tools.security_common import POLICY, decode_json, digest, read_file, require, tracked_paths
from tools.security_sdk_graphs import c_packages, go_packages, legacy_c_tree, legacy_manifest, maven_packages, nuget_packages

MANIFEST_NAMES = frozenset({
    "Cargo.toml", "Cargo.lock", "package.json", "package-lock.json", "npm-shrinkwrap.json",
    "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb", "go.mod", "go.sum", "go.work",
    "pyproject.toml", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "setup.py", "setup.cfg",
    "requirements.txt", "requirements.in", "requirements.lock", "build.gradle", "build.gradle.kts",
    "pom.xml", "gradle.lockfile", "packages.lock.json", "packages.config", "Directory.Packages.props",
    "Gemfile", "Gemfile.lock", "composer.json", "composer.lock", "conanfile.txt", "conanfile.py",
    "vcpkg.json", "CMakeLists.txt", "Directory.Build.props", "Directory.Build.targets", "NuGet.Config", "nuget.config",
    "dependencies.lock.json",
})


@dataclass(frozen=True, order=True)
class Package:
    ecosystem: str
    name: str
    version: str
    path: str

    def public(self) -> dict:
        return asdict(self)


def is_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return (name in MANIFEST_NAMES or name.endswith((".csproj", ".fsproj", ".vbproj", ".gradle", ".gradle.kts"))
            or (name == "global.json" and path.startswith(("sdk/dotnet/", "sdk/dotnet-guest/")))
            or (name.lower().startswith("nuget.") and name.lower().endswith(".config"))
            or (name.startswith("requirements") and name.endswith((".txt", ".in", ".lock"))))


def cargo_inventory(repo: Path, entry: dict) -> tuple[set[str], dict]:
    manifest = tomllib.loads(read_file(repo, entry["path"]).decode())
    payload = read_file(repo, entry["lock"])
    lock = tomllib.loads(payload.decode())
    packages = lock.get("package", [])
    require(isinstance(packages, list) and len(packages) > 0, "empty-cargo-lock")
    covered = {entry["path"], entry["lock"]}
    names = {item["name"] for item in packages if "source" not in item}
    if entry.get("isolated") is True:
        require(manifest.get("workspace") == {}
                and digest(read_file(repo, entry["path"]).replace(b"\r\n", b"\n")) == entry["manifest_sha256"],
                "unreviewed-isolated-cargo-manifest")
        require(manifest["package"]["name"] in names, "isolated-package-missing-from-lock")
        members = []
    else:
        members = manifest["workspace"]["members"]
        require(isinstance(members, list) and 0 < len(members) <= 256, "invalid-cargo-members")
    for member in members:
        require(isinstance(member, str) and not any(char in member for char in "*?["), "unreviewed-workspace-glob")
        path = f"{member}/Cargo.toml"
        package = tomllib.loads(read_file(repo, path).decode())["package"]
        require(package["name"] in names, "workspace-member-missing-from-lock")
        covered.add(path)
    for package in packages:
        require(package.get("source", "") in {"", "registry+https://github.com/rust-lang/crates.io-index"},
                "unreviewed-cargo-registry-or-git-source")
    return covered, {"path": entry["path"], "coverage": "RustSec", "lock": entry["lock"],
                     "lock_sha256": digest(payload), "packages": len(packages), "members": len(members)}


def npm_packages(repo: Path, entry: dict) -> list[Package]:
    manifest = decode_json(read_file(repo, entry["path"]))
    lock = decode_json(read_file(repo, entry["lock"]))
    require(isinstance(lock, dict) and lock.get("lockfileVersion") in {2, 3}, "unsupported-npm-lock")
    resolved = lock.get("packages")
    require(isinstance(resolved, dict) and "" in resolved, "missing-npm-resolved-graph")
    for kind in ("dependencies", "devDependencies", "optionalDependencies"):
        require(manifest.get(kind, {}) == resolved[""].get(kind, {}), "npm-manifest-lock-drift")
        for name in manifest.get(kind, {}):
            require(f"node_modules/{name}" in resolved, "npm-direct-dependency-missing")
    bundled = entry.get("bundled_package")
    bundled_prefix = None
    if bundled is not None:
        require(isinstance(bundled, str) and re.fullmatch(r"(?:@[a-z0-9-]+/)?[a-z0-9-]+", bundled),
                "invalid-reviewed-npm-bundle")
        owner = resolved.get(f"node_modules/{bundled}", {})
        location = urlsplit(owner.get("resolved", ""))
        require(manifest.get("dependencies", {}).get(bundled) == owner.get("version")
                and location.scheme == "https" and location.hostname == "registry.npmjs.org"
                and re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", owner.get("integrity", ""))
                and isinstance(owner.get("bundleDependencies"), list) and owner["bundleDependencies"],
                "unlocked-reviewed-npm-bundle")
        bundled_prefix = f"node_modules/{bundled}/node_modules/"
    packages = []
    for path, dependency in resolved.items():
        if not path:
            continue
        require(path.startswith("node_modules/") and not dependency.get("link"), "unsupported-npm-link")
        name = dependency.get("name") or path.rsplit("node_modules/", 1)[1]
        version = dependency.get("version", "")
        location = urlsplit(dependency.get("resolved", ""))
        # npm ships its dependencies inside its integrity-pinned tarball. Opt-in
        # ownership is explicit in the policy; every bundled version is scanned.
        bundled_source = (bundled_prefix is not None and path.startswith(bundled_prefix)
                          and dependency.get("inBundle") is True and not dependency.get("resolved"))
        require(bundled_source or (location.scheme == "https" and location.hostname == "registry.npmjs.org"),
                "unreviewed-npm-registry-or-source")
        require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version) is not None,
                "unresolved-npm-version")
        packages.append(Package("npm", name, version, entry["lock"]))
    require(bool(packages), "empty-npm-dependency-graph")
    return packages


def pypi_packages(repo: Path, path: str) -> list[Package]:
    text = read_file(repo, path).decode().replace("\\\r\n", " ").replace("\\\n", " ")
    packages = []
    for line in text.splitlines():
        line = re.sub(r"\s+--hash=sha256:[0-9a-f]{64}", "", line).strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.+!-]*)", line)
        require(match is not None, "unresolved-python-requirement")
        name, version = match.groups()
        packages.append(Package("PyPI", re.sub(r"[-_.]+", "-", name).lower(), version, path))
    require(bool(packages), "empty-python-dependency-graph")
    return packages


def inventory(repo: Path, policy: Path = POLICY) -> tuple[list[Package], list[dict]]:
    configuration = decode_json(read_file(policy, "inventory.json"))
    require(configuration.get("schema") == 1, "invalid-inventory-policy")
    paths = tracked_paths(repo)
    covered, packages, records = set(), [], []
    for entry in configuration["manifests"]:
        path = entry["path"]
        require(path not in covered, "duplicate-inventory-path")
        optional_directory = entry.get("absent_when_directory_missing")
        if optional_directory is not None:
            require(optional_directory == str(PurePosixPath(path).parent) and optional_directory != ".",
                    "invalid-optional-inventory-directory")
            if not any(candidate == optional_directory or candidate.startswith(optional_directory + "/") for candidate in paths):
                records.append({"path": path, "coverage": "not-shipped-at-source-revision", "packages": 0})
                continue
        if entry["kind"] == "c-sources" and legacy_c_tree(repo, entry, set(paths)):
            records.append({"path": path, "coverage": "reviewed-no-external-packages", "packages": 0,
                            "boundary": "Exact reviewed legacy C interface tree, not a transport implementation."})
            continue
        payload = read_file(repo, path)
        if entry["kind"] == "cargo":
            cargo_paths, record = cargo_inventory(repo, entry)
            covered.update(cargo_paths)
            records.append(record)
            continue
        if entry["kind"] == "npm":
            current = npm_packages(repo, entry)
            covered.add(entry["lock"])
        elif entry["kind"] == "pypi":
            current = pypi_packages(repo, path)
        elif entry["kind"] in {"go-locked", "maven-locked", "nuget-locked"}:
            if legacy_manifest(repo, entry, set(paths)):
                current = []
            else:
                reader = {"go-locked": go_packages, "maven-locked": maven_packages, "nuget-locked": nuget_packages}[entry["kind"]]
                current = [Package(ecosystem, name, version, entry["lock"])
                           for ecosystem, name, version in reader(repo, entry)]
                covered.add(entry["lock"])
                if entry["kind"] == "go-locked":
                    covered.add(entry["sum"])
                if entry["kind"] == "nuget-locked":
                    covered.update(item["path"] for item in entry.get("configuration", []))
        elif entry["kind"] == "nuget-aot-locked":
            from tools.security_native_aot import packages as native_aot_packages
            current = [Package(ecosystem, name, version, entry["lock"])
                       for ecosystem, name, version in native_aot_packages(repo, entry)]
            covered.add(entry["lock"])
            covered.update(item["path"] for item in entry["configuration"])
        elif entry["kind"] == "c-sources":
            current = [Package(ecosystem, name, version, path) for ecosystem, name, version in c_packages(repo, path)]
        elif entry["kind"] == "no-external-packages":
            require(digest(payload.replace(b"\r\n", b"\n")) == entry["sha256"], "unreviewed-sdk-manifest-change")
            current = []
        else:
            require(False, "unknown-inventory-kind")
        packages.extend(current)
        covered.add(path)
        records.append({"path": path, "coverage": "OSV" if current else "reviewed-no-external-packages",
                        "sha256": digest(payload), "packages": len(current)})
        if entry["kind"] == "c-sources":
            records[-1]["boundary"] = "OSV source-commit and PyPI queries; upstream native advisories need separate review."
    for entry in configuration.get("non_manifest_modules", []):
        path = entry["path"]
        require(digest(read_file(repo, path).replace(b"\r\n", b"\n")) == entry["sha256"], "unreviewed-manifest-lookalike")
        covered.add(path)
    discovered = {path for path in paths if is_manifest(path)}
    require(discovered == covered, "unreviewed-or-missing-dependency-manifest")
    control_path = "controls/.github/security/requirements.txt"
    control_packages = pypi_packages(policy, "requirements.txt")
    packages.extend(Package(item.ecosystem, item.name, item.version, control_path) for item in control_packages)
    records.append({"path": control_path, "coverage": "OSV-scanner-controls", "packages": len(control_packages),
                    "sha256": digest(read_file(policy, "requirements.txt"))})
    require(0 < len(packages) <= 5000, "sdk-package-count-limit")
    return sorted(set(packages)), records

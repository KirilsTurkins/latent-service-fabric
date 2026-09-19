"""Read reviewed, resolved SDK graphs as data, never execute a build system."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as element_tree

from tools.security_common import decode_json, digest, read_file, relative_path, require

SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9.-]+)?")
GO_VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
MODULE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~/-]*")
GO_SUM = re.compile(r"h1:[A-Za-z0-9+/]{43}=")


def normalized(payload: bytes) -> bytes:
    return payload.replace(b"\r\n", b"\n")


def legacy_manifest(repo: Path, entry: dict, paths: set[str]) -> bool:
    payload = read_file(repo, entry["path"])
    if digest(normalized(payload)) != entry.get("legacy_sha256"):
        return False
    require(entry["lock"] not in paths, "unexpected-legacy-sdk-lock")
    if entry["kind"] == "go-locked":
        require(entry["sum"] not in paths, "unexpected-legacy-sdk-sums")
    return True


def go_packages(repo: Path, entry: dict) -> list[tuple[str, str, str]]:
    manifest = normalized(read_file(repo, entry["path"]))
    sums = normalized(read_file(repo, entry["sum"]))
    lock = decode_json(read_file(repo, entry["lock"]))
    require(isinstance(lock, dict) and set(lock) == {
        "schemaVersion", "module", "goVersion", "manifestSha256", "sumSha256", "modules", "tools"}, "invalid-go-lock")
    require(lock["schemaVersion"] == 1 and lock["module"] == entry["module"], "invalid-go-lock-identity")
    require(lock["manifestSha256"] == digest(manifest) and lock["sumSha256"] == digest(sums),
            "go-manifest-lock-drift")
    require(isinstance(lock["goVersion"], str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", lock["goVersion"]),
            "unresolved-go-toolchain")
    checksums = {}
    for line in sums.decode().splitlines():
        parts = line.split()
        require(len(parts) == 3 and GO_SUM.fullmatch(parts[2]), "invalid-go-checksum")
        identity = tuple(parts[:2])
        require(identity not in checksums, "duplicate-go-checksum")
        checksums[identity] = parts[2]
    modules = lock["modules"]
    require(isinstance(modules, list) and 0 < len(modules) <= 1024, "invalid-go-module-count")
    selected = {}
    for item in modules:
        require(isinstance(item, dict) and set(item) == {"path", "version", "sum", "goModSum"}, "invalid-go-module")
        require(all(isinstance(value, str) for value in item.values()), "invalid-go-module-value")
        name, version = item["path"], item["version"]
        require(isinstance(name, str) and MODULE.fullmatch(name) and name not in selected,
                "invalid-or-duplicate-go-module")
        require(isinstance(version, str) and GO_VERSION.fullmatch(version), "unresolved-go-version")
        require(item["sum"] == checksums.get((name, version)) and GO_SUM.fullmatch(item["sum"]),
                "go-module-checksum-drift")
        require(item["goModSum"] == checksums.get((name, version + "/go.mod"))
                and GO_SUM.fullmatch(item["goModSum"]), "go-manifest-checksum-drift")
        selected[name] = version
    tools = lock["tools"]
    require(isinstance(tools, list) and len(tools) <= 16, "invalid-go-tool-count")
    tool_names = set()
    for item in tools:
        require(isinstance(item, dict) and set(item) == {"path", "module", "version"}
                and all(isinstance(value, str) for value in item.values()), "invalid-go-tool")
        name, module, version = item["path"], item["module"], item["version"]
        require(name not in tool_names and selected.get(module) == version
                and (name == module or name.startswith(module + "/")), "go-tool-lock-drift")
        tool_names.add(name)
    block, module_seen, version_seen = None, False, False
    declared_tools = set()
    for line in manifest.decode().splitlines():
        parts = line.split("//", 1)[0].split()
        if not parts:
            continue
        if parts == [")"]:
            require(block is not None, "invalid-go-block")
            block = None
            continue
        if len(parts) == 2 and parts[1] == "(":
            require(block is None and parts[0] in {"require", "tool"}, "unreviewed-go-directive")
            block = parts[0]
            continue
        directive, values = (block, parts) if block else (parts[0], parts[1:])
        if directive == "module":
            require(not module_seen and values == [entry["module"]], "go-module-identity-drift")
            module_seen = True
        elif directive == "go":
            require(not version_seen and values == [lock["goVersion"]], "go-toolchain-lock-drift")
            version_seen = True
        elif directive == "toolchain":
            require(values == ["go" + lock["goVersion"]], "go-toolchain-lock-drift")
        elif directive == "require":
            require(len(values) == 2 and selected.get(values[0]) == values[1], "go-required-module-missing")
        elif directive == "tool":
            require(len(values) == 1 and values[0] in tool_names and values[0] not in declared_tools,
                    "go-tool-module-missing")
            declared_tools.add(values[0])
        else:
            require(False, "unreviewed-go-directive")
    require(block is None and module_seen and version_seen, "incomplete-go-manifest")
    require(declared_tools == tool_names, "go-tool-lock-drift")
    return [("Go", name, version) for name, version in selected.items()] + [("Go", "stdlib", lock["goVersion"])]


def maven_packages(repo: Path, entry: dict) -> list[tuple[str, str, str]]:
    require(digest(normalized(read_file(repo, entry["path"]))) == entry["manifest_sha256"],
            "unreviewed-maven-build-logic")
    lock = decode_json(read_file(repo, entry["lock"]))
    require(isinstance(lock, dict) and set(lock) == {"schemaVersion", "maven", "artifacts"}
            and lock["schemaVersion"] == 1 and lock["maven"] == "https://repo.maven.apache.org/maven2/",
            "invalid-maven-lock")
    artifacts = lock["artifacts"]
    require(isinstance(artifacts, list) and 0 < len(artifacts) <= 512, "invalid-maven-artifact-count")
    packages, seen = set(), set()
    for item in artifacts:
        require(isinstance(item, dict) and set(item) == {"path", "sha256", "size", "platform"}, "invalid-maven-artifact")
        path = relative_path(item["path"])
        require(path not in seen and isinstance(item["sha256"], str) and SHA256.fullmatch(item["sha256"]),
                "invalid-or-duplicate-maven-artifact")
        require(type(item["size"]) is int and 0 < item["size"] <= 64 * 1024 * 1024, "maven-artifact-size-limit")
        require(item["platform"] in {"any", "linux-x86_64", "windows-x86_64"}, "unreviewed-maven-platform")
        parts = path.split("/")
        require(len(parts) >= 4 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts), "invalid-maven-coordinate")
        group, name, version = ".".join(parts[:-3]), parts[-3], parts[-2]
        require(VERSION.fullmatch(version), "unresolved-maven-version")
        suffix = ".jar" if item["platform"] == "any" else "-" + item["platform"] + ".exe"
        require(parts[-1] == name + "-" + version + suffix, "maven-coordinate-file-mismatch")
        packages.add(("Maven", group + ":" + name, version))
        seen.add(path)
    return sorted(packages)


def nuget_packages(repo: Path, entry: dict) -> list[tuple[str, str, str]]:
    payload = read_file(repo, entry["path"], 256 * 1024)
    require(b"<!" not in payload and b"<?" not in payload, "unsupported-project-xml")
    project = element_tree.fromstring(payload)
    require(project.tag == "Project" and project.get("Sdk") == "Microsoft.NET.Sdk", "unreviewed-project-sdk")
    direct, references = {}, set()
    tags = {"Project", "PropertyGroup", "ItemGroup", "TargetFramework", "ImplicitUsings", "Nullable",
            "TreatWarningsAsErrors", "RestorePackagesWithLockFile", "Deterministic", "PackageReference",
            "ProjectReference", "Protobuf", "OutputType", "RootNamespace", "AssemblyName", "LangVersion",
            "AllowUnsafeBlocks", "WarningsAsErrors", "EnableDefaultCompileItems", "Compile"}
    for node in project.iter():
        require("Condition" not in node.attrib and node.tag in tags,
                "unreviewed-project-dependency-logic")
        if node.tag == "PackageReference":
            name, version = node.get("Include", ""), node.get("Version", "")
            require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) and VERSION.fullmatch(version)
                    and name.lower() not in direct and not node.get("Update"), "unresolved-nuget-reference")
            direct[name.lower()] = version
        if node.tag == "ProjectReference":
            name = PurePosixPath(node.get("Include", "").replace("\\", "/")).stem.lower()
            require(bool(name), "invalid-project-reference")
            references.add(name)
    lock = decode_json(read_file(repo, entry["lock"]))
    require(isinstance(lock, dict) and set(lock) == {"version", "dependencies"} and lock["version"] == 1,
            "invalid-nuget-lock")
    frameworks = lock["dependencies"]
    require(isinstance(frameworks, dict) and 0 < len(frameworks) <= 16, "invalid-nuget-framework-count")
    declared_frameworks = [node.text for node in project.iter("TargetFramework")]
    require(len(declared_frameworks) == 1 and declared_frameworks[0] in frameworks, "nuget-framework-lock-drift")
    packages = set()
    for framework, dependencies in frameworks.items():
        require(framework == declared_frameworks[0] or framework.startswith(declared_frameworks[0] + "/"),
                "unreviewed-nuget-framework")
        require(isinstance(dependencies, dict) and 0 < len(dependencies) <= 1024, "invalid-nuget-package-count")
        names, observed = {name.lower() for name in dependencies}, {}
        require(len(names) == len(dependencies), "duplicate-nuget-name")
        for name, item in dependencies.items():
            require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) and isinstance(item, dict)
                    and item.get("type") in {"Direct", "Transitive", "Project"}, "invalid-nuget-package")
            edges = item.get("dependencies", {})
            require(isinstance(edges, dict) and all(edge.lower() in names for edge in edges), "incomplete-nuget-graph")
            if item["type"] == "Project":
                require(name.lower() in references and set(item) <= {"type", "dependencies"}, "unreviewed-project-lock")
                continue
            version, checksum = item.get("resolved", ""), item.get("contentHash", "")
            require(isinstance(version, str) and VERSION.fullmatch(version), "unresolved-nuget-version")
            require(isinstance(checksum, str) and re.fullmatch(r"[A-Za-z0-9+/]{86}==", checksum), "invalid-nuget-checksum")
            if item["type"] == "Direct":
                observed[name.lower()] = version
            packages.add(("NuGet", name, version))
        require(observed == direct, "nuget-manifest-lock-drift")
    require(bool(packages), "empty-nuget-dependency-graph")
    return sorted(packages)


def c_packages(repo: Path, path: str) -> list[tuple[str, str, str]]:
    lock = decode_json(read_file(repo, path))
    repositories = {"nghttp2": "nghttp2/nghttp2", "nanopb": "nanopb/nanopb", "protoc": "protocolbuffers/protobuf"}
    python_names = {"protobuf", "h2", "hpack", "hyperframe"}
    require(isinstance(lock, dict) and set(lock) == set(repositories) | python_names, "unreviewed-c-dependency-graph")
    packages = []
    for name, item in lock.items():
        allowed = {"version", "role", "purl", "url", "sha256", "commit"}
        if name == "nghttp2":
            allowed.add("bundled")
        require(isinstance(item, dict) and {"version", "role", "purl", "url", "sha256"} <= set(item)
                and set(item) <= allowed, "invalid-c-dependency")
        require(isinstance(item["version"], str) and VERSION.fullmatch(item["version"]), "unresolved-c-version")
        require(isinstance(item["sha256"], str) and SHA256.fullmatch(item["sha256"]), "invalid-c-archive-digest")
        require(item["role"] in {"runtime", "runtime-and-generator", "generator-only", "generator-and-test-only", "test-only"},
                "unreviewed-c-dependency-role")
        location = urlsplit(item["url"])
        require(location.scheme == "https" and not location.query and not location.fragment
                and not location.username and not location.password and location.port is None, "unreviewed-c-source-url")
        if name in repositories:
            commit = item.get("commit", "")
            repository = repositories[name]
            require(isinstance(commit, str) and COMMIT.fullmatch(commit), "unresolved-c-source-commit")
            if name == "nanopb":
                expected = "https://codeload.github.com/" + repository + "/tar.gz/" + commit
                reference = commit
            else:
                reference = "v" + item["version"]
                filename = "nghttp2-" + item["version"] + ".tar.gz" if name == "nghttp2" else "protoc-" + item["version"] + "-linux-x86_64.zip"
                expected = "https://github.com/" + repository + "/releases/download/" + reference + "/" + filename
            require(item["url"] == expected and item["purl"] == "pkg:github/" + repository + "@" + reference,
                    "c-source-identity-drift")
            packages.append(("GIT", "https://github.com/" + repository, commit))
        else:
            require(location.hostname == "files.pythonhosted.org" and location.path.startswith("/packages/")
                    and item["purl"] == "pkg:pypi/" + name + "@" + item["version"]
                    and PurePosixPath(location.path).name == name + "-" + item["version"] + "-py3-none-any.whl",
                    "unreviewed-c-python-source")
            packages.append(("PyPI", name, item["version"]))
        if name == "nghttp2":
            packages.append(c_bundled_source(item.get("bundled")))
    return packages


def c_bundled_source(bundled: object) -> tuple[str, str, str]:
    require(isinstance(bundled, list) and len(bundled) == 1, "unreviewed-c-bundled-graph")
    item = bundled[0]
    require(isinstance(item, dict) and set(item) == {
        "name", "version", "commit", "role", "purl", "url", "files"}, "invalid-c-bundled-source")
    require(item["name"] == "sfparse" and item["role"] == "bundled-runtime", "unreviewed-c-bundled-source")
    commit = item["commit"]
    require(isinstance(commit, str) and COMMIT.fullmatch(commit) and item["version"] == commit,
            "unresolved-c-bundled-commit")
    require(item["purl"] == "pkg:github/ngtcp2/sfparse@" + commit
            and item["url"] == "https://github.com/ngtcp2/sfparse/tree/" + commit, "c-bundled-source-identity-drift")
    files = item["files"]
    require(isinstance(files, dict) and set(files) == {"lib/sfparse.c", "lib/sfparse.h"}
            and all(isinstance(checksum, str) and SHA256.fullmatch(checksum) for checksum in files.values()),
            "unreviewed-c-bundled-files")
    return "GIT", "https://github.com/ngtcp2/sfparse", commit


def legacy_c_tree(repo: Path, entry: dict, paths: set[str]) -> bool:
    if entry["path"] in paths:
        return False
    selected = sorted(path for path in paths if path.startswith("sdk/c/"))
    require(0 < len(selected) <= 64, "unreviewed-legacy-c-tree")
    identities = [[path, digest(normalized(read_file(repo, path)))] for path in selected]
    identity = digest(json.dumps(identities, separators=(",", ":")).encode())
    require(identity in entry["legacy_tree_sha256"], "unreviewed-legacy-c-tree")
    return True

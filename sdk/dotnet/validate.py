#!/usr/bin/env python3
"""Qualify the scoped .NET client from fresh sources, locked packages and native peers."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdk/dotnet"
PROJECTS = ("Latent.Sdk", "Latent.Sdk.SemanticTests", "Latent.Sdk.Transport", "Latent.Sdk.Transport.Tests", "Latent.Sdk.ProviderWorkflow")
LOCKED = PROJECTS[2:]
PROTOS = ("latent/control/v1/common.proto", "latent/control/v1/policy.proto", "latent/control/v1/capability.proto", "latent/invocation/v1/invocation.proto")
SDK_VERSION = "8.0.425"
RUNTIME_VERSION = "8.0.31"
GRPC_TOOLS = "2.71.0"

sys.path.insert(0, str(ROOT))
from tools.security_common import decode_json, require
from tools.security_sdk_graphs import nuget_packages


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def command(arguments: list[str], directory: Path, environment: dict[str, str], quiet: bool = False) -> str:
    result = subprocess.run(arguments, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, check=False)
    require(len(result.stdout) <= 4 * 1024 * 1024, "dotnet-process-output-bound")
    output = result.stdout.decode("utf-8", errors="strict")
    if result.returncode or not quiet:
        print(output, end="", file=sys.stderr if result.returncode else sys.stdout)
    require(result.returncode == 0, "dotnet-validation-command-failed")
    return output.strip()


def snapshot(destination: Path) -> None:
    paths = [SDK / "global.json", SDK / "nuget.transport.config", ROOT / "sdk/profile/fixtures.json"]
    paths.extend(ROOT / "api/proto" / name for name in PROTOS)
    for project in PROJECTS:
        paths.extend(path for path in (SDK / project).rglob("*") if path.is_file()
                     and not {"target", "bin", "obj"}.intersection(path.relative_to(SDK / project).parts)
                     and (path.suffix in {".cs", ".csproj"} or path.name == "packages.lock.json"))
    require(len(paths) <= 128, "dotnet-source-file-bound")
    for path in paths:
        require(not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024, "dotnet-source-input-bound")
        target = destination / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def package_graph(source: Path, artifacts: Path, packages: Path) -> list[dict]:
    graph = []
    for project in LOCKED:
        directory = source / "sdk/dotnet" / project
        lock = decode_json((directory / "packages.lock.json").read_bytes())["dependencies"]["net8.0"]
        assets = decode_json((artifacts / "obj" / project / "project.assets.json").read_bytes())
        require(set(assets["targets"]) == {"net8.0"}, "dotnet-selected-framework-drift")
        selected = assets["targets"]["net8.0"]
        observed = {identity.rsplit("/", 1)[0].lower(): (identity.rsplit("/", 1)[1], item["type"])
                    for identity, item in selected.items()}
        require(len(observed) == len(selected) and set(observed) == {name.lower() for name in lock}
                and set(assets["libraries"]) == set(selected), "dotnet-selected-graph-incomplete")
        restore = assets["project"]["restore"]
        require(set(restore["sources"]) == {"https://api.nuget.org/v3/index.json"}
                and restore["restoreLockProperties"]["restoreLockedMode"] is True
                and restore["configFilePaths"] == [str(source / "sdk/dotnet/nuget.transport.config")], "dotnet-unreviewed-restore-input")
        for name, item in lock.items():
            version, kind = observed[name.lower()]
            identity = next(value for value in selected if value.rsplit("/", 1)[0].lower() == name.lower())
            require({edge.lower() for edge in item.get("dependencies", {})}
                    == {edge.lower() for edge in selected[identity].get("dependencies", {})}, "dotnet-selected-edge-drift")
            if item["type"] == "Project":
                require(kind == "project", "dotnet-selected-project-drift")
                continue
            require(kind == "package" and version == item["resolved"], "dotnet-selected-package-drift")
            library = assets["libraries"][identity]
            location = packages / library["path"]
            metadata = decode_json((location / ".nupkg.metadata").read_bytes())
            require(library["sha512"] == item["contentHash"] == metadata["contentHash"]
                    and metadata["source"] == "https://api.nuget.org/v3/index.json", "dotnet-content-hash-drift")
            archive = location / f"{name.lower()}.{version}.nupkg"
            archive_hash = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
            require(archive_hash == archive.with_suffix(".nupkg.sha512").read_text().strip(), "dotnet-archive-hash-drift")
            graph.append({"project": project, "name": name, "version": version, "contentHash": item["contentHash"], "archiveSha512": archive_hash})
    return graph


def generation(artifacts: Path, packages: Path, environment: dict[str, str]) -> dict:
    generated = artifacts / "obj/Latent.Sdk.Transport/debug/latent"
    sources = sorted(path for path in generated.rglob("*.cs"))
    require(len(sources) == 7, "dotnet-generated-source-count")
    generator = packages / "grpc.tools" / GRPC_TOOLS / "tools/linux_x64"
    protoc = command([str(generator / "protoc"), "--version"], SDK, environment, quiet=True)
    return {"schemaVersion": 1, "sdkVersion": SDK_VERSION, "runtimeVersion": RUNTIME_VERSION,
            "grpcToolsVersion": GRPC_TOOLS, "protocVersion": protoc,
            "tools": {name: checksum(generator / name) for name in ("protoc", "grpc_csharp_plugin")},
            "inputs": {name: normalized_hash(ROOT / "api/proto" / name) for name in PROTOS},
            "outputs": {str(path.relative_to(generated.parent)).replace("\\", "/"): normalized_hash(path) for path in sources}}


def qualify(dotnet: str, scratch: Path, environment: dict[str, str], quiet: bool) -> tuple[dict, list[dict], list[str]]:
    require(command([dotnet, "--version"], SDK, environment, quiet=True) == SDK_VERSION, "dotnet-sdk-version-mismatch")
    available = command([dotnet, "--list-runtimes"], SDK, environment, quiet=True)
    for framework in ("Microsoft.NETCore.App", "Microsoft.AspNetCore.App"):
        require(any(line.startswith(framework + " " + RUNTIME_VERSION + " ") for line in available.splitlines()), "dotnet-runtime-version-mismatch")
    policy = decode_json((ROOT / ".github/security/inventory.json").read_bytes())
    for project in LOCKED:
        path = f"sdk/dotnet/{project}/{project}.csproj"
        entries = [item for item in policy["manifests"] if item["path"] == path]
        require(len(entries) == 1 and entries[0]["kind"] == "nuget-locked", "dotnet-graph-registration-missing")
        nuget_packages(ROOT, entries[0])
    packages = scratch / "packages"
    packages.mkdir()
    environment["NUGET_PACKAGES"] = str(packages)
    previous, selected, transcripts = None, None, []
    for iteration in ("first", "reproduction"):
        source, artifacts = scratch / iteration / "source", scratch / iteration / "build"
        snapshot(source)
        directory = source / "sdk/dotnet"
        properties = ["-p:ImportDirectoryBuildProps=false", "-p:ImportDirectoryBuildTargets=false",
                      "-p:ImportDirectoryPackagesProps=false", "-p:UseSharedCompilation=false", "-nodeReuse:false"]
        for project in ("Latent.Sdk.Transport.Tests", "Latent.Sdk.ProviderWorkflow", "Latent.Sdk.SemanticTests"):
            path = f"{project}/{project}.csproj"
            command([dotnet, "restore", path, "--locked-mode", "--configfile", "nuget.transport.config",
                     "-p:ArtifactsPath=" + str(artifacts), "-p:NuGetAuditMode=all", *properties], directory, environment, quiet)
            command([dotnet, "build", path, "--no-restore", "--disable-build-servers", "--artifacts-path", str(artifacts),
                     "-v:q", *properties], directory, environment, quiet)
            if project != "Latent.Sdk.ProviderWorkflow" and iteration == "first":
                executable = artifacts / "bin" / project / "debug" / (project + ".dll")
                transcripts.append(command([dotnet, str(executable)], directory, environment, quiet))
        current_graph = package_graph(source, artifacts, packages)
        current = generation(artifacts, packages, environment)
        if previous is not None:
            require(previous == current and selected == current_graph, "dotnet-generation-or-selected-graph-not-reproducible")
        previous, selected = current, current_graph
    for location in sorted(packages.glob("*/*/*.nupkg")):
        command([dotnet, "nuget", "verify", str(location), "--all", "--verbosity", "quiet"], SDK, environment, quiet)
    return previous, selected, transcripts


def advisories() -> dict:
    from tools.security_advisories import query_osv
    from tools.security_inventory import Package
    policy = decode_json((ROOT / ".github/security/inventory.json").read_bytes())
    packages = sorted({Package(ecosystem, name, version, entry["lock"])
                       for entry in policy["manifests"] if entry["kind"] == "nuget-locked" and entry["path"].startswith("sdk/dotnet/")
                       for ecosystem, name, version in nuget_packages(ROOT, entry)})
    findings, observations = query_osv(packages)
    evidence = {"coordinates": [item.public() for item in packages], "observations": observations,
                "findings": [item.public() for item in findings], "exceptionsApplied": False}
    (SDK / "target/osv-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    require(not findings, "unwaived-dotnet-advisory")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--print-generation", action="store_true")
    parser.add_argument("--osv", action="store_true")
    arguments = parser.parse_args()
    require(sys.platform == "linux" and os.uname().machine == "x86_64", "dotnet-qualification-requires-linux-x64")
    require(arguments.check != arguments.print_generation, "choose-check-or-print-generation")
    require(not arguments.osv or arguments.check, "osv-requires-complete-check")
    executable = shutil.which(arguments.dotnet)
    require(executable is not None, "dotnet-sdk-unavailable")
    dotnet = str(Path(executable).resolve())
    target = SDK / "target"
    target.mkdir(exist_ok=True)
    require(not target.is_symlink() and target.resolve().parent == SDK.resolve(), "dotnet-target-outside-sdk")
    with tempfile.TemporaryDirectory(prefix="validation-", dir=target) as temporary:
        scratch = Path(temporary).resolve()
        require(scratch.is_relative_to(target.resolve()), "dotnet-scratch-outside-target")
        home = scratch / "home"
        home.mkdir()
        environment = {key: value for key, value in os.environ.items() if key in {"PATH", "SSL_CERT_FILE", "SSL_CERT_DIR"}}
        environment.update(HOME=str(home), DOTNET_CLI_HOME=str(home), DOTNET_ROOT=str(Path(dotnet).parent),
                           DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_CLI_USE_MSBUILD_SERVER="0",
                           DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", LANG="C.UTF-8", NUGET_XMLDOC_MODE="skip")
        result, packages, transcripts = qualify(dotnet, scratch, environment, arguments.print_generation)
        if arguments.print_generation:
            print(json.dumps(result, indent=2))
        else:
            require(result == decode_json((SDK / "protobuf.lock.json").read_bytes()), "dotnet-generated-bindings-drift")
            evidence = {"generation": result, "packages": packages, "tests": transcripts, "cleanRestores": 2,
                        "packageSignaturesVerified": True, "implicitDirectoryImports": False}
            if arguments.osv:
                evidence["osv"] = advisories()
            (target / "validation-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print("PASS .NET: two clean generations, exact selected package graphs, signatures, native peers and semantic fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

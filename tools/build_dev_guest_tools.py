#!/usr/bin/env python3
"""Build nonpublishing Linux tool candidates from maintained language recipes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dev_tool_distribution as distribution, dev_managed_distribution as managed, native_runtime_build, rust_capsule_project
from tools import dev_go_distribution, dev_typescript_distribution
from tools.build_observation import build_environment, resolve_tools
from tools.build_process import run_bounded
from tools.dev_distribution import assemble, file_digest
from tools.dev_guest_tools import ZIG_BYTES, ZIG_SHA256, ZIG_VERSION
from tools.dev_workflow.common import HOST_ABI, PROTOCOL, encode, require
from tools.dev_workflow.project import LANGUAGES
from tools.install_guest_bindgen import URL as BINDGEN_URL

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE = "python@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419"
SOURCES = {
    "zig": {"url": f"https://ziglang.org/download/{ZIG_VERSION}/zig-x86_64-linux-{ZIG_VERSION}.tar.xz",
            "sha256": "sha256:" + ZIG_SHA256, "maximum": ZIG_BYTES, "version": ZIG_VERSION},
    "wasm-tools": {"url": f"https://github.com/bytecodealliance/wasm-tools/releases/download/v{distribution.WASM_VERSION}/"
                          f"wasm-tools-{distribution.WASM_VERSION}-x86_64-linux.tar.gz",
                   "sha256": "sha256:" + distribution.WASM_SHA256, "maximum": 5862464, "version": distribution.WASM_VERSION},
    "wit-bindgen": {"url": BINDGEN_URL, "sha256": "sha256:" + distribution.ARCHIVE_SHA256,
                    "maximum": 32 * 1024 * 1024, "version": distribution.BINDGEN_VERSION},
}


def download(destination: Path, source: dict) -> None:
    deadline, used = time.monotonic() + 90, 0
    with urllib.request.urlopen(source["url"], timeout=30) as incoming, destination.open("xb") as output:
        while raw := incoming.read(1024 * 1024):
            used += len(raw)
            require(used <= source["maximum"] and time.monotonic() < deadline, "compiler-download-limit")
            output.write(raw)
    require(file_digest(destination)[0] == source["sha256"], "compiler-upstream-archive-digest")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-prefix", type=Path, required=True, help="/usr/local copied from the pinned Python OCI image")
    parser.add_argument("--allow-dirty", action="store_true", help="Unsigned local assembly testing only")
    parser.add_argument("--language", choices=sorted(LANGUAGES), required=True)
    parser.add_argument("--node-tests", action="store_true", help="Also stage source-built node executables for focused contributor tests")
    args = parser.parse_args()
    require(sys.platform == "linux", "guest-candidate-linux-builder-required")
    output = args.output.absolute()
    require(output.is_relative_to(ROOT / "target") and not output.exists(), "new-owned-build-directory-required")
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    require(args.allow_dirty or not dirty, "clean-source-required-for-candidate")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    epoch = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT))
    output.mkdir(mode=0o700, parents=True)
    environment = build_environment(output)
    environment["RUSTUP_TOOLCHAIN"] = distribution.RUST_VERSION
    environment.setdefault("CARGO_HOME", str(Path.home() / ".cargo"))
    target = Path(environment.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    if "CARGO_TARGET_DIR" in os.environ:
        target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
        environment["CARGO_TARGET_DIR"] = str(target)
    logs = output / "logs"
    logs.mkdir()
    def run(name: str, *command, maximum=16 * 1024 * 1024):
        result = run_bounded([str(item) for item in command], cwd=ROOT, env=environment,
                             timeout_seconds=600, max_output_bytes=maximum)
        (logs / (name + ".stdout")).write_bytes(result.stdout)
        (logs / (name + ".stderr")).write_bytes(result.stderr)
        return result.stdout
    pins = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
    tools, _ = resolve_tools(pins, ROOT, environment)
    node_features = ["latentd/development-test-node"] if args.node_tests else []
    node_arguments = ["-p", "latentd", "--bin", "latentd", "-p", "latent-wasmtime", "--bin", "latent-aot-compiler",
                      "--features", ",".join(node_features)] if args.node_tests else []
    # Reuse the language owner's reviewed compiler-hot-path profile. A plain
    # unoptimized Cranelift build cannot prepare SpiderMonkey within the actual
    # activation deadline; the debug assertions and guest budgets remain intact.
    node_profile = ROOT / ".cargo/managed-guest.toml"
    configuration = ["--config", node_profile] if args.node_tests else []
    run("host-tools", tools["cargo"], *configuration, "build", "--locked", "-p", "latent-packaging", "--example", "capsule_contracts",
        "-p", "latent-policy", "--example", "capsule_authoring",
        "-p", "latent", "--bin", "latent", *node_arguments)
    run("strip-operator", "strip", "-o", output / "latent-test", target / "debug/latent")
    if args.node_tests:
        from tools.build_dev_frontend import helper
        node = output / "source-node"
        node.mkdir(mode=0o700)
        (node / "bin").mkdir(mode=0o700)
        for name in ("latent", "latentd", "latent-aot-compiler"):
            run("strip-node-" + name, "strip", "-o", node / "bin" / name, target / "debug" / name)
            (node / "bin" / name).chmod(0o700)
        binaries = {name: file_digest(node / "bin" / name)[0] for name in ("latent", "latentd", "latent-aot-compiler")}
        record = {"purpose": "source-application-node-tests", "publisherAuthenticated": False,
            "sourceCommit": commit, "sourceDirty": dirty,
            "buildProfile": {"name": "dev", "overrides": ".cargo/managed-guest.toml", "sha256": file_digest(node_profile)[0],
                             "features": node_features},
            "version": tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"],
            "binaries": binaries, "helperSha256": helper(node / "helper.pyz"),
            "engine": {"hostAbiProfile": HOST_ABI, "wasmtimeVersion": pins["rust"]["dependencies"]["wasmtime"],
                       "compilerSha256": binaries["latent-aot-compiler"][7:]}}
        (node / "source-node.json").write_bytes(encode(record))
    if args.language == "rust":
        fetch = rust_capsule_project.create(output / "dependency-inputs", "greeting")
        run("guest-dependencies", tools["cargo"], "fetch", "--locked", "--manifest-path", fetch / "Cargo.toml")
    payload = output / "payload"
    payload.mkdir(mode=0o700)
    executables = distribution.python(payload, args.python_prefix.resolve(strict=True))
    if args.language == "rust":
        executables.update(distribution.rust(payload, tools["rustc"].parents[3]))
    upstream = {name: source for name, source in SOURCES.items() if name != "zig" or args.language in {"rust", "c"}}
    for name, source in upstream.items():
        archive = output / (name + ".archive")
        download(archive, source)
        if name == "zig":
            distribution.copy(archive, payload / "sdk/zig.tar.xz")
            with tarfile.open(archive, "r:xz") as source:
                member = source.getmember("zig-x86_64-linux-" + ZIG_VERSION + "/LICENSE")
                require(member.isfile() and member.size <= 65536, "zig-license-required")
                license_path = payload / "licenses/zig/LICENSE"
                license_path.parent.mkdir(parents=True)
                license_path.write_bytes(source.extractfile(member).read(65537))
        else:
            executables.update(distribution.binary_archive(archive, payload, name, source["sha256"][7:]))
    run("strip-contracts", "strip", "-o", payload / "sdk/bin/capsule-contracts", target / "debug/examples/capsule_contracts")
    executables.add("sdk/bin/capsule-contracts")
    run("strip-test-signer", "strip", "-o", payload / "sdk/bin/capsule-test-signer", target / "debug/examples/capsule_authoring")
    executables.add("sdk/bin/capsule-test-signer")
    # Managed dependency capture invokes these exact staged tools before final
    # bundle assembly. Archive extraction deliberately does not preserve modes.
    for name in executables:
        (payload / name).chmod(0o700)
    if args.language == "rust":
        distribution.registry(payload, Path(environment["CARGO_HOME"]))
    compiler_sbom = None
    if args.language in {"java", "dotnet"}:
        managed.prepare(payload, output, args.language, download)
        upstream.update(managed.sources(args.language))
    elif args.language == "go":
        compiler_sbom = dev_go_distribution.prepare(payload, output, download, epoch)
        upstream.update(dev_go_distribution.SOURCES)
    elif args.language == "typescript":
        dev_typescript_distribution.prepare(payload, output, download)
        upstream.update(dev_typescript_distribution.SOURCES)
    distribution.recipe(payload, args.language)
    for name in executables:
        (payload / name).chmod(0o700)
    run("python-version", payload / "sdk/bin/python", "-I", "-B", "-c", "import sys; assert sys.version_info[:3] == (3, 13, 5)")
    inventory = distribution.compiler_inventory(payload, commit, args.language)
    distribution.templates(payload, commit, args.language)
    metadata = json.loads(run("metadata", tools["cargo"], "metadata", "--locked", "--format-version", "1",
                              "--filter-platform", "x86_64-unknown-linux-gnu"))
    sbom, licenses = native_runtime_build.dependency_inventory(metadata,
        tomllib.loads((ROOT / "Cargo.lock").read_text()), commit, epoch,
        json.loads((ROOT / "packaging/linux/license-sources.json").read_bytes()), root_names=frozenset({"latent-packaging", "latent-policy"}))
    # Every retained .crate is redistributed, including inactive target entries
    # in the locked offline cache. Account for that complete source inventory.
    if args.language == "rust":
        guest_metadata = json.loads(run("guest-metadata", tools["cargo"], "metadata", "--locked", "--format-version", "1",
                                        "--manifest-path", fetch / "Cargo.toml"))
        guest_sbom, guest_licenses = native_runtime_build.dependency_inventory(guest_metadata,
            tomllib.loads((fetch / "Cargo.lock").read_text()), commit, epoch,
            json.loads((ROOT / "packaging/linux/license-sources.json").read_bytes()),
            root_names=frozenset(package["name"] for package in guest_metadata["packages"]))
        for name, source in guest_licenses.items():
            require(name not in licenses or file_digest(source) == file_digest(licenses[name]), "conflicting-distribution-license")
            licenses[name] = source
        known = {item["SPDXID"]: item for item in sbom["packages"]}
        for package in guest_sbom["packages"]:
            require(package["SPDXID"] not in known or known[package["SPDXID"]] == package, "conflicting-distribution-package")
            known[package["SPDXID"]] = package
        sbom["packages"] = list(known.values())
        relations = {encode(item): item for item in [*sbom["relationships"], *guest_sbom["relationships"]]}
        sbom["relationships"] = list(relations.values())
    for name, source in licenses.items():
        distribution.copy(source, payload / name)
    distribution.copy(ROOT / "LICENSE", payload / "licenses/LSF.txt")
    extra = [{"SPDXID": "SPDXRef-tool-" + name, "name": name, "versionInfo": source["version"],
        "downloadLocation": source["url"], "filesAnalyzed": False, "licenseDeclared": "NOASSERTION",
        "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION",
        "checksums": [{"algorithm": "SHA256", "checksumValue": source["sha256"][7:]}],
        "comment": "Upstream binary distribution; supplied license texts are retained. Zig includes its full archive and notices."}
        for name, source in upstream.items()]
    if args.language in {"java", "dotnet"}:
        extra.extend(managed.dependency_packages(args.language))
    elif args.language == "typescript":
        extra.extend(dev_typescript_distribution.dependency_packages())
    if compiler_sbom is not None:
        # Reuse the reviewed inventory owner for the generator's declared Rust
        # closure. Keep its exact upstream source identities and dependency edges.
        known = {item["SPDXID"]: item for item in sbom["packages"]}
        for package in compiler_sbom["packages"]:
            require(package["SPDXID"] not in known or known[package["SPDXID"]] == package,
                    "conflicting-generator-dependency")
            if package["SPDXID"] not in known:
                extra.append(package)
        sbom["relationships"].extend(compiler_sbom["relationships"])
    for name, version, location, comment in (
        ("rust", distribution.RUST_VERSION, "https://static.rust-lang.org/dist/channel-rust-" + distribution.RUST_VERSION + ".toml",
         "Official installed compiler and stdlib; copyright manifests and license texts in licenses/rust."),
        ("cpython", "3.13.5", "https://www.python.org/ftp/python/3.13.5/Python-3.13.5.tar.xz", "Binary prefix from " + PYTHON_IMAGE)):
        if name == "rust" and args.language != "rust":
            continue
        extra.append({"SPDXID": "SPDXRef-tool-" + name, "name": name, "versionInfo": version, "downloadLocation": location,
            "filesAnalyzed": False, "licenseDeclared": "NOASSERTION", "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION", "comment": comment})
    sbom.update(name="LSF " + args.language + " developer tools", documentNamespace=
                "https://github.com/KirilsTurkins/latent-service-fabric/dev-" + args.language + "-sbom/" + commit)
    sbom["documentComment"] = ("Native contract tool dependencies and upstream compiler distributions. "
        "Rust bundles include the complete redistributed locked Cargo source cache. System libraries remain OS prerequisites.")
    sbom["packages"].extend(extra)
    sbom["relationships"].extend({"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                                  "relatedSpdxElement": item["SPDXID"]} for item in extra)
    (payload / "sbom.spdx.json").write_bytes(encode(sbom))
    (payload / "build-provenance.json").write_bytes(encode({"schemaVersion": "latent.dev.build-provenance.v1",
        "sourceCommit": commit, "sourceDirty": dirty, "target": "linux-x86_64", "hostAbi": HOST_ABI, "protocol": PROTOCOL,
        "toolInventory": inventory["identity"], "pythonImage": PYTHON_IMAGE, "upstreamArchives": upstream,
        "language": args.language, "ownerIssue": LANGUAGES[args.language], "qualification": "assembly-only", "publicRelease": False}))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    value = assemble(payload, output / "candidate", commit=commit, version=version, target="linux-x86_64", epoch=epoch,
                     executables=executables, archive_name="latent-dev-linux-x86_64-" + args.language + "-tools.zip")
    print(encode({"archive": value["archive"], "sourceCommit": commit, "publisherAuthenticated": False}).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

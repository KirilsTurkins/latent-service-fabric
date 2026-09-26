#!/usr/bin/env python3
"""Assemble native developer outputs on Linux using the existing SPDX owner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import native_runtime_build
from tools.dev_distribution import assemble, file_digest, frontend_files
from tools.dev_workflow.common import HOST_ABI, PROTOCOL, encode, require

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--portable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=["windows-x86_64", "linux-x86_64"], default="windows-x86_64")
    args = parser.parse_args()
    require(sys.platform == "linux", "candidate-assembly-linux-required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip(), "clean-source-required-for-candidate")
    epoch = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT))
    record = json.loads((args.frontend / "build.json").read_bytes())
    require(record["sourceCommit"] == commit and not record["sourceDirty"] and record["hostAbi"] == HOST_ABI
            and record["protocol"] == PROTOCOL and record["target"] == args.target, "frontend-exact-source-required")
    require(frontend_files(args.frontend) == record["files"], "frontend-distribution-bytes-changed")
    suffix = ".exe" if args.target == "windows-x86_64" else ""
    frontend_name, portable_name = "latent-dev" + suffix, "latent-portable-test-host" + suffix
    require(file_digest(args.frontend / "dist/latent-dev" / frontend_name)[0] == record["frontendSha256"]
            and file_digest(args.frontend / "helper.pyz")[0] == record["helperSha256"], "frontend-output-identity")
    portable_record = json.loads(args.portable.with_suffix(".json").read_bytes())
    require(portable_record == {"sourceCommit": commit, "sha256": file_digest(args.portable)[0],
                               "target": args.target, "profile": "release"}, "portable-exact-source-required")
    output = args.output.absolute()
    require(output.is_relative_to(ROOT / "target") and not output.exists(), "new-owned-build-directory-required")
    payload = output / "payload"
    payload.mkdir(parents=True)
    shutil.copytree(args.frontend / "dist/latent-dev", payload / "bin")
    shutil.copytree(args.frontend / "licenses", payload / "licenses")
    shutil.copyfile(args.portable, payload / "bin" / portable_name)
    shutil.copyfile(args.frontend / "helper.pyz", payload / "helper.pyz")
    shutil.copyfile(args.frontend / "python-inventory.json", payload / "python-inventory.json")
    metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--locked", "--format-version", "1",
                         "--filter-platform", "x86_64-pc-windows-msvc" if suffix else "x86_64-unknown-linux-gnu"],
                         cwd=ROOT, timeout=300))
    sbom, licenses = native_runtime_build.dependency_inventory(metadata,
        tomllib.loads((ROOT / "Cargo.lock").read_text()), commit, epoch,
        json.loads((ROOT / "packaging/linux/license-sources.json").read_bytes()),
        root_names=frozenset({"latent-portable-test-host"}))
    for name, source in licenses.items():
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
    python = json.loads((payload / "python-inventory.json").read_bytes())
    python_packages = [{"SPDXID": "SPDXRef-cpython", "name": "CPython", "versionInfo": python["python"],
        "filesAnalyzed": False, "downloadLocation": "https://www.python.org/ftp/python/3.13.5/" +
            ("python-3.13.5-amd64.exe" if suffix else "Python-3.13.5.tar.xz"),
        "licenseDeclared": "Python-2.0", "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION",
        "comment": "Redistributed Python and native dependency licenses: " + python["pythonLicense"]}]
    for index, package in enumerate(python["packages"]):
        python_packages.append({"SPDXID": f"SPDXRef-python-build-{index}", "name": package["name"],
            "versionInfo": package["version"], "downloadLocation": "https://pypi.org/project/" + package["name"] + "/" + package["version"],
            "filesAnalyzed": False, "licenseDeclared": package["licenseDeclared"], "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION", "checksums": [{"algorithm": "SHA256", "checksumValue": package["wheelSha256"]}],
            "comment": "Bootloader build input; redistributed license texts: " + ", ".join(package["licenses"])})
    for index, package in enumerate(python.get("nativePackages", [])):
        python_packages.append({"SPDXID": f"SPDXRef-python-native-{index}", "name": package["name"],
            "versionInfo": package["version"], "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
            "licenseDeclared": "NOASSERTION", "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION",
            "comment": "Observed Linux library package; redistributed terms: " + package["licenseFile"]})
    sbom["name"] = "LSF " + args.target + " developer frontend and portable test host"
    sbom["documentNamespace"] = "https://github.com/KirilsTurkins/latent-service-fabric/dev-" + args.target + "-sbom/" + commit
    sbom["packages"].extend(python_packages)
    sbom["relationships"].extend({"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                                  "relatedSpdxElement": item["SPDXID"]} for item in python_packages)
    (payload / "sbom.spdx.json").write_bytes(encode(sbom))
    (payload / "build-provenance.json").write_bytes(encode({"schemaVersion": "latent.dev.build-provenance.v1",
        "sourceCommit": commit, "target": args.target, "hostAbi": HOST_ABI, "protocol": PROTOCOL,
        "frontend": record, "portable": portable_record, "cargoLockSha256": file_digest(ROOT / "Cargo.lock")[0],
        "qualification": "build-and-native-subset-only", "publicRelease": False}))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    value = assemble(payload, output / "candidate", commit=commit, version=version, target=args.target, epoch=epoch,
                     executables={"bin/" + frontend_name, "bin/" + portable_name})
    print(encode({"target": value["target"], "sourceCommit": commit, "archive": value["archive"],
                  "publisherAuthenticated": False}).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

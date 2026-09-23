#!/usr/bin/env python3
"""Build a pinned Ubuntu WSL image candidate; never import or publish it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_dev_frontend import helper
from tools.dev_distribution import assemble, file_digest
from tools.dev_workflow.common import encode, require

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {"ubuntu": "ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3",
          "python": "python@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419"}


def run(*argv, **kwargs):
    return subprocess.run(list(argv), check=True, timeout=600, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true", help="local assembly testing only; never attested")
    args = parser.parse_args()
    output = args.output.absolute()
    require(output.is_relative_to(ROOT / "target") and not output.exists(), "new-owned-build-directory-required")
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip())
    require(args.allow_dirty or not dirty, "clean-source-required-for-candidate")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    epoch = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    output.mkdir(parents=True)
    context = output / "context"
    context.mkdir()
    identity = {"sourceCommit": commit, "sourceDirty": dirty, "baseImages": IMAGES,
                "recipeSha256": file_digest(ROOT / "packaging/dev/wsl.Dockerfile")[0]}
    (context / "source.json").write_bytes(encode(identity))
    helper(context / "helper.pyz")
    for source, destination in (("packaging/dev/wsl.Dockerfile", "Dockerfile"), ("packaging/dev/wsl.conf", "wsl.conf"),
                                ("tools/dev_rootfs_inventory.py", "rootfs_inventory.py"), ("LICENSE", "LSF-LICENSE")):
        shutil.copyfile(ROOT / source, context / destination)
    name = "lsf-dev-rootfs-" + secrets.token_hex(8)
    run("docker", "build", "--platform", "linux/amd64", "--tag", name, str(context))
    payload = output / "payload"
    payload.mkdir()
    created = False
    try:
        smoke = run("docker", "run", "--rm", "--name", name + "-accounts", "--user", "0", "--network", "none",
            "--mount", "type=bind,source=" + str(ROOT / "tools/dev_guest_smoke.py") + ",target=/guest-smoke.py,readonly",
            name, "/usr/local/bin/python3.13", "-I", "/guest-smoke.py", "--image-build-test", capture_output=True)
        (output / "guest-account-test.json").write_bytes(smoke.stdout)
        run("docker", "create", "--name", name, name)
        created = True
        run("docker", "export", "--output", str(payload / "rootfs.tar"), name)
        run("docker", "cp", name + ":/opt/latent-dev/distribution/.", str(payload))
    finally:
        # Exact unpredictable name created above, never another container or image.
        if created:
            run("docker", "rm", name)
        run("docker", "image", "rm", name)
    record = json.loads((payload / "rootfs-inventory.json").read_bytes())
    packages = []
    for index, package in enumerate(record["packages"]):
        packages.append({"SPDXID": f"SPDXRef-ubuntu-{index}", "name": package["name"], "versionInfo": package["version"],
            "downloadLocation": "https://archive.ubuntu.com/ubuntu", "filesAnalyzed": False,
            "licenseDeclared": "NOASSERTION", "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION",
            "comment": "Redistributed package copyright and license terms: " + package["licenseFile"]})
    packages.append({"SPDXID": "SPDXRef-cpython", "name": "CPython", "versionInfo": "3.13.5", "filesAnalyzed": False,
        "downloadLocation": "https://www.python.org/ftp/python/3.13.5/Python-3.13.5.tar.xz", "licenseDeclared": "Python-2.0",
        "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION", "comment": "Binary from " + IMAGES["python"]})
    sbom = {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": "LSF developer WSL Ubuntu image", "documentNamespace": "https://github.com/KirilsTurkins/latent-service-fabric/dev-wsl-sbom/" + commit,
        "creationInfo": {"creators": ["Tool: latent-dev-rootfs-builder-v1"],
                         "created": datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "packages": packages, "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                                                   "relatedSpdxElement": package["SPDXID"]} for package in packages]}
    (payload / "sbom.spdx.json").write_bytes(encode(sbom))
    value = assemble(payload, output / "candidate", commit=commit, version=version,
                     target="linux-x86_64-wsl-rootfs", epoch=epoch, executables=set())
    print(encode({"target": value["target"], "source": identity, "archive": value["archive"],
                  "helperSha256": record["helperSha256"], "publisherAuthenticated": False}).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

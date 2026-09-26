"""Capture the maintained Node/TypeScript compiler with its exact npm lock."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil

from tools.dev_managed_distribution import extract, pack
from tools.dev_workflow.common import require

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"node": {"url": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.gz",
    "version": "24.19.0", "maximum": 57409532,
    "sha256": "sha256:f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4"}}


def prepare(payload: Path, output: Path, download) -> None:
    from tools.typescript_capsule import install
    archive = output / "node.archive"
    download(archive, SOURCES["node"])
    node = extract(archive, output / "node-source", "node", source=SOURCES["node"])
    original = dict(os.environ)
    try:
        os.environ["PATH"] = str(node / "bin") + os.pathsep + original["PATH"]
        installed = install(output / "typescript-dependencies")
        # npm launch aliases are unused: the owner selects exact JS entrypoints.
        # Materializing .bin would duplicate scripts with a different module root.
        retained = output / "typescript-tools"
        shutil.copytree(installed, retained, ignore=shutil.ignore_patterns(".bin", "logs"))
        pack({"node": node, "tools": retained}, payload / "sdk")
        notices = payload / "licenses/typescript"
        notices.mkdir(parents=True)
        shutil.copyfile(node / "LICENSE", notices / "Node-LICENSE.txt")
        shutil.copyfile(installed / "package-lock.json", notices / "package-lock.json")
        (notices / "README.txt").write_text(
            "Exact dependency license and notice files remain in sdk/managed.zip.\n"
            "sdk/managed-inputs.json records every file; compilation uses no npm install or network resolver.\n",
            encoding="utf-8")
    finally:
        os.environ.clear()
        os.environ.update(original)


def dependency_packages() -> list[dict]:
    lock = json.loads((ROOT / "sdk/typescript-guest/tools/package-lock.json").read_bytes())
    result = []
    for name, item in sorted(lock["packages"].items()):
        if not name:
            continue
        algorithm, separator, encoded = item.get("integrity", "").partition("-")
        require(separator and algorithm in {"sha512", "sha256"}, "locked-npm-integrity-required")
        result.append({"SPDXID": "SPDXRef-npm-" + hashlib.sha256(name.encode()).hexdigest(),
            "name": name.rsplit("node_modules/", 1)[-1], "versionInfo": item["version"],
            "downloadLocation": item["resolved"], "filesAnalyzed": False,
            "licenseDeclared": item.get("license", "NOASSERTION"), "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION", "checksums": [{"algorithm": algorithm.upper(),
                "checksumValue": base64.b64decode(encoded, validate=True).hex()}],
            "comment": "Declared pinned npm dependency; sdk/managed-inputs.json identifies the platform files actually redistributed."})
    return result

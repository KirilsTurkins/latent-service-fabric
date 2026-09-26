#!/usr/bin/env python3
"""Build distinct maintained green/blue Angular sources, never wrapper-only variants."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.angular_build.inputs import read
from tools.build_angular_package import observed_build
from tools.build_snapshot import SnapshotError, canonical, digest
from tools.phase2_operator_process import read_json, require, write_json

ROOT = Path(__file__).resolve().parents[1]


def stage_variant(source, destination, variant):
    require(variant in ("green", "blue"), "reference-variant")
    config = read_json(source / "angular-build.json")
    require(config["name"] == "angular-reference" and config["backendProfile"] == "scoped-http-get-v1"
            and "shared/version.ts" in config["sources"], "reference-build-profile")
    files = ["angular-build.json", *config["sources"], *(asset["source"] for asset in config["assets"])]
    require(len(files) <= 16 and len(files) == len(set(files)), "reference-source-count")
    destination.mkdir(mode=0o700)
    for name in files:
        selected = "variants/blue.ts" if variant == "blue" and name == "shared/version.ts" else name
        content = read(source, selected, 256 * 1024)
        target = destination / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(content)
    version = read(destination, "shared/version.ts", 128)
    require(version.strip() == f"export const REFERENCE_VERSION = 'reference-{variant}';".encode(),
            "reference-version-source")
    return digest(version)


def run(args):
    output = args.output.resolve()
    require(not output.exists(), "reference-output-exists")
    output.mkdir(mode=0o700, parents=True)
    records = []
    for variant in ("green", "blue"):
        print("Angular reference build: " + variant, file=sys.stderr, flush=True)
        with tempfile.TemporaryDirectory(prefix="lsf-reference-source-") as temporary:
            source = Path(temporary) / "application"
            version_digest = stage_variant(ROOT / "examples/angular-reference-application", source, variant)
            summary = observed_build(input_root=source, config="angular-build.json", toolchain=args.toolchain_root,
                                     cli=args.cli, target_root=output, output=output / variant,
                                     cargo_target=args.cargo_target_dir, repository=args.repository)
        observation = read_json(output / variant / "observation.json")
        manifest = read_json(output / variant / "inputs/metadata/web-application.json")
        records.append({"variant": variant, "versionSourceDigest": version_digest,
                        "packageDigest": summary["packageDigest"], "componentDigest": manifest["renderer"]["digest"],
                        "assetsDigest": manifest["assetsDigest"],
                        "buildObservationDigest": digest((output / variant / "observation.json").read_bytes()),
                        "sourceSnapshotDigest": observation["source"]["snapshotDigest"]})
    for field in ("versionSourceDigest", "packageDigest", "componentDigest", "assetsDigest", "sourceSnapshotDigest"):
        require(records[0][field] != records[1][field], "reference-builds-not-distinct-" + field)
    result = {"schemaVersion": "latent.angular.reference.builds.v1", "actualAngularBuilds": records,
              "reproducibility": "not-checked", "dependencyCompleteness": "declared-inputs-incomplete"}
    write_json(output / "reference-builds.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("toolchain-root", "cli", "cargo-target-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--repository", default="https://github.com/KirilsTurkins/latent-service-fabric")
    args = parser.parse_args()
    require(sys.platform == "linux", "reference-build-linux-required")
    print(canonical(run(args)).decode())


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as failure:
        print("Angular reference build failed: " + str(failure), file=sys.stderr)
        raise SystemExit(1)

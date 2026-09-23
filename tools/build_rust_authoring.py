#!/usr/bin/env python3
"""Build source-captured standalone Rust projects for the runtime authoring gate."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import rust_capsule as authoring


def run(output: Path, packager: Path, legacy: Path) -> None:
    output = output.parent.resolve(strict=True) / output.name
    if output.exists() or output.is_symlink() or authoring.ROOT in output.parents:
        raise ValueError("authoring qualification requires a fresh directory outside the checkout")
    output.mkdir(mode=0o700)
    projects, builds = output / "projects", output / "builds"
    projects.mkdir(); builds.mkdir()
    records, stage = [], "start"
    try:
        for template in (*authoring.TUTORIALS, "diagnostics", *("guest-" + name for name in authoring.GUESTS)):
            stage = template
            name = "rust-" + template[6:] if template.startswith("guest-") else template
            directory = projects / name
            authoring.new_project(directory, template, name)
            if template.startswith("guest-"):
                # Only qualification reuses the old fixture's explicit ceilings and service identity.
                previous = authoring.document(legacy / name / "capsule.json")
                value = authoring.document(directory / "capsule-project.json")
                value["limits"] = previous["execution"]["limits"]
                value["service"] = previous["metadata"]["name"]
                (directory / "capsule-project.json").write_bytes(authoring.canonical(value))
            if template == "diagnostics":
                value = authoring.document(directory / "capsule-project.json")
                value["limits"]["cpuFuel"] = 10000000000
                (directory / "capsule-project.json").write_bytes(authoring.canonical(value))
            started = time.monotonic()
            authoring.lock_project(directory)
            authoring.build(directory, builds / name, packager, "https://github.com/KirilsTurkins/latent-service-fabric")
            records.append({"name": name, "template": template,
                            "observationDigest": authoring.digest(authoring.read(builds / name / "build-observation.json")),
                            "elapsedMillis": round((time.monotonic()-started)*1000)})
            print("Built standalone Rust capsule: " + name, flush=True)
        # Existing cross-language regression includes C. Preserve its actual old observation;
        # it is not claimed as a Rust-authoring build or silently signed with the new recipe.
        shutil.copytree(legacy / "c-blob", builds / "c-blob")
        for name in ("BUILD-COMPLETE.json", "source-inputs.json"):
            shutil.copyfile(legacy / name, builds / name)
        authoring.write(output / "BUILD-MATRIX.json", {"formatVersion": 1, "builds": records,
                        "legacyRegression": ["c-blob"], "executed": False})
    except BaseException as error:
        authoring.write(output / "MATRIX-FAILED.json", {"formatVersion": 1, "stage": stage,
                        "errorType": type(error).__name__, "completedBuilds": records})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--packager", type=Path, required=True)
    parser.add_argument("--legacy-guests", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.packager.resolve(strict=True), args.legacy_guests.resolve(strict=True))


if __name__ == "__main__":
    main()

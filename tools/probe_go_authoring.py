#!/usr/bin/env python3
"""Real Go project/build/package/admission experiment; full SDK gate is separate."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.go_capsule_project import ROOT, TEMPLATES, create
from tools.go_capsule_build import build
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import fresh, write_json
from tools.run_rust_capsule_workflow import run


def probe(output: Path):
    output = output.absolute()
    if ROOT == output or ROOT in output.parents:
        raise ValueError("Go authoring projects must be outside the source checkout")
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output))
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    commands.environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0")
    report = {"language": "go", "status": "failed", "fullSdkQualification": False}
    try:
        commands.run("host-build", "cargo", "build", "--locked", "-p", "latent", "-p", "latentd", "--bins",
                     "-p", "latent-packaging", "--example", "package", "--example", "capsule_contracts",
                     "-p", "latent-policy", "--example", "capsule_authoring")
        binary = target / "debug"
        (output / "projects").mkdir()
        (output / "builds").mkdir()
        built = []
        for template in TEMPLATES:
            project = create(output / "projects" / template, template)
            built.append(build(project, output / "builds" / template,
                binary / "examples/capsule_contracts", binary / "examples/package",
                "https://github.com/KirilsTurkins/latent-service-fabric"))
        commands.run("sign-demo", binary / "examples/capsule_authoring", "demo-sign", output / "releases", *built)
        run(binary / "latent", binary / "latentd", output / "releases", output / "node", language="go")
        report["status"] = "passed"
    finally:
        report["commands"] = commands.records
        write_json(output / "project-experiment.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    probe(parser.parse_args().output)

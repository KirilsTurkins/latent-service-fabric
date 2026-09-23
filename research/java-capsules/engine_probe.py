#!/usr/bin/env python3
"""Compile a temporary research observer against the unchanged, locked LSF backend."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.build_observation import build_environment, resolve_tools
from probe import Attempt, digest, write_json

WRAPPER = '#[path = "../../../research/java-capsules/engine_probe.rs"]\nmod driver;\nfn main() -> std::process::ExitCode { driver::main() }\n'


@contextmanager
def observer(root: Path):
    """Never overwrite a target or change production manifests/dependency features."""
    directory = root / "crates/latent-wasmtime/examples"
    for ancestor in (root, root / "crates", root / "crates/latent-wasmtime", directory):
        if ancestor.is_symlink():
            raise ValueError("research-observer-symlink")
    existed = directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "java_feasibility_generated.rs"
    with path.open("x", encoding="utf-8") as output:
        output.write(WRAPPER)
    try:
        yield path
    finally:
        if path.is_symlink() or path.read_text() != WRAPPER:
            raise ValueError("research-observer-changed-while-owned")
        path.unlink()
        if not existed:
            directory.rmdir()


def source_inputs(root: Path = ROOT) -> dict:
    paths = [root / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml")]
    for directory in ("apps", "crates", "sdk/rust", "sdk/rust-guest", "wit", "api", "schemas", "research/java-capsules"):
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file()
                     and not set(path.relative_to(root / directory).parts) & {"target", "__pycache__", ".gradle", "build"})
    if len(paths) > 10000 or sum(path.stat().st_size for path in paths) > 64 * 1024 * 1024:
        raise ValueError("backend-source-inventory-bound")
    if any(path.is_symlink() for path in paths):
        raise ValueError("backend-source-symlink")
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or (output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "target")):
        parser.error("output must be outside source directories")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"formatVersion": 1, "qualification": "not-qualified", "status": "not-started",
               "scope": "production-backend-feasibility-not-signed-node-conformance", "phases": []}
    try:
        if args.component.is_symlink() or not args.component.is_file() or not 0 < args.component.stat().st_size <= 16 * 1024 * 1024:
            raise ValueError("component-input-missing-unsafe-or-oversized")
        inputs = source_inputs()
        write_json(output / "source-inputs.json", inputs)
        receipt["sourceSnapshotSha256"] = digest(output / "source-inputs.json")
        receipt["sourceCapture"] = "listed-worktree-inputs-not-complete-transitive-build-provenance"
        temporary = output / "tmp"
        temporary.mkdir()
        environment = build_environment(temporary)
        config = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        paths, identities = resolve_tools(config, ROOT, environment)
        receipt["tools"] = identities
        environment.update({"RUSTC": str(paths["rustc"]), "CARGO_INCREMENTAL": "0"})
        attempt = Attempt(output, environment)
        receipt["phases"] = attempt.phases
        with observer(ROOT) as wrapper:
            receipt["generatedObserverSha256"] = digest(wrapper)
            built = attempt.run("build-current-lsf-backend", [str(paths["cargo"]), "build", "--locked",
                "-p", "latent-wasmtime", "--example", "java_feasibility_generated"], timeout_seconds=600)
            if built["status"] == "passed":
                binary = ROOT / "target/debug/examples/java_feasibility_generated"
                receipt["binarySha256"] = digest(binary)
                observed = attempt.run("current-lsf-backend", [str(binary), str(args.component.resolve()),
                    str(output / "engine.json")], timeout_seconds=90)
                receipt["observerExitStatus"] = observed["status"]
                if (output / "engine.json").is_file():
                    receipt["engineObservation"] = json.loads((output / "engine.json").read_text())
                    receipt["status"] = "observed-not-qualified"
                else:
                    receipt["status"] = "observer-failed-without-receipt"
            else:
                receipt["status"] = "build-or-environment-failure-not-language-rejection"
        if source_inputs() != inputs:
            raise ValueError("backend-sources-changed-during-probe")
    except (OSError, ValueError, RuntimeError) as error:
        receipt.update(status="probe-environment-or-recipe-error", reason=str(error))
    finally:
        write_json(output / "receipt.json", receipt)
        print(json.dumps(receipt, indent=2), flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

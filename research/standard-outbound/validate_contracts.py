#!/usr/bin/env python3
"""Validate uninstalled research WIT with the repository-pinned compiler."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

COMMAND_TIMEOUT_SECONDS = 30


def stage_companion(repository: Path, destination: Path) -> None:
    """Use the actual v1 platform package, never a hand-maintained type copy."""
    companion = repository / "research/standard-outbound/nonblocking-v2/package.wit"
    dependency = repository / "wit/platform/network"
    sources = sorted(dependency.glob("*.wit"))
    if not sources:
        raise FileNotFoundError(f"No v1 WIT package found in {dependency}")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(companion, destination / "package.wit")
    target = destination / "deps/network"
    target.mkdir(parents=True)
    for source in sources:
        shutil.copyfile(source, target / source.name)


def source_identity(repository: Path) -> dict[str, str]:
    """Bind the observation to the actual comparison and dependency sources."""
    research = repository / "research/standard-outbound"
    sources = [research / "nonblocking-v2/package.wit"]
    for directory in (research, repository / "wit/platform/network"):
        package = sorted(directory.glob("*.wit"))
        if not package:
            raise FileNotFoundError(f"No WIT package found in {directory}")
        sources.extend(package)
    return {
        str(path.relative_to(repository).as_posix()): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sources
    }


def validate(repository: Path, output: Path, wasm_tools: str) -> dict:
    """Publish a type-only observation only after both fresh artifacts validate."""
    repository = repository.resolve()
    if output.is_symlink():
        raise FileExistsError("The output directory must not be a symbolic link")
    output = output.resolve()
    research = repository / "research/standard-outbound"
    for source in (research, repository / "wit"):
        if output == source or source in output.parents:
            raise ValueError("The output directory must be outside the WIT source trees")
    # Never follow stale output-file symlinks, truncate hard links, overwrite
    # evidence from an earlier run, or mistake old artifacts for fresh results.
    if output.exists():
        raise FileExistsError("Choose a fresh output directory; existing output is never reused")
    pin = (repository / "tools/toolchain.toml").read_bytes()
    expected = tomllib.loads(pin.decode("utf-8"))["contracts"]["wasm-tools"]
    version = subprocess.run(
        [wasm_tools, "--version"], check=True, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT_SECONDS, cwd=repository,
    ).stdout.strip()
    if version.split()[:2] != ["wasm-tools", expected]:
        raise ValueError(f"Expected wasm-tools {expected}, observed {version!r}")
    sources = source_identity(repository)
    output.mkdir(parents=True, exist_ok=False)

    def run(*arguments: str | Path) -> None:
        subprocess.run(
            [wasm_tools, *(str(arg) for arg in arguments)], check=True,
            stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT_SECONDS, cwd=repository,
        )

    with tempfile.TemporaryDirectory(prefix=".validation-", dir=output) as temporary:
        work = Path(temporary)
        staged = work / "nonblocking-v2"
        stage_companion(repository, staged)
        # Parse the original directory, not just one file: a second package
        # declaration must remain a parser error rather than disappearing.
        artifacts = {}
        for name, source in (("v1", research), ("v2", staged)):
            artifact = work / f"{name}.wasm"
            run("component", "wit", source, "--wasm", "--output", artifact)
            run("validate", "--features", "all", artifact)
            data = artifact.read_bytes()
            if not data:
                raise ValueError(f"The compiler produced an empty {name} artifact")
            artifacts[artifact.name] = {
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            }
        if source_identity(repository) != sources or (repository / "tools/toolchain.toml").read_bytes() != pin:
            raise ValueError("Contract sources or toolchain pin changed during validation")
        observation = {
            "schemaVersion": "latent.research.outbound-wit.v1",
            "evidenceKind": "type-only-contract-validation",
            "runtimeQualification": False,
            "compilerVersion": version,
            "toolchainSha256": hashlib.sha256(pin).hexdigest(),
            "sources": sources,
            "artifacts": artifacts,
        }
        for name in artifacts:
            (work / name).rename(output / name)
        # This completion marker is absent on parser/validator failure or timeout.
        (output / "validation.json").write_text(
            json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
    print(json.dumps(observation, sort_keys=True))
    print(f"Validated type-only v1 and v2 contracts in {output}")
    print("This is not runtime installation, authorization, or socket qualification.")
    return observation


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wasm-tools", default="wasm-tools", help="Pinned wasm-tools executable")
    parser.add_argument(
        "--output", type=Path, default=repository / "target/outbound-contract",
        help="Fresh output directory outside the WIT source trees; never overwritten",
    )
    arguments = parser.parse_args()
    try:
        validate(repository, arguments.output, arguments.wasm_tools)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Contract validation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Parse and validate the research contracts without installing either interface."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


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


def validate(repository: Path, output: Path, wasm_tools: str) -> None:
    """Validate v1 in place and v2 with a freshly staged exact v1 dependency."""
    repository = repository.resolve()
    output = output.resolve()
    research = repository / "research/standard-outbound"
    # Do not put generated WIT or dependencies back into either source package.
    for source in (research, repository / "wit"):
        if output == source or source in output.parents:
            raise ValueError("The output directory must be outside the WIT source trees")
    output.mkdir(parents=True, exist_ok=True)

    def run(*arguments: str | Path) -> None:
        subprocess.run([wasm_tools, *(str(arg) for arg in arguments)], check=True)

    # Parsing the directory (not just streams.wit) catches package collisions.
    v1 = output / "v1.wasm"
    run("component", "wit", research, "--wasm", "--output", v1)
    run("validate", "--features", "all", v1)
    with tempfile.TemporaryDirectory(prefix="lsf-nonblocking-wit-") as temporary:
        staged = Path(temporary) / "nonblocking-v2"
        stage_companion(repository, staged)
        v2 = output / "v2.wasm"
        run("component", "wit", staged, "--wasm", "--output", v2)
        run("validate", "--features", "all", v2)
    print(f"Validated type-only v1 and v2 contracts in {output}")
    print("This is not runtime installation, authorization, or socket qualification.")


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wasm-tools", default="wasm-tools", help="Pinned wasm-tools executable")
    parser.add_argument(
        "--output", type=Path, default=repository / "target/outbound-contract",
        help="Generated type-only components; outside the WIT source trees",
    )
    arguments = parser.parse_args()
    try:
        validate(repository, arguments.output, arguments.wasm_tools)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Contract validation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

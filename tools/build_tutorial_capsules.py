#!/usr/bin/env python3
"""Compile the three learning capsules and write their local publication inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import run_bounded
from tools.build_observation import build_environment

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "greeting": ("greet", [("name", "String")], "String", ["Ada"]),
    "word-count": ("count", [("text", "String")], "U32", ["LSF runs small programs"]),
    "shipping": ("quote", [("items", "U32"), ("express", "Bool")], "U32", [2, False]),
}


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def metadata_digest(value: dict) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def inputs(directory: Path, name: str, component: bytes) -> None:
    function, parameters, result, example_input = EXAMPLES[name]
    contract_id = f"examples:{name}/api@1.0.0"
    interface = {"id": contract_id, "documentation": None, "functions": [{
        "id": function, "name": function, "asynchronous": False,
        "documentation": None, "attributes": {},
        "parameters": [{"name": field, "value_type": kind, "documentation": None}
                       for field, kind in parameters],
        "results": [{"name": "result", "documentation": None,
                     "value_type": {"Result": {"ok": result, "error": "String"}}}],
    }]}
    interface["digest"] = metadata_digest(interface)
    contract = {"id": contract_id, "package_name": f"examples:{name}",
                "semantic_version": "1.0.0", "interfaces": [interface], "dependencies": []}
    contract["digest"] = metadata_digest(contract)
    write(directory / "contracts.json", {"format_version": 1, "contracts": [contract]})
    manifest = json.loads((ROOT / "examples/echo-contract/capsule.json").read_text())
    manifest["metadata"]["name"] = f"examples/{name}"
    manifest["metadata"]["annotations"] = {"latent.dev/purpose": "learning-example"}
    manifest["component"] = {"digest": digest(component), "version": "1.0.0",
                             "world": f"examples:{name}/service@1.0.0"}
    manifest["exports"] = [contract_id]
    manifest["imports"] = []
    manifest["execution"]["limits"]["logBytes"] = 0
    manifest["compatibility"]["minimumFabricVersion"] = tomllib.loads(
        (ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    write(directory / "capsule.json", manifest)
    deployment = json.loads((ROOT / "examples/echo-contract/deployment.json").read_text())
    deployment["metadata"]["name"] = f"tutorial-{name}"
    deployment["spec"].update(service=f"examples/{name}", release=digest(component), grants=[])
    deployment["spec"]["resources"]["logBytes"] = 0
    write(directory / "deployment.json", deployment)
    write(directory / "input.json", example_input)


def build(output: Path) -> None:
    output = output.resolve()
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    if not output.is_relative_to(ROOT / "target") or output == ROOT / "target":
        raise ValueError("Choose a fresh output directory below this checkout's target directory.")
    if output.exists():
        raise ValueError("Output already exists; choose another --output directory.")
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="lsf-tutorial-build-") as temporary:
        environment = build_environment(Path(temporary))
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0")

        def run(*command: str, timeout: int = 600) -> bytes:
            result = run_bounded(command, ROOT, environment, timeout_seconds=timeout,
                                 max_output_bytes=4 * 1024 * 1024)
            return result.stdout

        toolchain = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        if run("rustc", "--version").decode().split()[1] != toolchain["rust"]["toolchain"]:
            raise ValueError("Use the repository's pinned Rust toolchain.")
        if toolchain["contracts"]["wasm-tools"] not in run("wasm-tools", "--version").decode().split():
            raise ValueError("Use the repository's pinned wasm-tools version.")
        command = ["cargo", "build", "--locked", "--release", "-p", "latent-toolchain-smoke",
                   "--target", "wasm32-unknown-unknown"]
        for name in EXAMPLES:
            command.extend(["--example", f"tutorial-{name}"])
        print("Building greeting, word-count and shipping capsules...", flush=True)
        run(*command)
        for name in EXAMPLES:
            directory = output / name
            directory.mkdir()
            component = directory / "component.wasm"
            core = target / "wasm32-unknown-unknown/release/examples" / (
                "tutorial_" + name.replace("-", "_") + ".wasm")
            run("wasm-tools", "component", "new", str(core), "-o", str(component), timeout=30)
            run("wasm-tools", "validate", str(component), timeout=30)
            inputs(directory, name, component.read_bytes())
            print(f"Ready: {name}", flush=True)
    write(output / "BUILD-COMPLETE.json", {"examples": list(EXAMPLES)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "target/tutorial-capsules")
    build(parser.parse_args().output)


if __name__ == "__main__":
    main()

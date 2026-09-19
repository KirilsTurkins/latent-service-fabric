"""Generate private Go RPC bindings with pinned local plugins and Buf."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from dependencies import go_environment, pinned_version


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdk" / "go"
TOOLS = SDK / "target" / "tools"
PLUGINS = {
    "protoc-gen-go": ("google.golang.org/protobuf/cmd/protoc-gen-go", "v1.36.12"),
    "protoc-gen-go-grpc": ("google.golang.org/grpc/cmd/protoc-gen-go-grpc", "v1.6.2"),
}
SOURCES = {
    "latent/control/v1/common.proto": "controlv1",
    "latent/control/v1/policy.proto": "controlv1",
    "latent/control/v1/capability.proto": "controlv1",
    "latent/invocation/v1/invocation.proto": "invocationv1",
}


def run(command: list[str], environment: dict[str, str], timeout: int = 120,
        directory: Path = ROOT) -> str:
    return subprocess.run(command, cwd=directory, env=environment, check=True,
                          capture_output=True, text=True, timeout=timeout).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    environment = go_environment()
    pinned_version()
    if run(["buf", "--version"], environment) != "1.72.0":
        raise ValueError("Go generation requires repository-pinned Buf 1.72.0")
    TOOLS.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    for name, (module, version) in PLUGINS.items():
        executable = TOOLS / (name + suffix)
        run(["go", "build", "-trimpath", "-o", str(executable), module],
            environment, 180, SDK)
        if version.removeprefix("v") != run([str(executable), "--version"], environment).split()[-1].removeprefix("v"):
            raise ValueError(f"unexpected {name} version")
    options = ["module=latent.dev/sdk/go"] + [
        f"M{source}=latent.dev/sdk/go/internal/rpc/{package}"
        for source, package in SOURCES.items()
    ]
    with tempfile.TemporaryDirectory(prefix="go-protobuf-", dir=TOOLS.parent) as temporary:
        output = Path(temporary)
        template = {"version": "v2", "plugins": [
            {"local": str(TOOLS / (name + suffix)), "out": str(output), "opt": options}
            for name in PLUGINS
        ]}
        command = ["buf", "--timeout", "60s", "generate", str(ROOT / "api" / "proto"),
                   "--template", json.dumps(template)]
        for source in SOURCES:
            command.extend(["--path", str(ROOT / "api" / "proto" / source)])
        run(command, environment)
        generated = output / "internal" / "rpc"
        destination = SDK / "internal" / "rpc"
        sources = {path.relative_to(generated): path for path in generated.rglob("*.go")}
        existing = {path.relative_to(destination): path for path in destination.rglob("*.go")}
        if arguments.check:
            if sources.keys() != existing.keys() or any(
                sources[name].read_bytes() != existing[name].read_bytes() for name in sources
            ):
                raise ValueError("private Go RPC bindings differ from pinned regeneration")
        else:
            if destination.is_symlink() or not destination.resolve().is_relative_to(SDK.resolve()):
                raise ValueError("private Go RPC output must stay within this SDK")
            for name, path in sources.items():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError("private Go RPC output path escapes its directory")
                target.write_bytes(path.read_bytes())
            for name in existing.keys() - sources.keys():
                target = existing[name]
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError("stale Go RPC output path escapes its directory")
                target.unlink()
    print("checked Go RPC regeneration" if arguments.check else "generated Go RPC bindings from four authoritative protobuf sources")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        print(f"Go generation failed: {failure}", file=sys.stderr)
        raise SystemExit(1)

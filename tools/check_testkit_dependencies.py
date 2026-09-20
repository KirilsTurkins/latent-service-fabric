#!/usr/bin/env python3
"""Fail if neutral test helpers pull node/runtime/provider dependencies into fast tests."""
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"latentd", "latent-node", "latent-wasmtime", "latent-http", "latent-nats", "latent-state", "latent-vault"}


def main() -> None:
    for package in ("latent-testkit", "latent-admission", "latent-scheduler"):
        args = ["cargo", "tree", "--locked", "-p", package, "--prefix", "none", "--format", "{p}"]
        args += ["--no-default-features", "--edges", "normal,build"] if package == "latent-testkit" else ["--edges", "normal,build,dev"]
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True, timeout=120)
        names = {line.split()[0] for line in result.stdout.splitlines() if line.strip()}
        forbidden = FORBIDDEN | ({"latent-activation", "latent-executor", "latent-telemetry"} if package == "latent-testkit" else set())
        offenders = sorted(name for name in names if name in forbidden or name.startswith("wasmtime"))
        if offenders:
            raise RuntimeError(f"{package} inherited heavy dependencies: {offenders}\n{result.stdout}")
        print(f"{package}: {len(names)} dependency nodes, no forbidden runtime/provider dependencies")
    for package in ("latent-admission", "latent-scheduler"):
        manifest = tomllib.loads((ROOT / "crates" / package / "Cargo.toml").read_text())
        assert manifest["dev-dependencies"]["latent-testkit"]["default-features"] is False


if __name__ == "__main__":
    main()

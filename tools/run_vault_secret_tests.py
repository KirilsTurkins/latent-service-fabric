#!/usr/bin/env python3
"""Real Vault secret conformance with one pinned, disposable TLS dev server."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import uuid

from run_oci_registry_tests import command
from vault_test_support import Client, ROOT_TOKEN

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "hashicorp/vault@sha256:783103ba38c5e3edcaa9bbbcb0ff80fc93c690361f03fd487e89227da6c3efa9"
LABEL = "io.latent.vault-conformance"


def close(name, token, identity):
    found = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=15)
    if found.returncode:
        if not any(s in found.stderr.lower() for s in ("no such object", "no such container")):
            raise RuntimeError("cannot verify owned Vault cleanup")
        return
    info = json.loads(found.stdout)[0]
    if info["Config"].get("Labels", {}).get(LABEL) != token or (identity and info["Id"] != identity):
        raise RuntimeError("refusing to remove a container with different ownership")
    command(["docker", "rm", "--force", info["Id"]])


def test_command(manifest):
    if manifest is None:
        return ["cargo", "test", "--locked", "--all-features", "-p", "latent-wasmtime", "--test", "vault_secrets",
                "real_vault_", "--", "--ignored", "--nocapture", "--test-threads=1"]
    if manifest.stat().st_size > 32 * 1024 * 1024:
        raise RuntimeError("Cargo test manifest exceeds its finite limit")
    executables = set()
    with manifest.open(encoding="utf-8") as source:
        for line in source:
            if len(line) > 131072:
                raise RuntimeError("Cargo manifest line exceeds its finite limit")
            item = json.loads(line)
            if item.get("reason") == "compiler-artifact" and item.get("target", {}).get("name") == "vault_secrets" and item.get("profile", {}).get("test") and item.get("executable"):
                executables.add(item["executable"])
    if len(executables) != 1:
        raise RuntimeError("Cargo manifest must identify one Vault test harness")
    executable = Path(executables.pop()).resolve()
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    if not executable.is_file() or not executable.is_relative_to(target):
        raise RuntimeError("Vault test harness must reside in this Cargo target directory")
    return [str(executable), "real_vault_", "--ignored", "--nocapture", "--test-threads=1"]


def run(args, directory):
    token = uuid.uuid4().hex
    name = "lsf-vault-test-" + token
    remote = "/tmp/" + name
    identity, remote_created = None, False
    try:
        port = 8200
        network = ["--publish", "127.0.0.1::8200"]
        if args.cargo_container:
            port = int(command(["docker", "exec", args.cargo_container, "python3", "-c",
                                "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1])"]))
            network = ["--network", "container:" + args.cargo_container]
        identity = command(["docker", "run", "--detach", "--name", name, "--label", f"{LABEL}={token}",
            *network, "--memory", "512m", "--memory-swap", "512m", "--cpus", "1", "--pids-limit", "128",
            "--read-only", "--cap-drop", "ALL", "--cap-add", "IPC_LOCK", "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=16777216", "--log-driver", "local",
            "--log-opt", "max-size=64k", "--log-opt", "max-file=1", "--log-opt", "compress=false",
            "--entrypoint", "/bin/vault", IMAGE, "server", "-dev", "-dev-no-store-token",
            "-dev-root-token-id=" + ROOT_TOKEN, "-dev-tls", "-dev-tls-cert-dir=/tmp",
            f"-dev-listen-address=0.0.0.0:{port}"])
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = subprocess.run(["docker", "exec", name, "cat", "/tmp/vault-ca.pem"],
                                    capture_output=True, timeout=5)
            if result.returncode == 0 and 0 < len(result.stdout) < 65536:
                pem = result.stdout.decode("ascii")
                (directory / "ca.pem").write_text(pem, encoding="ascii")
                (directory / "ca.der").write_bytes(ssl.PEM_cert_to_DER_cert(pem))
                break
            time.sleep(.2)
        else:
            raise RuntimeError("Vault TLS bootstrap failed")
        if args.cargo_container:
            command(["docker", "exec", args.cargo_container, "mkdir", "-m", "700", remote])
            remote_created = True
            for source, target in [(directory / "ca.pem", "ca.pem"), (directory / "ca.der", "ca.der"),
                                   (ROOT / "tools/vault_test_support.py", "control.py")]:
                command(["docker", "cp", str(source), f"{args.cargo_container}:{remote}/{target}"])
            command(["docker", "exec", args.cargo_container, "python3", remote + "/control.py",
                     str(port), remote + "/ca.pem", "setup"], timeout=40)
            launch = ["docker", "exec", "-w", args.workspace,
                      "-e", f"LSF_VAULT_TEST_PORT={port}", "-e", f"LSF_VAULT_TEST_CA={remote}/ca.der",
                      "-e", f"LSF_VAULT_TEST_PEM={remote}/ca.pem", "-e", f"LSF_VAULT_TEST_CONTROL={remote}/control.py",
                      args.cargo_container]
            env = None
        else:
            info = json.loads(command(["docker", "inspect", identity]))[0]
            mapping = info["NetworkSettings"]["Ports"]["8200/tcp"]
            if len(mapping) != 1 or mapping[0]["HostIp"] != "127.0.0.1":
                raise RuntimeError("Vault fixture requires one loopback mapping")
            port = int(mapping[0]["HostPort"])
            Client(port, directory / "ca.pem").setup()
            launch = []
            env = dict(os.environ, LSF_VAULT_TEST_PORT=str(port), LSF_VAULT_TEST_CA=str(directory / "ca.der"),
                       LSF_VAULT_TEST_PEM=str(directory / "ca.pem"), LSF_VAULT_TEST_CONTROL=str(ROOT / "tools/vault_test_support.py"))
        return subprocess.run([*launch, *test_command(args.test_manifest)], cwd=ROOT, env=env, timeout=300).returncode
    finally:
        close(name, token, identity)
        if remote_created:
            cleanup = "from pathlib import Path; import shutil,sys; p=Path(sys.argv[1]); assert p.parent==Path('/tmp') and p.name=='lsf-vault-test-'+sys.argv[2] and p.resolve()==p and not p.is_symlink(); shutil.rmtree(p)"
            command(["docker", "exec", args.cargo_container, "python3", "-c", cleanup, remote, token])
        print("Removed owned Vault server and temporary TLS files", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cargo-container", help="existing bounded Linux test container")
    parser.add_argument("--workspace", default="/phase3-current")
    parser.add_argument("--test-manifest", type=Path, help="reuse the built workspace test harness in CI")
    args = parser.parse_args()
    if args.cargo_container and args.test_manifest:
        parser.error("a local Cargo manifest cannot address another container's filesystem")
    target = ROOT / "target"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vault-conformance-", dir=target) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(target.resolve()) or directory.is_symlink():
            raise RuntimeError("invalid temporary Vault test root")
        return run(args, directory)


if __name__ == "__main__":
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    sys.exit(main())

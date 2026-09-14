#!/usr/bin/env python3
"""Real S3 blob conformance with one pinned, disposable TLS server."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

from run_oci_registry_tests import certificates, command
from s3_test_support import ACCESS, SECRET, Client

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "quay.io/minio/minio@sha256:a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2"
LABEL = "io.latent.s3-conformance"


def close(name: str, token: str, identity: str | None):
    found = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=15)
    if found.returncode:
        if not any(value in found.stderr.lower() for value in ("no such object", "no such container")):
            raise RuntimeError("cannot verify whether the owned S3 server was removed")
        return
    info = json.loads(found.stdout)[0]
    if info["Config"].get("Labels", {}).get(LABEL) != token or (identity and info["Id"] != identity):
        raise RuntimeError("refusing to remove a container with different ownership")
    command(["docker", "rm", "--force", info["Id"]])


def test_command(manifest: Path | None) -> list[str]:
    if manifest is None:
        return ["cargo", "test", "--locked", "--all-features", "-p", "latent-wasmtime", "--test", "s3_blobs",
                "real_s3_", "--", "--ignored", "--nocapture", "--test-threads=1"]
    if manifest.stat().st_size > 32 * 1024 * 1024:
        raise RuntimeError("Cargo test manifest exceeds its finite limit")
    executables = set()
    with manifest.open(encoding="utf-8") as source:
        for line in source:
            if len(line) > 131072:
                raise RuntimeError("Cargo test manifest line exceeds its finite limit")
            item = json.loads(line)
            if item.get("reason") == "compiler-artifact" and item.get("target", {}).get("name") == "s3_blobs" and item.get("profile", {}).get("test") and item.get("executable"):
                executables.add(item["executable"])
    if len(executables) != 1:
        raise RuntimeError("Cargo manifest must identify one S3 test harness")
    executable = Path(executables.pop()).resolve()
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    if not executable.is_file() or not executable.is_relative_to(target):
        raise RuntimeError("S3 test harness must reside in this Cargo target directory")
    return [str(executable), "real_s3_", "--ignored", "--nocapture", "--test-threads=1"]


def run(args, directory: Path):
    certificates(directory)
    shutil.copyfile(directory / "server.pem", directory / "public.crt")
    shutil.copyfile(directory / "server.key", directory / "private.key")
    token = uuid.uuid4().hex
    name = "lsf-s3-test-" + token
    remote = "/tmp/lsf-s3-test-" + token
    identity = None
    remote_created = False
    try:
        network = ["--publish", "127.0.0.1::9000"]
        port = 9000
        if args.cargo_container:
            port = int(command(["docker", "exec", args.cargo_container, "python3", "-c",
                                "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1])"]))
            network = ["--network", "container:" + args.cargo_container]
        identity = command(["docker", "run", "--detach", "--name", name, "--label", f"{LABEL}={token}",
            *network, "--memory", "512m", "--memory-swap", "512m", "--pids-limit", "128", "--cpus", "1",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--log-driver", "local", "--log-opt", "max-size=128k", "--log-opt", "max-file=1", "--log-opt", "compress=false",
            "--tmpfs", "/data:rw,nosuid,nodev,size=67108864", "--tmpfs", "/tmp:rw,nosuid,nodev,size=8388608",
            "--mount", f"type=bind,source={directory},target=/certs,readonly",
            "--env", f"MINIO_ROOT_USER={ACCESS}", "--env", f"MINIO_ROOT_PASSWORD={SECRET}",
            "--env", "MINIO_BROWSER=off", "--env", "MINIO_UPDATE=off", IMAGE,
            "server", "--quiet", "--certs-dir", "/certs", "--address", f":{port}", "/data"])
        if args.cargo_container:
            command(["docker", "exec", args.cargo_container, "mkdir", "-m", "700", remote])
            remote_created = True
            for source, target in [(directory / "ca.der", "ca.der"), (directory / "ca.pem", "ca.pem"), (ROOT / "tools/s3_test_support.py", "setup.py")]:
                command(["docker", "cp", str(source), f"{args.cargo_container}:{remote}/{target}"])
            command(["docker", "exec", args.cargo_container, "python3", remote + "/setup.py", str(port), remote + "/ca.pem"], timeout=40)
            launch = ["docker", "exec", "-w", args.workspace,
                      "-e", f"LSF_S3_TEST_PORT={port}", "-e", f"LSF_S3_TEST_CA={remote}/ca.der",
                      "-e", f"LSF_S3_TEST_PEM={remote}/ca.pem", "-e", f"LSF_S3_TEST_CONTROL={remote}/setup.py",
                      "-e", f"LSF_S3_TEST_INVENTORY={remote}/inventory", args.cargo_container]
            env = None
        else:
            info = json.loads(command(["docker", "inspect", identity]))[0]
            mapping = info["NetworkSettings"]["Ports"]["9000/tcp"]
            if len(mapping) != 1 or mapping[0]["HostIp"] != "127.0.0.1":
                raise RuntimeError("test server must have one loopback port")
            port = int(mapping[0]["HostPort"])
            Client(port, directory / "ca.pem").prepare()
            launch = []
            env = dict(os.environ, LSF_S3_TEST_PORT=str(port), LSF_S3_TEST_CA=str(directory / "ca.der"),
                       LSF_S3_TEST_PEM=str(directory / "ca.pem"), LSF_S3_TEST_CONTROL=str(ROOT / "tools/s3_test_support.py"),
                       LSF_S3_TEST_INVENTORY=str(directory / "inventory"))
        print("Running actual guest/S3 provider tests against pinned MinIO over TLS", flush=True)
        result = subprocess.run([*launch, *test_command(args.test_manifest)], cwd=ROOT, env=env, timeout=300)
        return result.returncode
    finally:
        # Failed docker-run can leave a created container. Inspect the unique
        # name, verify its ownership label, and remove only its immutable ID.
        close(name, token, identity)
        if remote_created:
            # One shell-independent Python operation validates the exact private
            # temporary root before recursively removing this run's inventory.
            cleanup = "from pathlib import Path; import shutil,sys; p=Path(sys.argv[1]); assert p.parent==Path('/tmp') and p.name=='lsf-s3-test-'+sys.argv[2] and p.resolve()==p and not p.is_symlink(); shutil.rmtree(p)"
            command(["docker", "exec", args.cargo_container, "python3", "-c", cleanup, remote, token])
        print("Removed owned S3 server, payload storage and temporary inventory", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cargo-container", help="existing bounded Linux test container; shares its network namespace")
    parser.add_argument("--workspace", default="/phase3-current")
    parser.add_argument("--test-manifest", type=Path, help="reuse the already built workspace test harness in CI")
    args = parser.parse_args()
    if args.cargo_container and args.test_manifest:
        parser.error("the local Cargo manifest option cannot address another container's filesystem")
    target = ROOT / "target"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="s3-conformance-", dir=target) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(target.resolve()) or directory.is_symlink():
            raise RuntimeError("invalid temporary test root")
        return run(args, directory)


if __name__ == "__main__":
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    sys.exit(main())

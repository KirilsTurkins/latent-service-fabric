#!/usr/bin/env python3
"""Run tiny OCI integration tests against one owned, temporary TLS registry."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/project-zot/zot-minimal-linux-amd64@sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395"
LABEL = "io.latent.oci-test-run"
USERNAME = "lsf-test-only"
PASSWORD = "lsf-test-only-password"
FIXTURE = ROOT / "crates/latent-oci/tests/fixtures/registry/htpasswd"


def command(arguments: list[str], *, timeout: float = 30) -> str:
    """Only fixed local tooling uses captured output; never print command arguments."""
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(arguments[0]).name} command failed ({result.returncode})")
    if len(result.stdout) > 65_536:
        raise RuntimeError("local command output exceeded diagnostic limit")
    return result.stdout.strip()


def openssl_path() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parents[1] / "usr/bin/openssl.exe"
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("OpenSSL is required to generate short-lived test certificates")


def certificates(directory: Path) -> None:
    executable = openssl_path()
    command([executable, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(directory / "ca.key"), "-out", str(directory / "ca.pem"),
             "-days", "2", "-sha256", "-subj", "/CN=LSF PUBLIC TEST ONLY CA",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign"])
    command([executable, "req", "-new", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(directory / "server.key"), "-out", str(directory / "server.csr"),
             "-subj", "/CN=LSF PUBLIC TEST ONLY REGISTRY"])
    extensions = directory / "server.ext"
    extensions.write_text("basicConstraints=critical,CA:FALSE\n"
                          "keyUsage=critical,digitalSignature,keyEncipherment\n"
                          "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n",
                          encoding="ascii")
    command([executable, "x509", "-req", "-in", str(directory / "server.csr"),
             "-CA", str(directory / "ca.pem"), "-CAkey", str(directory / "ca.key"),
             "-set_serial", "2", "-out", str(directory / "server.pem"), "-days", "1",
             "-sha256", "-extfile", str(extensions)])
    command([executable, "x509", "-in", str(directory / "ca.pem"), "-outform", "DER",
             "-out", str(directory / "ca.der")])
    shutil.copyfile(FIXTURE, directory / "htpasswd")
    (directory / "config.json").write_text(json.dumps({
        "distSpecVersion": "1.1.1",
        "storage": {"rootDirectory": "/var/lib/registry", "gc": False, "dedupe": False},
        "http": {"address": "0.0.0.0", "port": "5000",
                 "tls": {"cert": "/fixtures/server.pem", "key": "/fixtures/server.key"},
                 "auth": {"htpasswd": {"path": "/fixtures/htpasswd"}, "failDelay": 0}},
        "log": {"level": "error"},
    }), encoding="ascii")
    # The container drops all capabilities. On Linux it must be able to read
    # this host-owned bind mount without DAC override. These credentials are
    # explicitly public test material, never copied from operator secrets.
    directory.chmod(0o755)
    for name in ("ca.pem", "ca.der", "server.pem", "server.key", "htpasswd", "config.json"):
        (directory / name).chmod(0o644)
    for name in ("ca.key", "server.csr", "server.ext"):
        (directory / name).unlink()


class Registry:
    def __init__(self, directory: Path, state_file: Path | None = None):
        self.directory = directory.resolve()
        self.token = uuid.uuid4().hex
        self.name = f"lsf-oci-test-{self.token}"
        self.state_file = state_file
        self.state_owned = False

    def launch(self) -> str:
        command(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"])
        if self.state_file:
            # Exclusive creation prevents overwriting another run's recovery state.
            with self.state_file.open("x", encoding="ascii") as state:
                self.state_owned = True
                json.dump({"name": self.name, "token": self.token}, state)
        command(["docker", "run", "--detach", "--rm", "--name", self.name,
                 "--label", f"{LABEL}={self.token}", "--publish", "127.0.0.1::5000",
                 "--memory", "256m", "--memory-swap", "256m", "--pids-limit", "64",
                 "--cpus", "1", "--read-only", "--cap-drop", "ALL", "--security-opt",
                 "no-new-privileges", "--log-driver", "local", "--log-opt", "max-size=128k",
                 "--log-opt", "max-file=1", "--log-opt", "compress=false",
                 "--tmpfs", "/var/lib/registry:rw,nosuid,nodev,size=134217728",
                 "--tmpfs", "/tmp:rw,nosuid,nodev,size=8388608", "--mount",
                 f"type=bind,source={self.directory},target=/fixtures,readonly",
                 IMAGE, "serve", "/fixtures/config.json"])
        mapping = json.loads(command(["docker", "inspect", self.name, "--format",
                                      '{{json (index .NetworkSettings.Ports "5000/tcp")}}']))
        if len(mapping) != 1 or mapping[0]["HostIp"] != "127.0.0.1":
            raise RuntimeError("registry port was not isolated to IPv4 loopback")
        port = mapping[0]["HostPort"]
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 0 < int(port) < 65_536:
            raise RuntimeError("invalid registry port mapping")
        return f"https://127.0.0.1:{port}"

    def close(self) -> None:
        result = subprocess.run(["docker", "inspect", self.name, "--format",
                                 '{"id":{{json .Id}},"labels":{{json .Config.Labels}}}'], capture_output=True,
                                text=True, timeout=15)
        if result.returncode:
            if "no such object" not in result.stderr.lower() and "no such container" not in result.stderr.lower():
                raise RuntimeError("unable to confirm owned registry cleanup")
            if self.state_file and self.state_owned:
                self.state_file.unlink(missing_ok=True)
            return
        identity = json.loads(result.stdout)
        if (identity["labels"].get(LABEL) != self.token
                or not re.fullmatch(r"[0-9a-f]{64}", identity["id"])):
            raise RuntimeError("refusing to remove a container without this run's ownership label")
        # Remove the verified immutable ID, not a name that could be reused.
        command(["docker", "rm", "--force", identity["id"]], timeout=20)
        if self.state_file and self.state_owned:
            self.state_file.unlink(missing_ok=True)


def cleanup_state(path: Path) -> None:
    if not path.exists():
        return
    if path.stat().st_size > 256:
        raise RuntimeError("invalid owned-container recovery state")
    state = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(state, dict):
        raise RuntimeError("invalid owned-container recovery state")
    token = state.get("token", "")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token) or state.get("name") != f"lsf-oci-test-{token}":
        raise RuntimeError("invalid owned-container recovery identity")
    registry = Registry(path.parent, path)
    registry.token, registry.name = token, state["name"]
    registry.state_owned = True
    registry.close()


def ready(origin: str, certificate: Path, timeout: float = 30) -> None:
    context = ssl.create_default_context(cafile=str(certificate))
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=context))
    authorization = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(origin + "/v2/", headers={"Authorization": "Basic " + authorization})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with client.open(request, timeout=min(2, max(0.1, deadline - time.monotonic()))) as response:
                if response.status == 200 and len(response.read(4097)) <= 4096:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise RuntimeError("temporary TLS registry did not become ready within its deadline")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-fixture", action="store_true", help="check TLS/auth startup and cleanup only")
    parser.add_argument("--test-binary", type=Path, help="run an already-built registry test binary")
    parser.add_argument("--provenance-input", type=Path,
                        help="include actual observed-build round trip using package-ready build_provenance output")
    parser.add_argument("--state-file", type=Path, help="exclusive CI recovery state, removed after cleanup")
    parser.add_argument("--cleanup-state", type=Path, help="recover only the labelled container in this state file")
    arguments = parser.parse_args()
    if arguments.cleanup_state:
        cleanup_state(arguments.cleanup_state)
        return 0
    if not arguments.check_fixture and arguments.test_binary is None:
        subprocess.run(["cargo", "test", "-p", "latent-oci", "--test", "registry", "--locked", "--no-run"],
                       cwd=ROOT, check=True, timeout=900)
    with tempfile.TemporaryDirectory(prefix="lsf-oci-test-") as temporary:
        directory = Path(temporary)
        certificates(directory)
        registry = Registry(directory, arguments.state_file)
        try:
            origin = registry.launch()
            ready(origin, directory / "ca.pem")
            if arguments.check_fixture:
                print("Disposable registry TLS/auth fixture passed.")
                return 0
            environment = os.environ.copy()
            environment.update(LSF_OCI_TEST_ORIGIN=origin, LSF_OCI_TEST_CA_DER=str(directory / "ca.der"))
            environment.pop("LSF_OCI_PROVENANCE_INPUT", None)
            extra = []
            if arguments.provenance_input:
                environment["LSF_OCI_PROVENANCE_INPUT"] = str(arguments.provenance_input.resolve(strict=True))
            else:
                extra = ["--skip", "real_observed_build_provenance_roundtrip"]
            test = ([str(arguments.test_binary.resolve())] if arguments.test_binary else
                    ["cargo", "test", "-p", "latent-oci", "--test", "registry", "--locked", "--"])
            subprocess.run([*test, "--ignored", "--test-threads=1", "--nocapture", *extra], cwd=ROOT,
                           env=environment, check=True, timeout=180)
            print("Disposable registry integration passed; no artifacts retained.")
            return 0
        finally:
            registry.close()


if __name__ == "__main__":
    def interrupted(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        # Do not expose HTTP URLs, headers, subprocess arguments or credential material.
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f"OCI registry test failed: {reason}", file=sys.stderr)
        sys.exit(1)

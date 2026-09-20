#!/usr/bin/env python3
"""Run tiny OCI integration tests against one owned, temporary TLS registry."""

from __future__ import annotations

import argparse
import base64
from contextvars import ContextVar
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


try:
    from tools.test_run import ProcessFailure, Ready, TestRun, contract, require, selected_contract
    from tools.prepared_test_harness import execute, wasm
except ModuleNotFoundError as error:
    if error.name != "tools":
        raise
    from test_run import ProcessFailure, Ready, TestRun, contract, require, selected_contract
    from prepared_test_harness import execute, wasm

ACTIVE_RUN: ContextVar[TestRun | None] = ContextVar("oci_owned_run", default=None)

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/project-zot/zot-minimal-linux-amd64@sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395"
LABEL = "io.latent.oci-test-run"
USERNAME = "lsf-test-only"
PASSWORD = "lsf-test-only-password"
FIXTURE = ROOT / "crates/latent-oci/tests/fixtures/registry/htpasswd"
WEB_TEST = "supply_chain::tests::web_catalog::registry::authenticated_web_registry_admission_roundtrip"


def test_target(web: bool) -> list[str]:
    """Build and run the same target; web mode selects exactly one required test."""
    return (["-p", "latent-policy", "--lib"] if web else
            ["-p", "latent-oci", "--test", "registry"])


def test_filters(web: bool, observed: bool) -> list[str]:
    if web:
        return ["--exact", WEB_TEST]
    filters = ["--skip", "bearer::real_harbor_bearer_roundtrip"]
    return filters if observed else [*filters, "--skip", "real_observed_build_provenance_roundtrip"]


def command(arguments: list[str], *, timeout: float = 30) -> str:
    """Only fixed local tooling uses captured output; never print command arguments."""
    owner = ACTIVE_RUN.get()
    if owner is not None:
        return owner.command(arguments, timeout=timeout).output.decode("utf-8").strip()
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


def certificates(directory: Path, *, dns_names: tuple[str, ...] = ()) -> None:
    if len(dns_names) > 8 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', name) for name in dns_names):
        raise RuntimeError('invalid fixture certificate DNS name')
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
                          "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1"
                          + ''.join(',DNS:' + name for name in dns_names) + '\n',
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
        self.container_id: str | None = None

    def inspect(self, template: str):
        arguments = ["docker", "inspect", self.name, "--format", template]
        owner = ACTIVE_RUN.get()
        if owner is None:
            return subprocess.run(arguments, capture_output=True, text=True, timeout=15)
        result = owner.command(arguments, timeout=15, check=False)
        # Docker CLI diagnostics are captured together and bounded by the owner.
        text = result.output.decode("utf-8", "replace")
        return subprocess.CompletedProcess(arguments, result.returncode, text if result.returncode == 0 else "", text)

    def alive(self, origin: str) -> bool:
        result = self.inspect('{"id":{{json .Id}},"labels":{{json .Config.Labels}},'
                              '"running":{{json .State.Running}},"ports":{{json .NetworkSettings.Ports}}}')
        if result.returncode:
            return False
        identity = json.loads(result.stdout)
        require(identity["id"] == self.container_id and identity["labels"].get(LABEL) == self.token,
                "invalid-fixture", "readiness-container-identity-mismatch")
        mapping = identity["ports"].get("5000/tcp")
        require(isinstance(mapping, list) and len(mapping) == 1 and mapping[0]["HostIp"] == "127.0.0.1"
                and origin == "https://127.0.0.1:" + mapping[0]["HostPort"],
                "invalid-fixture", "readiness-container-endpoint-mismatch")
        return identity["running"] is True

    def launch(self) -> str:
        command(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"])
        if self.state_file:
            # Exclusive creation prevents overwriting another run's recovery state.
            fd = os.open(self.state_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as state:
                self.state_owned = True
                json.dump({"name": self.name, "token": self.token}, state)
        created = command(["docker", "run", "--pull=never", "--detach", "--rm", "--name", self.name,
                 "--label", f"{LABEL}={self.token}", "--publish", "127.0.0.1::5000",
                 "--memory", "256m", "--memory-swap", "256m", "--pids-limit", "64",
                 "--cpus", "1", "--read-only", "--cap-drop", "ALL", "--security-opt",
                 "no-new-privileges", "--log-driver", "local", "--log-opt", "max-size=128k",
                 "--log-opt", "max-file=1", "--log-opt", "compress=false",
                 "--tmpfs", "/var/lib/registry:rw,nosuid,nodev,size=134217728",
                 "--tmpfs", "/tmp:rw,nosuid,nodev,size=8388608", "--mount",
                 f"type=bind,source={self.directory},target=/fixtures,readonly",
                 IMAGE, "serve", "/fixtures/config.json"])
        require(re.fullmatch(r"[0-9a-f]{64}", created), "invalid-fixture", "invalid-owned-container-id")
        self.container_id = created
        mapping = json.loads(command(["docker", "inspect", self.name, "--format",
                                      '{{json (index .NetworkSettings.Ports "5000/tcp")}}']))
        if len(mapping) != 1 or mapping[0]["HostIp"] != "127.0.0.1":
            raise RuntimeError("registry port was not isolated to IPv4 loopback")
        port = mapping[0]["HostPort"]
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 0 < int(port) < 65_536:
            raise RuntimeError("invalid registry port mapping")
        return f"https://127.0.0.1:{port}"

    def close(self) -> None:
        result = self.inspect('{"id":{{json .Id}},"labels":{{json .Config.Labels}}}')
        if result.returncode:
            if "no such object" not in result.stderr.lower() and "no such container" not in result.stderr.lower():
                raise RuntimeError("unable to confirm owned registry cleanup")
            if self.state_file and self.state_owned:
                self.remove_state()
            return
        identity = json.loads(result.stdout)
        if (identity["labels"].get(LABEL) != self.token
                or not re.fullmatch(r"[0-9a-f]{64}", identity["id"])
                or self.container_id is not None and self.container_id != identity["id"]):
            raise RuntimeError("refusing to remove a container without this run's ownership label")
        # Remove the verified immutable ID, not a name that could be reused.
        command(["docker", "rm", "--force", identity["id"]], timeout=20)
        owner = ACTIVE_RUN.get()
        if owner is not None:
            removed = owner.command(["docker", "inspect", identity["id"]], timeout=5, check=False)
            message = removed.output.decode("utf-8", "replace").lower()
            require(removed.returncode != 0 and ("no such object" in message or "no such container" in message),
                    "infrastructure-timeout", "registry-retirement-unconfirmed")
        if self.state_file and self.state_owned:
            self.remove_state()

    def remove_state(self) -> None:
        if not self.state_file or not self.state_owned or not self.state_file.exists():
            return
        require(not self.state_file.is_symlink() and self.state_file.stat().st_size <= 256,
                "invalid-fixture", "recovery-state-changed")
        with self.state_file.open("rb") as source:
            identity = os.fstat(source.fileno())
            record = json.loads(source.read(257))
        require(record == {"name": self.name, "token": self.token}
                and self.state_file.stat().st_ino == identity.st_ino,
                "invalid-fixture", "recovery-state-not-owned")
        self.state_file.unlink()


def cleanup_state(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or path.stat().st_size > 256:
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


def ready(origin: str, certificate: Path, timeout: float = 30, *, registry: Registry | None = None) -> None:
    context = ssl.create_default_context(cafile=str(certificate))
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=context))
    authorization = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(origin + "/v2/", headers={"Authorization": "Basic " + authorization})
    owner = ACTIVE_RUN.get()
    if owner is not None:
        require(registry is not None and registry.container_id is not None,
                "invalid-fixture", "missing-readiness-owner")
        expected = Ready(registry.container_id, owner.run_id, origin, "oci-distribution-v2-tls")
        def probe():
            try:
                with client.open(request, timeout=owner.remaining(2)) as response:
                    body = response.read(4097)
                    require(response.status == 200 and len(body) <= 4096 and body.strip() in (b"{}", b""),
                            "invalid-fixture", "invalid-registry-protocol-readiness")
                    return expected
            except urllib.error.HTTPError:
                raise ProcessFailure("assertion-failure", "registry-readiness-authentication-failed") from None
            except (OSError, urllib.error.URLError):
                return None
        owner.ready(expected, lambda: registry.alive(origin), probe, timeout)
        return
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


def provenance_artifacts(owner: TestRun, root: Path) -> None:
    for leaf in ("observation.json", "package-source.json", "sbom-inputs.json"):
        owner.artifact("provenance-" + leaf, root / leaf, 2 * 1024 * 1024)
    with (root / "package-source.json").open("rb") as source:
        recipe = json.loads(source.read(2 * 1024 * 1024 + 1))
    layers = recipe.get("layers")
    require(isinstance(layers, list) and 0 < len(layers) <= 128,
            "invalid-fixture", "invalid-provenance-layer-count")
    total = 0
    for index, layer in enumerate(layers):
        value = layer.get("source")
        require(isinstance(value, str) and not value.startswith("/") and "\\" not in value
                and all(part not in {"", ".", ".."} for part in value.split("/")),
                "invalid-fixture", "invalid-provenance-layer-path")
        path = root / value
        require(path.resolve().is_relative_to(root.resolve()), "invalid-fixture", "foreign-provenance-layer")
        owner.artifact("provenance-layer-" + str(index), path)
        total += path.stat().st_size
        require(total <= 64 * 1024 * 1024, "invalid-fixture", "provenance-total-byte-limit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-fixture", action="store_true", help="TLS/auth startup and cleanup only; not LSF qualification")
    parser.add_argument("--preflight", action="store_true", help="check environment before preparing/building artifacts")
    parser.add_argument("--test-manifest", type=Path, help="successful explicit Cargo JSON build inventory")
    parser.add_argument("--test-binary", type=Path, help="optional assertion against the manifest-selected executable")
    parser.add_argument("--provenance-input", type=Path)
    parser.add_argument("--web-admission-component", type=Path)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--cleanup-state", type=Path)
    parser.add_argument("--diagnostic-root", type=Path)
    parser.add_argument("--inject-failure", choices=["after-ready"], help="fixture fault demonstration, never qualification")
    arguments = parser.parse_args(argv)
    if arguments.web_admission_component and arguments.provenance_input:
        parser.error("web admission and capsule provenance use separate test targets")
    web = arguments.web_admission_component is not None
    name = "oci-web" if web else "oci-registry"
    policy, rows = selected_contract(name, repo=ROOT, diagnostic_root=arguments.diagnostic_root)
    with TestRun(name, policy, repo=ROOT, reproduction={"suite": name, "web": web,
                 "observed": arguments.provenance_input is not None, "fixtureOnly": arguments.check_fixture,
                 "preflight": arguments.preflight, "fault": arguments.inject_failure or "none"},
                 secrets=(PASSWORD,), diagnostic_root=arguments.diagnostic_root) as owner:
        token = ACTIVE_RUN.set(owner)
        try:
            owner.source_identity()
            if arguments.cleanup_state:
                owner.mark("teardown")
                cleanup_state(arguments.cleanup_state)
                return 0
            owner.prerequisites(before_build=True)
            if arguments.preflight:
                return 0
            if not arguments.check_fixture:
                require(arguments.test_manifest is not None, "invalid-fixture", "explicit-test-manifest-required")
                inputs = {"test-manifest": arguments.test_manifest}
                if web:
                    inputs["component"] = arguments.web_admission_component
                owner.prerequisites(inputs)
                if web:
                    wasm(owner, "component", arguments.web_admission_component)
                if arguments.provenance_input:
                    provenance_artifacts(owner, arguments.provenance_input)
            directory = owner.root / "registry"
            directory.mkdir(mode=0o700)
            owner.mark("startup")
            certificates(directory)
            owner.artifact("registry-ca", directory / "ca.der", 65536)
            owner.artifact("registry-config", directory / "config.json", 65536)
            owner.artifact("registry-auth-fixture", directory / "htpasswd", 65536)
            owner.fixture_ids["registry-image"] = IMAGE.rsplit("@", 1)[1]
            registry = Registry(directory, arguments.state_file)
            # Register before launch: interrupted creation still has a labelled
            # identity and recovery state, even if the CLI result is lost.
            owner.cleanup.append(registry.close)
            origin = registry.launch()
            owner.mark("readiness")
            ready(origin, directory / "ca.pem", registry=registry)
            if arguments.inject_failure:
                raise ProcessFailure("assertion-failure", "injected-after-ready")
            if arguments.check_fixture:
                return 0
            environment = dict(os.environ, LSF_OCI_TEST_ORIGIN=origin,
                               LSF_OCI_TEST_CA_DER=str(directory / "ca.der"))
            environment.pop("LSF_OCI_PROVENANCE_INPUT", None)
            environment.pop("LSF_WEB_COMPONENT", None)
            if web:
                environment["LSF_WEB_COMPONENT"] = str(arguments.web_admission_component.resolve())
            if arguments.provenance_input:
                environment["LSF_OCI_PROVENANCE_INPUT"] = str(arguments.provenance_input.resolve())
            row = rows[policy["suiteIds"][0]]
            selected = ([WEB_TEST] if web else [case for case in row["expectedIgnored"]
                        if case != "bearer::real_harbor_bearer_roundtrip" and
                        (arguments.provenance_input is not None or case != "real_observed_build_provenance_roundtrip")])
            execute(owner, row, arguments.test_manifest, environment, selected=selected,
                    timeout=180, binary=arguments.test_binary)
            return 0
        finally:
            # __exit__ executes registered cleanup after this block. Preserve the
            # context until then so recovery commands share the total deadline.
            owner.cleanup.insert(0, lambda: ACTIVE_RUN.reset(token))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        reason = error.reason if isinstance(error, ProcessFailure) else type(error).__name__
        print(f"OCI registry test failed: {reason}", file=sys.stderr)
        sys.exit(1)

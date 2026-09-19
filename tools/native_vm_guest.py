#!/usr/bin/env python3
"""Trusted VM test controller; never import or execute an unauthenticated bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time

ROOT = Path("/opt/lsf-native-test")
PLAN = ROOT / "plan.json"
STATE = ROOT / "state.json"
PREFIX = Path("/opt/lsf")
CONFIG = Path("/etc/lsf")
REPOSITORY = "KirilsTurkins/latent-service-fabric"
LAST = "initialization"
CHECKS = []
DETAILS = {}


class Failure(Exception):
    pass


def require(condition, diagnostic):
    if not condition:
        raise Failure(diagnostic)


def read(path, maximum=1_048_576):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, "test-input-file-boundary")
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    require(len(data) <= maximum, "test-input-byte-limit")
    return data


def value(path):
    return json.loads(read(path))


def write(path, document, mode=0o600):
    with path.open("x", encoding="utf-8") as output:
        json.dump(document, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")
    path.chmod(mode)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(65536):
            result.update(data)
    return result.hexdigest()


def run(command, *, timeout=90, codes=(0,), identity=None, maximum=1_048_576):
    global LAST
    LAST = Path(str(command[0])).name + ":" + next((str(part) for part in command[1:]
                                                  if str(part) in {"install", "verify", "preflight", "readiness",
                                                                   "publish", "publish-package", "apply", "invoke",
                                                                   "remove", "purge", "start", "stop"}), "command")
    options = {"user": identity[0], "group": identity[1], "extra_groups": []} if identity is not None else {}
    process = subprocess.Popen([str(part) for part in command], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                               env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp",
                                    "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}, **options)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < deadline, "test-command-timeout")
                for key, _events in selector.select(0.1):
                    data = os.read(key.fd, min(65536, maximum + 1 - len(output)))
                    if data:
                        output.extend(data)
                        require(len(output) <= maximum, "test-command-output-limit")
                    else:
                        selector.unregister(key.fileobj)
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        if codes is not None and process.returncode not in codes:
            diagnostic = "test-command-failed"
            try:
                parsed = json.loads(output)
                supplied = parsed.get("diagnostic") or parsed.get("error", {}).get("code")
                if isinstance(supplied, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", supplied):
                    diagnostic += ":" + supplied
            except (ValueError, AttributeError):
                pass
            raise Failure(diagnostic)
        return process.returncode, bytes(output)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()


def passed(name):
    CHECKS.append(name)


def bootstrap(plan, command, *extra, codes=(0,), identity=None, release=None):
    location = ["--directory", plan["localDirectory"]] if plan.get("localDirectory") else ["--system"]
    arguments = ["/usr/bin/python3", "-I", plan["releaseDirectory"] + "/lsf-install.pyz", command]
    if command != "verify":
        arguments += location
    if command in {"install", "verify"}:
        arguments += ["--release-directory", release or plan["releaseDirectory"], "--version", plan["version"],
                      "--publisher-policy", plan["publisherPolicy"], "--trusted-root", plan["trustedRoot"],
                      "--verifier", plan["verifier"]]
        if plan["purpose"] == "candidate":
            arguments.append("--allow-candidate")
    if command == "install":
        arguments += ["--profile", plan["profile"]]
        if plan["profile"] == "local-experimental-v1":
            arguments.append("--acknowledge-experimental")
        elif plan.get("admissionPolicy"):
            arguments += ["--trust-policy", plan["admissionPolicy"]]
    status, output = run([*arguments, *extra], codes=codes, identity=identity, timeout=150)
    return status, json.loads(output)


def authenticate(plan, negatives=False):
    release = Path(plan["releaseDirectory"])
    policy = value(Path(plan["publisherPolicy"]))
    require(policy["sourceCommit"] == plan["sourceCommit"] and policy["version"] == plan["version"]
            and policy["repository"] == REPOSITORY and policy["purpose"] == plan["purpose"], "independent-test-policy-mismatch")
    expected_workflow = ".github/workflows/native-runtime-release.yml" if plan["purpose"] == "release" else ".github/workflows/native-runtime.yml"
    require(policy["workflow"] == expected_workflow and policy["sourceRef"] == plan["sourceRef"], "independent-workflow-mismatch")
    for name, maximum in (("SHA256SUMS", 8192), ("SHA256SUMS.sigstore.json", 1_048_576), ("release.json", 1_048_576)):
        read(release / name, maximum)
    command = [plan["verifier"], "attestation", "verify", release / "SHA256SUMS",
               "--bundle", release / "SHA256SUMS.sigstore.json", "--custom-trusted-root", plan["trustedRoot"],
               "--repo", REPOSITORY, "--hostname", "github.com", "--cert-identity",
               f"https://github.com/{REPOSITORY}/{expected_workflow}@{plan['sourceRef']}",
               "--cert-oidc-issuer", "https://token.actions.githubusercontent.com", "--source-ref", plan["sourceRef"],
               "--source-digest", plan["sourceCommit"], "--signer-digest", plan["sourceCommit"],
               "--deny-self-hosted-runners", "--predicate-type", "https://slsa.dev/provenance/v1"]
    isolated = ["/usr/bin/unshare", "--net"] if os.geteuid() == 0 else []
    run([*isolated, *command], timeout=60)
    expected = {}
    for line in read(release / "SHA256SUMS", 8192).decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)", line)
        require(match and match[2] not in expected, "bootstrap-checksum-format")
        expected[match[2]] = match[1]
    require(set(expected) == {"release.json", "lsf-install.pyz", f"lsf-{plan['version']}-x86_64-unknown-linux-gnu.tar.gz"},
            "bootstrap-checksum-inventory")
    for name, checksum in expected.items():
        require(digest(release / name) == checksum, "bootstrap-checksum-mismatch")
    passed("publisher-authentication-before-downloaded-bootstrap")
    if negatives:
        for flag, replacement in (("--source-digest", "0" * 40), ("--cert-identity", "https://github.com/attacker/repository")):
            rejected = list(command)
            rejected[rejected.index(flag) + 1] = replacement
            status, _output = run([*isolated, *rejected], codes=None, timeout=60)
            require(status != 0, "incorrect-publisher-identity-accepted")
        tampered = ROOT / "tampered-SHA256SUMS"
        tampered.write_bytes(read(release / "SHA256SUMS") + b"tampered\n")
        rejected = list(command)
        rejected[3] = tampered
        require(run([*isolated, *rejected], codes=None, timeout=60)[0] != 0, "tampered-checksums-accepted")
        rejected = list(command)
        rejected[rejected.index("--bundle") + 1] = ROOT / "missing-attestation.json"
        require(run([*isolated, *rejected], codes=None, timeout=60)[0] != 0, "unsigned-bundle-accepted")
        passed("offline-crypto-rejects-tamper-unsigned-wrong-repository-and-commit")
    verified = bootstrap(plan, "verify")[1]
    require(verified["sourceCommit"] == plan["sourceCommit"], "bootstrap-source-mismatch")
    passed("installer-repeats-offline-publisher-verification")
    return verified


def service_identity():
    account = pwd.getpwnam("lsf")
    require(0 < account.pw_uid < 1000, "node-service-uid")
    return account.pw_uid, account.pw_gid


def systemctl(*arguments):
    return run(["/usr/bin/systemctl", "--no-pager", *arguments], timeout=100)[1].decode().strip()


def clean_stop(invocation=None):
    invocation = invocation or systemctl("show", "lsf.service", "--property=InvocationID", "--value")
    require(re.fullmatch(r"[0-9a-f]{32}", invocation), "systemd-invocation-identity")
    if systemctl("show", "lsf.service", "--property=InvocationID", "--value") == invocation:
        systemctl("stop", "lsf.service")
    require(systemctl("show", "lsf.service", "--property=MainPID", "--value") == "0" or
            systemctl("show", "lsf.service", "--property=InvocationID", "--value") != invocation, "node-not-reaped")
    records = run(["/usr/bin/journalctl", "--no-pager", "-o", "cat", "--lines=80",
                   "_SYSTEMD_INVOCATION_ID=" + invocation], maximum=262144)[1]
    stopped = []
    for line in records.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("schemaVersion") == "latent.standalone.status.v1" and record.get("event") == "stopped":
            stopped.append(record)
    require(len(stopped) == 1 and stopped[0].get("clean") is True and stopped[0].get("report", {}).get("clean") is True,
            "missing-clean-node-shutdown-record")
    passed("systemd-invocation-scoped-clean-shutdown-and-process-reap")


def backup_and_restore(plan, name):
    require(systemctl("show", "lsf.service", "--property=MainPID", "--value") == "0", "backup-requires-stopped-node")
    original = protected_hashes()
    backup = ROOT / (name + ".tar")
    run(["/usr/bin/tar", "--create", "--file", backup, "--numeric-owner", "--one-file-system", "--directory", "/",
         "etc/lsf", "var/lib/lsf", "var/cache/lsf", "opt/lsf/installed.json"], timeout=60)
    require(backup.stat().st_size <= 134_217_728 and backup.stat().st_mode & 0o077 == 0, "private-bounded-consistent-backup-required")
    with tarfile.open(backup) as saved:
        count = 0
        total = 0
        for entry in saved:
            count += 1
            total += entry.size
            require(count <= 8192 and total <= 134_217_728 and not entry.name.startswith("/")
                    and ".." not in entry.name.split("/") and (entry.isdir() or entry.isfile()), "unsafe-test-backup")
    node = CONFIG / "node.json"
    node.write_bytes(b'{"deliberatelyInterruptedOperatorEdit":true}\n')
    require(bootstrap(plan, "preflight", codes=None, identity=service_identity())[0] != 0, "invalid-recovery-config-accepted")
    run(["/usr/bin/tar", "--extract", "--same-owner", "--same-permissions", "--file", backup, "--directory", "/"], timeout=60)
    require(protected_hashes() == original, "stopped-compatible-backup-restore-changed-protected-state")
    passed("stopped-consistent-backup-and-exact-compatible-set-restore")


def protected_hashes(config=CONFIG):
    names = ["node.json", "client/client.json"]
    if (config / "private/native-aot.key").exists():
        names += ["private/native-aot.key", "admission-policy.json"]
    return {name: digest(config / name) for name in names}


def cli(plan, *arguments, codes=(0,)):
    prefix = Path(plan.get("localDirectory", str(PREFIX)))
    config = prefix / "config" if plan.get("localDirectory") else CONFIG
    output = run([prefix / "current/bin/latent", "--config", config / "client/client.json", "--output", "json",
                  *arguments], codes=codes, timeout=30)[1]
    result = json.loads(output)
    require(result.get("schemaVersion") == "latent.cli.result.v1", "cli-result-schema")
    if codes == (0,):
        require(result.get("category") == "success" and result.get("outcomeKnown") is True, "uncertain-mutation-do-not-replay")
    return result


def invoke(plan, retained, stage):
    prefix = Path(plan.get("localDirectory", str(PREFIX)))
    activation = "native-" + stage
    result = cli(plan, "invoke", "--service", "examples/echo", "--contract", "examples:echo/api@0.1.0",
                 "--function", "echo", "--input", prefix / "current/examples/echo/input.json",
                 "--activation-id", activation, "--cpu-fuel", "1000000", "--memory-bytes", "4194304",
                 "--log-bytes", "16384", "--wall-time-ms", "5000", "--rpc-timeout-ms", "5000")
    data = result["data"]
    payload = data["payload"]
    require(data["activationId"] == activation and payload["encoding"] == "base64"
            and payload["mediaType"] == "application/vnd.latent.wit-values.v1+json" and len(payload["data"]) <= 4096,
            "echo-result-envelope")
    returned = base64.b64decode(payload["data"], validate=True)
    expected = value(prefix / "current/examples/echo/input.json")[0]
    require(json.loads(returned) == [{"ok": expected}] and int(payload["byteLength"]) == len(returned), "echo-result")
    pin = data["resolvedRevision"]
    require(pin["releaseDigest"] == retained["componentDigest"] and pin["publicationId"] == retained["publicationId"],
            "retained-publication-identity")
    passed("packaged-echo-invocation-" + stage)


def publish(plan):
    prefix = Path(plan.get("localDirectory", str(PREFIX)))
    example = prefix / "current/examples/echo"
    if plan["profile"] == "external-capsule-v1":
        result = cli(plan, "release", "publish-package", plan["packageDirectory"], "--evidence", plan["packageEvidence"],
                     "--operation-id", "native-publish", "--expected-generation", "0")
    else:
        result = cli(plan, "release", "publish", "--manifest", example / "capsule.json", "--component", example / "echo-capsule.wasm",
                     "--contracts", example / "contracts.json", "--operation-id", "native-publish", "--expected-generation", "0")
    release = result["data"]["release"]
    require(release["digest"] == "sha256:" + digest(example / "echo-capsule.wasm"), "published-bundled-component-identity")
    deployment = value(example / "deployment.json")
    deployment["metadata"]["name"] = "native-retained"
    deployment["spec"]["release"] = release["digest"]
    deployment["spec"]["publication"] = release["publication"]["id"]
    directory = Path(plan.get("localDirectory", str(ROOT)))
    deployment_path = directory / ("deployment-" + plan["version"] + ".json")
    write(deployment_path, deployment)
    snapshot = cli(plan, "deployment", "get", "native-retained", "--operation-snapshot", codes=(6,))["data"]
    cli(plan, "deployment", "apply", deployment_path, "--operation-id", "native-deploy",
        "--expected-generation", "0", "--expected-state-version", str(snapshot["stateVersion"]))
    retained = {"componentDigest": release["digest"], "publicationId": release["publication"]["id"], "deployment": "native-retained"}
    invoke(plan, retained, "first")
    return retained


def negative_configuration(plan):
    identity = service_identity()
    node = CONFIG / "node.json"
    original = read(node, 65536)
    try:
        node.chmod(0o644)
        require(bootstrap(plan, "preflight", codes=None, identity=identity)[0] != 0, "public-credential-file-accepted")
        node.chmod(0o640)
        invalid = json.loads(original)
        invalid["securityProfile"] = "unsupported-native-test-profile"
        node.write_text(json.dumps(invalid))
        require(bootstrap(plan, "preflight", codes=None, identity=identity)[0] != 0, "unsupported-profile-accepted")
        invalid = json.loads(original)
        invalid["credentials"][0]["token"] = "native-readiness-deliberately-not-the-live-credential"
        node.write_text(json.dumps(invalid))
        require(bootstrap(plan, "readiness", codes=None, identity=identity)[0] != 0, "unauthenticated-readiness-accepted")
    finally:
        node.write_bytes(original)
        node.chmod(0o640)
    if plan["profile"] == "external-capsule-v1":
        key = CONFIG / "private/native-aot.key"
        before = digest(key)
        try:
            key.chmod(0o644)
            require(bootstrap(plan, "preflight", codes=None, identity=identity)[0] != 0, "public-aot-key-accepted")
        finally:
            key.chmod(0o600)
        require(digest(key) == before, "host-key-regenerated")
        passed("protected-aot-key-rejection-without-regeneration")
    bootstrap(plan, "readiness", identity=identity)
    run(["/usr/bin/unshare", "--mount", "--propagation", "private", "/usr/bin/python3", "-I", ROOT / "guest.py",
         "--phase", "unsupported-host"], timeout=100)
    passed("protected-credentials-unsupported-profile-and-failed-authenticated-readiness")


def unsupported_host(plan):
    require(os.geteuid() == 0, "private-host-probe-namespace-requires-test-controller-root")
    fake = ROOT / "unsupported-os-release"
    fake.write_bytes(b'ID=unsupported-native-test\nVERSION_ID="0"\n')
    fake.chmod(0o644)
    run(["/usr/bin/mount", "--bind", fake, "/usr/lib/os-release"])
    status, result = bootstrap(plan, "preflight", codes=None, identity=service_identity())
    require(status != 0 and result.get("diagnostic") == "supported-distribution-is-ubuntu-24.04", "unsupported-host-not-rejected-by-real-probe")
    passed("real-host-probe-refuses-unsupported-os-in-private-mount-namespace")


def initial(plan):
    require(os.geteuid() == 0 and Path("/proc/1/comm").read_text().strip() == "systemd", "clean-systemd-vm-required")
    for program in ("cargo", "rustc", "wasm-tools", "gcc", "clang", "docker", "podman", "kubectl"):
        require(shutil.which(program) is None, "guest-must-not-have-build-or-container-toolchain")
    require(all(not path.exists() for path in (PREFIX, CONFIG, Path("/var/lib/lsf"), Path("/var/cache/lsf"))), "fresh-native-vm-required")
    verified = authenticate(plan, negatives=True)
    outside = ROOT / "outside"
    outside.mkdir(mode=0o700)
    (outside / "sentinel").write_bytes(b"not-owned-by-installation")
    PREFIX.symlink_to(outside, target_is_directory=True)
    try:
        require(bootstrap(plan, "install", codes=None)[0] != 0, "symlink-installation-root-accepted")
    finally:
        PREFIX.unlink()
    require((outside / "sentinel").read_bytes() == b"not-owned-by-installation", "unsafe-path-touched-outside-file")
    passed("unsafe-installation-path-refused-without-outside-mutation")
    if plan["profile"] == "external-capsule-v1":
        missing = {key: item for key, item in plan.items() if key != "admissionPolicy"}
        require(bootstrap(missing, "install", codes=None)[0] != 0, "external-profile-without-trust-accepted")
        key_digest = digest(CONFIG / "private/native-aot.key")
        result = bootstrap(plan, "install", "--resume", "--start", "--enable")[1]
        require(digest(CONFIG / "private/native-aot.key") == key_digest, "resume-regenerated-host-key")
        passed("interrupted-unactivated-external-install-resumes-with-same-key")
    else:
        result = bootstrap(plan, "install", "--start", "--enable")[1]
    require(result["activationReady"] is True and systemctl("is-enabled", "lsf.service") == "enabled", "service-not-ready-or-enabled")
    process_id = int(systemctl("show", "lsf.service", "--property=MainPID", "--value"))
    status = Path(f"/proc/{process_id}/status").read_text()
    require(f"Uid:\t{service_identity()[0]}\t" in status, "runtime-runs-as-wrong-user")
    for name in ("latent", "latentd", "latent-aot-compiler"):
        binary = PREFIX / "current/bin" / name
        require(binary.stat().st_uid == 0 and not binary.stat().st_mode & 0o022, "runtime-binary-not-root-protected")
        require(run(["/usr/bin/test", "-w", binary], codes=None, identity=service_identity())[0] == 1, "service-can-write-native-binary")
    listeners = run(["/usr/bin/ss", "-ltnH"])[1]
    require(b"127.0.0.1:50051" in listeners and b"0.0.0.0:50051" not in listeners and b"[::]:50051" not in listeners,
            "native-management-listener-not-loopback-only")
    retained = publish(plan)
    group = systemctl("show", "lsf.service", "--property=ControlGroup", "--value")
    require(group.startswith("/system.slice/lsf.service"), "node-not-owned-by-systemd-unit-cgroup")
    processes = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and set(processes.read_text().split()) != {str(process_id)}:
        time.sleep(0.1)
    require(set(processes.read_text().split()) == {str(process_id)}, "compiler-child-not-reaped-after-preparation")
    passed("root-protected-native-binaries-loopback-management-and-reaped-compiler-children")
    protected = protected_hashes()
    negative_configuration(plan)
    bootstrap(plan, "install", "--start")
    require(protected_hashes() == protected and int(systemctl("show", "lsf.service", "--property=MainPID", "--value")) == process_id,
            "same-version-reinstall-changed-credentials-or-restarted-node")
    invoke(plan, retained, "same-version")
    passed("same-version-configuration-key-credential-and-process-preservation")
    write(STATE, {"installationId": result["installationId"], "retained": retained, "protected": protected,
                  "bootId": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  "invocationId": systemctl("show", "lsf.service", "--property=InvocationID", "--value"),
                  "archiveSha256": verified["archiveSha256"], "sourceCommit": plan["sourceCommit"]})
    passed("non-root-systemd-node-enabled-for-real-reboot")


def retained(plan):
    state = value(STATE)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    require(boot != state["bootId"], "actual-guest-reboot-required")
    bootstrap(plan, "readiness", identity=service_identity())
    clean_stop(state["invocationId"])
    require(protected_hashes() == state["protected"], "reboot-changed-protected-configuration")
    invoke(plan, state["retained"], "after-real-reboot")
    passed("actual-changed-boot-id-and-retained-deployment")
    clean_stop()
    backup_and_restore(plan, "retained-backup")
    time.sleep(6)
    systemctl("start", "lsf.service")
    bootstrap(plan, "readiness", identity=service_identity())
    invoke(plan, state["retained"], "after-clean-stop")
    removed = bootstrap(plan, "remove")[1]
    require(removed["configurationAndDataRetained"] is True and protected_hashes() == state["protected"], "removal-lost-protected-data")
    require(not (PREFIX / "current").exists() and not Path("/etc/systemd/system/lsf.service").exists(), "removal-retained-runtime-or-unit")
    time.sleep(6)
    bootstrap(plan, "install", "--start", "--enable")
    require(protected_hashes() == state["protected"], "reinstall-lost-config-credentials-or-key")
    invoke(plan, state["retained"], "after-remove-reinstall")
    passed("remove-retain-reinstall-recovers-exact-publication")
    clean_stop()
    bootstrap(plan, "remove")
    require(bootstrap(plan, "purge", "--confirm-installation", "0" * 32, codes=None)[0] != 0, "purge-without-exact-id-accepted")
    substitution = Path("/var/lib/lsf") / "unsafe-substitution"
    substitution.symlink_to(ROOT / "outside/sentinel")
    require(bootstrap(plan, "purge", "--confirm-installation", state["installationId"], codes=None)[0] != 0, "purge-followed-symlink")
    substitution.unlink()
    bootstrap(plan, "purge", "--confirm-installation", state["installationId"])
    require(all(not path.exists() for path in (CONFIG, Path("/var/lib/lsf"), Path("/var/cache/lsf")))
            and (ROOT / "outside/sentinel").read_bytes() == b"not-owned-by-installation", "purge-boundary")
    passed("separate-purge-validates-id-and-paths-and-resumes-without-outside-deletion")


def upgrade(plan):
    require("predecessor" in plan, "approved-native-predecessor-required")
    previous = plan["predecessor"]
    authenticate(previous)
    bootstrap(previous, "install", "--start", "--enable")
    retained = publish(previous)
    original = protected_hashes()
    original_node = value(CONFIG / "node.json")
    next_plan = {**plan}
    if plan["profile"] == "external-capsule-v1":
        next_plan["admissionPolicy"] = previous["admissionPolicy"]
    require(bootstrap(next_plan, "install", codes=None)[0] != 0, "cross-version-install-without-explicit-upgrade-accepted")
    require(protected_hashes() == original and not (PREFIX / "transaction.json").exists(), "rejected-upgrade-mutated-protected-state")
    clean_stop()
    backup_and_restore(previous, "pre-upgrade-backup")
    time.sleep(6)
    systemctl("start", "lsf.service")
    target = value(Path(plan["releaseDirectory"]) / "release.json")
    flags = ["--upgrade", "--start"]
    if plan["profile"] == "external-capsule-v1":
        flags += ["--approve-compiler-sha256", target["engine"]["compilerSha256"]]
    result = bootstrap(next_plan, "install", *flags)[1]
    require(result["version"] == plan["version"] and result["activationReady"] is True, "compatible-upgrade-not-activated")
    after = value(CONFIG / "node.json")
    if plan["profile"] == "external-capsule-v1":
        require(after["isolatedAot"]["compilerDigest"] == "sha256:" + target["engine"]["compilerSha256"], "approved-compiler-identity-not-installed")
        after["isolatedAot"]["compilerDigest"] = original_node["isolatedAot"]["compilerDigest"]
    require(after == original_node and all(digest(CONFIG / name) == checksum for name, checksum in original.items() if name != "node.json"),
            "upgrade-changed-unapproved-config-credentials-key-or-policy")
    require(systemctl("is-enabled", "lsf.service") == "enabled", "upgrade-lost-existing-boot-enablement")
    invoke(plan, retained, "after-compatible-upgrade")
    retained_hashes = protected_hashes()
    status, denied = bootstrap(previous, "install", "--upgrade", codes=None)
    require(status != 0 and denied.get("diagnostic") == "unsupported-upgrade-or-downgrade-no-files-changed", "unsupported-downgrade-not-rejected")
    require(protected_hashes() == retained_hashes and not (PREFIX / "transaction.json").exists(), "unsupported-downgrade-mutated-installed-state")
    invoke(plan, retained, "after-unsupported-downgrade-rejection")
    passed("declared-authenticated-native-version-upgrade-and-unsupported-downgrade-refusal")
    DETAILS["upgrade"] = {"fromVersion": previous["version"], "fromCommit": previous["sourceCommit"],
                          "toVersion": plan["version"], "toCommit": plan["sourceCommit"], "retained": retained,
                          "onlyApprovedCompilerDigestChanged": True, "unsupportedDowngradeRejected": True}
    clean_stop()
    bootstrap(plan, "remove")
    bootstrap(plan, "purge", "--confirm-installation", result["installationId"])


def rootless(plan):
    require(os.geteuid() != 0 and not CONFIG.exists(), "actual-rootless-identity-required")
    plan = {**plan, "profile": "local-experimental-v1", "localDirectory": str(Path.home() / "lsf-evaluation")}
    authenticate(plan)
    bootstrap(plan, "install", "--port", "50052")
    directory = Path(plan["localDirectory"])
    protected = protected_hashes(directory / "config")
    process = subprocess.Popen(["/usr/bin/python3", "-I", plan["releaseDirectory"] + "/lsf-install.pyz",
                                "run-local", "--directory", str(directory)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                               env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(Path.home())})
    captured = bytearray()
    overflow = threading.Event()

    def drain():
        while data := process.stdout.read(4096):
            if len(captured) + len(data) > 262144:
                overflow.set()
                os.killpg(process.pid, signal.SIGKILL)
                return
            captured.extend(data)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        bootstrap(plan, "readiness")
        publish(plan)
        require(bootstrap(plan, "remove", codes=None)[0] != 0, "rootless-live-mutation-not-serialized")
        os.killpg(process.pid, signal.SIGTERM)
        require(process.wait(timeout=90) == 0, "rootless-unclean-exit")
        reader.join(timeout=5)
        require(not reader.is_alive() and not overflow.is_set(), "rootless-output-owner-not-drained")
        records = [json.loads(line) for line in captured.splitlines() if line.startswith(b"{")]
        require(any(record.get("event") == "stopped" and record.get("clean") is True for record in records), "rootless-clean-shutdown-missing")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()
    require(protected_hashes(directory / "config") == protected and not CONFIG.exists()
            and not Path("/etc/systemd/system/lsf.service").exists(), "rootless-modified-system-or-credentials")
    bootstrap(plan, "remove")
    installation = bootstrap(plan, "status")[1]["installationId"]
    bootstrap(plan, "purge", "--confirm-installation", installation)
    passed("actual-unprivileged-foreground-no-systemd-serialization-and-clean-shutdown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("initial", "retained", "rootless", "upgrade", "unsupported-host"))
    arguments = parser.parse_args()
    os.umask(0o077)
    report = {"schemaVersion": "latent.native-vm-guest.v1", "phase": arguments.phase, "passed": False, "checks": CHECKS, "details": DETAILS}
    try:
        plan = value(PLAN)
        if arguments.phase == "initial":
            initial(plan)
        else:
            authenticate(plan)
            {"retained": retained, "rootless": rootless, "upgrade": upgrade, "unsupported-host": unsupported_host}[arguments.phase](plan)
        report.update({"passed": True, "profile": plan["profile"], "sourceCommit": plan["sourceCommit"],
                       "kernel": os.uname().release, "python": sys.version.split()[0], "uid": os.geteuid(),
                       "bootId": Path("/proc/sys/kernel/random/boot_id").read_text().strip()})
        if STATE.exists() and os.geteuid() == 0:
            state = value(STATE)
            report.update({"archiveSha256": state["archiveSha256"], "retained": state["retained"]})
    except (Failure, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        report.update({"diagnostic": str(error) if isinstance(error, Failure) else "guest-prerequisite-or-contract-failure", "lastCommand": LAST})
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

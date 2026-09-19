#!/usr/bin/env python3
"""Boot a pinned clean QEMU guest and test only authenticated packaged binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_runtime import files, verify
from tools.native_runtime.common import InstallError, document, encode, execute, require

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "tools/native-vm-profile.json"


def checked(command, *, timeout=60, maximum=262144, codes=(0,)):
    status, output = execute([str(part) for part in command], timeout=timeout, maximum=maximum,
                             environment={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": os.environ["HOME"]})
    require(status in codes, "vm-controller-command-failed-" + Path(str(command[0])).name)
    return output


def download(profile, root):
    target = root / "ubuntu.qcow2"
    expected = profile["imageSha256"]
    require(verify.SHA256.fullmatch(expected) and profile["imageUrl"].startswith("https://cloud-images.ubuntu.com/noble/"),
            "reviewed-vm-image-required")
    checksum = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + 180
    with urllib.request.urlopen(profile["imageUrl"], timeout=30) as response, target.open("xb") as output:
        require(response.url == profile["imageUrl"], "vm-image-unexpected-redirect")
        while block := response.read(1_048_576):
            total += len(block)
            require(total <= profile["maximumImageBytes"] and time.monotonic() < deadline, "vm-image-download-bound")
            checksum.update(block)
            output.write(block)
    require(checksum.hexdigest() == expected, "vm-image-digest-mismatch")
    info = document(checked(["qemu-img", "info", "--output=json", target]))
    require(info["format"] == "qcow2" and "backing-filename" not in info, "self-contained-qcow2-image-required")
    return target


class Guest:
    def __init__(self, root, profile, image):
        self.root = root
        self.profile = profile
        self.process = None
        self.port = None
        self.acceleration = "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg"
        self.key = root / "client-ed25519"
        self.host_key = root / "host-ed25519"
        self.serial = root / "serial.log"
        self.diagnostic = None
        for path in (self.key, self.host_key):
            checked(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", path])
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        files.create(root / "known_hosts", f"[127.0.0.1]:{self.port} ".encode() + files.read(self.host_key.with_suffix(".pub")))
        cloud = {"hostname": "lsf-native-test", "manage_etc_hosts": True, "ssh_pwauth": False, "disable_root": True,
                 "users": [{"name": "lsf-test", "lock_passwd": True, "shell": "/bin/bash",
                            "sudo": ["ALL=(ALL) NOPASSWD:ALL"], "ssh_authorized_keys": [self.key.with_suffix(".pub").read_text().strip()]}],
                 "ssh_keys": {"ed25519_private": self.host_key.read_text(), "ed25519_public": self.host_key.with_suffix(".pub").read_text().strip()},
                 "runcmd": [["mkdir", "-p", "/var/log/journal"], ["systemctl", "restart", "systemd-journald"],
                            ["systemctl", "enable", "ssh"]]}
        files.create(root / "user-data", b"#cloud-config\n" + encode(cloud))
        files.create(root / "meta-data", encode({"instance-id": "lsf-native-" + str(self.port), "local-hostname": "lsf-native-test"}))
        files.create(root / "network-data", encode({"version": 2, "ethernets": {"primary": {
            "match": {"macaddress": "52:54:00:30:80:01"}, "dhcp4": True}}}))
        checked(["cloud-localds", "--network-config", root / "network-data", root / "seed.img", root / "user-data", root / "meta-data"])
        checked(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", image,
                 root / "guest.qcow2", str(profile["diskGiB"]) + "G"])

    def start(self):
        command = ["qemu-system-x86_64", "-machine", "q35", "-accel", self.acceleration,
                   "-cpu", "host" if self.acceleration == "kvm" else "max", "-m", str(self.profile["memoryMiB"]),
                   "-smp", str(self.profile["processors"]), "-display", "none", "-monitor", "none",
                   "-serial", "file:" + str(self.serial), "-drive", f"file={self.root / 'guest.qcow2'},if=virtio,format=qcow2",
                   "-drive", f"file={self.root / 'seed.img'},if=virtio,format=raw,readonly=on",
                   "-netdev", f"user,id=native,restrict=on,hostfwd=tcp:127.0.0.1:{self.port}-:22",
                   "-device", "virtio-net-pci,netdev=native,mac=52:54:00:30:80:01"]
        self.diagnostic = (self.root / "qemu.log").open("xb")
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self.diagnostic,
                                        stderr=subprocess.STDOUT, start_new_session=True)

    def options(self):
        return ["-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
                "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(self.root / "known_hosts"),
                "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2", "-i", str(self.key)]

    def ssh(self, command, *, timeout=60, codes=(0,), maximum=262144):
        return checked(["ssh", *self.options(), "-p", str(self.port), "lsf-test@127.0.0.1", shlex.join([str(part) for part in command])],
                       timeout=timeout, codes=codes, maximum=maximum)

    def ready(self, old_boot=None):
        deadline = time.monotonic() + self.profile["bootTimeoutSeconds"]
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "owned-qemu-exited-before-guest-ready")
            output = self.ssh(["cat", "/proc/sys/kernel/random/boot_id"], codes=(0, 255), timeout=10).decode().strip()
            if re.fullmatch(r"[0-9a-f-]{36}", output) and (old_boot is None or output != old_boot):
                self.ssh(["sudo", "cloud-init", "status", "--wait"], timeout=90)
                return output
            time.sleep(2)
        require(False, "guest-boot-or-real-reboot-timeout")

    def copy(self, source, destination):
        checked(["scp", *self.options(), "-P", str(self.port), source, "lsf-test@127.0.0.1:" + destination], timeout=120)

    def close(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
            except ProcessLookupError:
                self.process.wait(timeout=5)
        if self.diagnostic is not None:
            self.diagnostic.close()


def provision(guest, args, policy, root, report):
    release = args.release_directory
    metadata = document(files.read(release / "release.json"))
    trust = verify.PublisherTrust(policy, args.trusted_root, args.verifier, args.purpose == "candidate")
    with verify.release(release, args.version, trust) as verified:
        report["archiveSha256"] = verified.metadata["archive"]["sha256"]
        report["authentication"] = verified.authentication
    guest.ssh(["sudo", "install", "-d", "-m", "0755", "/opt/lsf-native-test", "/opt/lsf-native-test/release", "/opt/lsf-verification"])
    guest.ssh(["install", "-d", "-m", "0700", "/home/lsf-test/provision"])
    inputs = [(release / name, "/opt/lsf-native-test/release/" + name, "0644") for name in
              (metadata["archive"]["name"], "release.json", "lsf-install.pyz", "SHA256SUMS", "SHA256SUMS.sigstore.json")]
    inputs += [(args.verifier, "/opt/lsf-verification/gh", "0755"),
               (args.trusted_root, "/opt/lsf-verification/trusted_root.jsonl", "0644"),
               (policy, "/opt/lsf-verification/policy.json", "0644"),
               (ROOT / "tools/native_vm_guest.py", "/opt/lsf-native-test/guest.py", "0644")]
    plan = {"version": args.version, "sourceCommit": args.commit, "sourceRef": args.source_ref,
            "profile": args.profile, "purpose": args.purpose, "releaseDirectory": "/opt/lsf-native-test/release",
            "publisherPolicy": "/opt/lsf-verification/policy.json", "trustedRoot": "/opt/lsf-verification/trusted_root.jsonl",
            "verifier": "/opt/lsf-verification/gh"}
    if args.profile == "external-capsule-v1":
        require(args.fixture_directory is not None, "independently-provisioned-fresh-example-test-trust-required")
        fixture = args.fixture_directory
        count = 0
        for directory, directories, filenames in os.walk(fixture):
            require(len(Path(directory).relative_to(fixture).parts) <= 8, "test-fixture-depth")
            for name in directories:
                require(not (Path(directory) / name).is_symlink(), "test-fixture-symlink")
            for name in filenames:
                count += 1
                path = Path(directory) / name
                require(count <= 128 and not path.is_symlink() and path.stat().st_size <= 16_777_216, "test-fixture-file-limit")
                relative = path.relative_to(fixture).as_posix()
                verify.relative(relative)
                destination = "/opt/lsf-verification/admission/" + relative
                guest.ssh(["sudo", "install", "-d", "-m", "0755", str(Path(destination).parent)])
                inputs.append((path, destination, "0644"))
        plan.update({"admissionPolicy": "/opt/lsf-verification/admission/policy.json",
                     "packageDirectory": "/opt/lsf-verification/admission/package",
                     "packageEvidence": "/opt/lsf-verification/admission/evidence/index.json"})
    files.create(root / "plan.json", encode(plan))
    inputs.append((root / "plan.json", "/opt/lsf-native-test/plan.json", "0644"))
    for ordinal, (source, destination, mode) in enumerate(inputs):
        temporary = "/home/lsf-test/provision/input-" + str(ordinal)
        guest.copy(source, temporary)
        guest.ssh(["sudo", "install", "-o", "root", "-g", "root", "-m", mode, temporary, destination])
        guest.ssh(["rm", "--", temporary])
    report["guestPrerequisites"] = {"ghSha256": files.digest(args.verifier), "ghTrustedBeforeBundle": True,
                                    "noGuestPackageInstallation": True, "sshHostKeyPinnedBeforeBoot": True,
                                    "network": guest.profile["network"]}


def run(args):
    require(sys.platform == "linux" and verify.SOURCE.fullmatch(args.commit), "native-linux-exact-source-vm-controller-required")
    profile = document(files.read(PROFILE))
    require(args.output.is_relative_to(ROOT / "target") and not args.output.exists(), "new-owned-vm-receipt-path-required")
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    policy = verify.publisher_policy({"schemaVersion": "latent.native-publisher-policy.v1", "repository": verify.REPOSITORY,
                                      "workflow": verify.RELEASE_WORKFLOW if args.purpose == "release" else verify.CANDIDATE_WORKFLOW,
                                      "sourceRef": args.source_ref, "sourceCommit": args.commit, "version": args.version,
                                      "purpose": args.purpose}, args.version, args.purpose == "candidate")
    report = {"schemaVersion": "latent.native-vm-result.v1", "passed": False, "acceptanceComplete": False,
              "sourceCommit": args.commit, "version": args.version, "profile": args.profile, "purpose": args.purpose,
              "image": {key: profile[key] for key in ("imageUrl", "imageSha256", "distribution", "architecture")},
              "guestResults": [], "gaps": ["declared-compatible-native-version-pair-not-yet-selected"]}
    guest = None
    try:
        with tempfile.TemporaryDirectory(prefix="native-vm-", dir=ROOT / "target") as temporary:
            root = Path(temporary)
            files.create(root / "publisher-policy.json", encode(policy))
            image = download(profile, root)
            guest = Guest(root, profile, image)
            report["acceleration"] = guest.acceleration
            report["hostKernel"] = os.uname().release
            try:
                guest.start()
                boot = guest.ready()
                report["initialBootId"] = boot
                provision(guest, args, root / "publisher-policy.json", root, report)

                def phase(name, user="root"):
                    result = document(guest.ssh(["sudo", "-H", "-u", user, "/usr/bin/python3", "-I",
                                                  "/opt/lsf-native-test/guest.py", "--phase", name],
                                                 timeout=profile["scenarioTimeoutSeconds"], codes=(0, 1), maximum=262144))
                    report["guestResults"].append(result)
                    require(result.get("passed") is True, "packaged-native-guest-phase-failed-" + name)

                phase("initial")
                guest.ssh(["sudo", "systemctl", "reboot", "--no-block"], codes=(0, 255), timeout=15)
                report["rebootedBootId"] = guest.ready(old_boot=boot)
                phase("retained")
                if args.profile == "local-experimental-v1":
                    phase("rootless", "lsf-test")
                report["passed"] = True
            finally:
                guest.close()
                if guest.serial.exists():
                    with guest.serial.open("rb") as source:
                        source.seek(max(0, guest.serial.stat().st_size - 16384))
                        serial = source.read(16384).decode(errors="replace")
                    public_lines = [line for line in serial.splitlines() if re.match(r"^\[[ 0-9.]+\]", line)]
                    report["bootKernelDiagnostics"] = public_lines[-24:]
    except (InstallError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        report["diagnostic"] = str(error) if isinstance(error, InstallError) else "vm-prerequisite-or-input-failure"
    files.create(args.output, encode(report))
    print(json.dumps({"passed": report["passed"], "acceptanceComplete": report["acceptanceComplete"],
                      "profile": args.profile, "receipt": str(args.output), "diagnostic": report.get("diagnostic")}))
    return 0 if report["passed"] and not args.require_upgrade else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release-directory", "trusted-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--verifier", type=Path, default=Path("/usr/bin/gh"))
    parser.add_argument("--fixture-directory", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--purpose", choices=("release", "candidate"), required=True)
    parser.add_argument("--profile", choices=("local-experimental-v1", "external-capsule-v1"), required=True)
    parser.add_argument("--require-upgrade", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

"""Execute CI's real objcopy/identity handoff on tiny ELFs, without Rust or a node."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
RUSTC_VERSION = "rustc 1.97.1 (8bab26f4f 2026-07-14)"


def resource_commands():
    """Read the actual maintained run block, not a second copy of its commands."""
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    step = text.split("      - name: Validate bounded Phase 2 delivery and resource workflows\n", 1)[1]
    step = step.split("      - name: Retain compact Phase 2 gate receipts\n", 1)[0]
    script = "\n".join(line[10:] for line in step.splitlines() if line.startswith(" " * 10))
    staging = script[script.index('resource_bin='):script.index('LSF_PHASE2_RESOURCE_FIXTURE_ROOT=')]
    start = script.index('LSF_GATE_FIXTURE_ROOT=')
    identity = script[start:script.index("\nPY\n", start) + 4]
    launch = next(line for line in script.splitlines()
                  if line.startswith("python3 tools/phase2_gate_resource.py --cli "))
    return staging, identity, launch


def digest(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(sys.platform == "linux" and all(shutil.which(tool) for tool in
                     ("bash", "cc", "objcopy", "readelf", "python3")),
                     "requires the Linux CI binary utilities")
class ResourceBinaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lsf-resource-binaries-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace with spaces"
        self.target = self.root / "target/debug"
        self.target.mkdir(parents=True)
        self.fixture = self.root / "fixture with spaces"
        self.fixture.mkdir()
        (self.root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
        source = self.root / "fixture.c"
        source.write_text('#include <stdio.h>\nint main(void) { puts(NAME); return 0; }\n',
                          encoding="utf-8")
        self.original = {}
        for index, name in enumerate(("latent", "latentd"), 1):
            executable = self.target / name
            self.command(["cc", "-g", "-O0", f'-DNAME="{name}"', str(source), "-o", str(executable)])
            # Guarantee a meaningful size difference without allocating a giant
            # debug binary or increasing the real profile's executable ceiling.
            padding = self.root / f"{name}.debug"
            padding.write_bytes(bytes([index]) * (65536 * index))
            padded = self.root / f"{name}.padded"
            self.command(["objcopy", "--add-section", f".debug_lsf_fixture={padding}",
                          str(executable), str(padded)])
            padded.replace(executable)
            os.link(executable, self.target / f"{name}.hardlink")
            stat = executable.stat()
            self.original[name] = (executable.read_bytes(), stat.st_ino, stat.st_mtime_ns)
        # Only the compiler-version observation is substituted; objcopy, the
        # workflow's hashing code and both output executables are real.
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        rustc = bin_dir / "rustc"
        rustc.write_text(f"#!/bin/sh\nprintf '%s\\n' '{RUSTC_VERSION}'\n", encoding="utf-8")
        rustc.chmod(0o700)
        self.env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                        fixture_root=str(self.fixture), GITHUB_SHA=REVISION,
                        RUNNER_TEMP=str(self.root))

    def command(self, args, **kwargs):
        return subprocess.run(args, check=True, capture_output=True, timeout=15, **kwargs)

    def run_workflow(self, prefix=""):
        staging, identity, launch = resource_commands()
        # Record the real shell-expanded gate arguments without starting LSF.
        record = 'python3() { printf "%s\\0" "$@" > "$fixture_root/gate-args"; }\n'
        return subprocess.run(["bash", "--noprofile", "--norc", "-e", "-u", "-o", "pipefail", "-c",
                               prefix + staging + identity + record + launch], cwd=self.root,
                              env=self.env, capture_output=True, timeout=15)

    def assert_source_unchanged(self):
        for name, (data, inode, mtime) in self.original.items():
            for path in (self.target / name, self.target / f"{name}.hardlink"):
                stat = path.stat()
                self.assertEqual((path.read_bytes(), stat.st_ino, stat.st_mtime_ns),
                                 (data, inode, mtime))

    def assert_no_handoff(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.fixture / "build.json").exists())
        self.assertFalse((self.fixture / "gate-args").exists())

    def test_runtime_copies_identity_and_gate_arguments_agree_without_mutating_cargo(self):
        result = self.run_workflow()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        identity = json.loads((self.fixture / "build.json").read_text())
        self.assertEqual(set(identity), {"schemaVersion", "sourceRevision", "cargoLockSha256",
                                        "cliSha256", "nodeSha256", "rustcVersion", "buildProfile"})
        self.assertEqual(identity["schemaVersion"], "latent.phase2.resource-build.v1")
        self.assertEqual(identity["sourceRevision"], REVISION)
        self.assertEqual(identity["rustcVersion"], RUSTC_VERSION)
        self.assertEqual(identity["buildProfile"], "debug")
        self.assertEqual(identity["cargoLockSha256"], digest(self.root / "Cargo.lock"))
        arguments = (self.fixture / "gate-args").read_bytes().split(b"\0")[:-1]
        arguments = [value.decode() for value in arguments]
        self.assertEqual(arguments[0], "tools/phase2_gate_resource.py")
        self.assertEqual(arguments[1::2], ["--cli", "--node", "--fixture-root",
                                          "--build-identity", "--output"])
        for name, field, flag in (("latent", "cliSha256", "--cli"),
                                   ("latentd", "nodeSha256", "--node")):
            staged = self.fixture / "resource-bin" / name
            self.assertEqual(arguments[arguments.index(flag) + 1], str(staged))
            self.assertEqual(identity[field], digest(staged))
            self.assertNotEqual(identity[field], digest(self.target / name))
            self.assertNotEqual(staged.stat().st_ino, self.original[name][1])
            self.assertLess(staged.stat().st_size, len(self.original[name][0]))
            self.assertTrue(os.access(staged, os.X_OK))
            self.assertEqual(self.command([str(staged)]).stdout, (name + "\n").encode())
            sections = self.command(["readelf", "--sections", "--wide", str(staged)]).stdout
            self.assertNotIn(b".debug_", sections)
        self.assertEqual(arguments[arguments.index("--build-identity") + 1],
                         str(self.fixture / "build.json"))
        self.assert_source_unchanged()

    def test_invalid_cli_stops_before_identity_or_probe(self):
        (self.target / "latent").write_bytes(b"not an ELF")
        self.assert_no_handoff(self.run_workflow())
        self.assertEqual((self.target / "latentd").read_bytes(), self.original["latentd"][0])

    def test_invalid_node_never_falls_back_after_cli_copy_succeeds(self):
        (self.target / "latentd").write_bytes(b"not an ELF")
        self.assert_no_handoff(self.run_workflow())
        self.assertTrue((self.fixture / "resource-bin/latent").is_file())
        self.assertEqual((self.target / "latent").read_bytes(), self.original["latent"][0])

    def test_existing_output_is_not_overwritten(self):
        output = self.fixture / "resource-bin"
        output.mkdir()
        sentinel = output / "latent"
        sentinel.write_bytes(b"previous owner")
        self.assert_no_handoff(self.run_workflow())
        self.assertEqual(sentinel.read_bytes(), b"previous owner")
        self.assert_source_unchanged()

    def test_unavailable_objcopy_is_not_ignored(self):
        self.assert_no_handoff(self.run_workflow("objcopy() { return 127; }\n"))
        self.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()

"""Fast native packaging and installer safety tests; synthetic binaries, not VM evidence."""

from __future__ import annotations

from contextlib import contextmanager
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.native_runtime import archive, configuration, files, lifecycle, verify
from tools.native_runtime.common import InstallError, document, encode, execute
from tools.native_runtime.layout import Layout
from tools.native_runtime_build import bootstrap

ROOT = Path(__file__).resolve().parents[2]
LINUX = sys.platform == "linux"
UNPRIVILEGED = LINUX and os.geteuid() != 0


def fixture(version: str = "0.1.0-test.1") -> tuple[dict, bytes]:
    payloads = {name: b"synthetic-not-an-executable\n" for name in verify.REQUIRED}
    payloads["systemd/lsf.service"] = (ROOT / "packaging/linux/lsf.service").read_bytes()
    inventory = [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                  "mode": 0o755 if name.startswith("bin/") else 0o644} for name, data in sorted(payloads.items())]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as output:
        for entry in inventory:
            header = tarfile.TarInfo(entry["path"])
            header.size = entry["size"]
            header.mode = entry["mode"]
            output.addfile(header, io.BytesIO(payloads[entry["path"]]))
    compressed = gzip.compress(raw.getvalue(), mtime=0)
    executable = hashlib.sha256(payloads["bin/latent-aot-compiler"]).hexdigest()
    metadata = {"schemaVersion": "latent.native-release.v1", "version": version, "sourceCommit": "a" * 40,
                "target": verify.TARGET, "toolchain": {"rust": "1.97.1", "lockSha256": "b" * 64},
                "engine": {"wasmtimeVersion": "47.0.4", "hostAbiProfile": "lsf-host-abi-phase3-v4",
                           "compilerSha256": executable, "dynamicDependencies": ["libc.so.6"]},
                "platform": dict(verify.PLATFORM),
                "compatibility": {"installerFormat": 1, "nodeConfigFormat": 1, "migration": "none", "upgradeFrom": []},
                "archive": {"name": f"lsf-{version}-{verify.TARGET}.tar.gz", "size": len(compressed),
                            "sha256": hashlib.sha256(compressed).hexdigest()},
                "bootstrap": {"name": "lsf-install.pyz", "size": len(payloads["lsf-install.pyz"]),
                              "sha256": hashlib.sha256(payloads["lsf-install.pyz"]).hexdigest()}, "files": inventory}
    return metadata, compressed


def policy_fixture(metadata: dict) -> dict:
    return {"schemaVersion": "latent.native-publisher-policy.v1", "repository": verify.REPOSITORY,
            "workflow": verify.RELEASE_WORKFLOW, "sourceRef": "refs/tags/" + metadata["version"],
            "sourceCommit": metadata["sourceCommit"], "version": metadata["version"], "purpose": "release"}


@contextmanager
def selected(root: Path, version: str = "0.1.0-test.1", previous: dict | None = None):
    metadata, payload = fixture(version)
    if previous:
        metadata["compatibility"]["upgradeFrom"] = [{"version": previous["version"], "sourceCommit": previous["sourceCommit"],
                                                    "archiveSha256": previous["archive"]["sha256"]}]
    path = root / metadata["archive"]["name"]
    path.write_bytes(payload)
    with path.open("rb") as stream:
        policy = policy_fixture(metadata)
        yield verify.VerifiedRelease(metadata, stream.fileno(), verify.publisher_id(policy), b"synthetic", b"synthetic",
                                     {"method": "synthetic-for-safety-test-only", "policy": policy})


class ManifestTests(unittest.TestCase):
    def test_vm_driver_uses_pinned_image_and_actual_reboot(self):
        profile = json.loads((ROOT / "tools/native-vm-profile.json").read_text())
        self.assertRegex(profile["imageSha256"], "^[0-9a-f]{64}$")
        self.assertIn("/20260911/", profile["imageUrl"])
        for name in ("run_native_vm.py", "native_vm_guest.py"):
            source = (ROOT / "tools" / name).read_text()
            compile(source, name, "exec")
            self.assertNotIn("StrictHostKeyChecking=no", source)
            self.assertNotIn("docker run", source)
        controller = (ROOT / "tools/run_native_vm.py").read_text()
        self.assertIn('"reboot", "--no-block"', controller)
        self.assertIn("old_boot=boot", controller)
        self.assertIn("restrict=on", controller)

    def test_exact_publisher_policy_and_no_implicit_candidate_trust(self):
        metadata, _payload = fixture()
        policy = policy_fixture(metadata)
        self.assertEqual(verify.publisher_policy(policy, metadata["version"]), policy)
        for name, replacement in (("repository", "attacker/latent-service-fabric"), ("sourceCommit", "development"),
                                   ("workflow", ".github/workflows/ci.yml"), ("sourceRef", "refs/heads/development"),
                                   ("purpose", "candidate"), ("version", "0.1.0-test.2")):
            with self.subTest(name=name), self.assertRaises(InstallError):
                verify.publisher_policy({**policy, name: replacement}, metadata["version"])
        candidate = {**policy, "purpose": "candidate", "workflow": verify.CANDIDATE_WORKFLOW,
                     "sourceRef": "refs/heads/feature/native"}
        with self.assertRaisesRegex(InstallError, "candidate-is-not-a-release"):
            verify.publisher_policy(candidate, metadata["version"])
        self.assertEqual(verify.publisher_policy(candidate, metadata["version"], True), candidate)
        self.assertNotEqual(verify.publisher_id(policy), verify.publisher_id(candidate))

    def test_offline_verification_pins_certificate_not_user_predicate_claims(self):
        metadata, _payload = fixture()
        policy = policy_fixture(metadata)
        command = verify.verification_command("/usr/bin/gh", Path("SHA256SUMS"), Path("bundle.json"),
                                               Path("separate-roots.jsonl"), policy)
        for name, expected in (("--bundle", "bundle.json"), ("--custom-trusted-root", "separate-roots.jsonl"),
                               ("--source-ref", policy["sourceRef"]), ("--source-digest", metadata["sourceCommit"]),
                               ("--signer-digest", metadata["sourceCommit"]), ("--repo", verify.REPOSITORY),
                               ("--cert-oidc-issuer", verify.ISSUER), ("--predicate-type", verify.PREDICATE)):
            self.assertEqual(command[command.index(name) + 1], expected)
        self.assertEqual(command[command.index("--cert-identity") + 1],
                         f"https://github.com/{verify.REPOSITORY}/{verify.RELEASE_WORKFLOW}@{policy['sourceRef']}")
        self.assertIn("--deny-self-hosted-runners", command)
        self.assertNotIn("--signer-workflow", command)

    def test_complete_fixture_inventory_and_exact_version(self):
        metadata, _payload = fixture()
        self.assertEqual(verify.manifest(metadata, metadata["version"]), metadata)
        with self.assertRaisesRegex(InstallError, "version-mismatch"):
            verify.manifest(metadata, "0.1.0-test.2")

    def test_duplicate_documents_and_oversized_inputs(self):
        for data in (b'{"version":1,"version":2}', b"[]", b"{", b"0" * 100):
            with self.subTest(data=data), self.assertRaises(InstallError):
                document(data, 32)

    def test_unsafe_paths_versions_and_file_modes(self):
        for name in ("../latent", "/latent", "bin//latent", "bin/../latent", "bin\\latent", "bin/.hidden", "bin/latent\n"):
            with self.subTest(name=name), self.assertRaises(InstallError):
                verify.relative(name)
        for name in ("development", "latest", "0.1/../../etc", "0.1.0\n"):
            with self.subTest(name=name), self.assertRaises(InstallError):
                verify.version(name)
        metadata, _payload = fixture()
        for mode in (0o777, 0o4755, 0o1777):
            value = copy.deepcopy(metadata)
            value["files"][0]["mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(InstallError):
                verify.manifest(value, value["version"])

    def test_missing_compiler_incompatible_platform_and_approval_mismatch(self):
        metadata, _payload = fixture()
        for key in ("compiler", "platform", "digest", "migration", "unknown"):
            value = copy.deepcopy(metadata)
            if key == "compiler":
                value["files"] = [entry for entry in value["files"] if entry["path"] != "bin/latent-aot-compiler"]
            elif key == "platform":
                value["platform"]["minimumKernel"] = "1.0"
            elif key == "digest":
                value["engine"]["compilerSha256"] = "d" * 64
            elif key == "migration":
                value["compatibility"]["migration"] = "automatic"
            else:
                value["unknown"] = True
            with self.subTest(key=key), self.assertRaises(InstallError):
                verify.manifest(value, value["version"])

    def test_zip_bootstrap_contains_only_runtime_modules(self):
        import zipfile
        first = bootstrap(ROOT, 1_700_000_000)
        self.assertEqual(first, bootstrap(ROOT, 1_700_000_000))
        with zipfile.ZipFile(io.BytesIO(first)) as zipped:
            self.assertIn("__main__.py", zipped.namelist())
            self.assertIn("native_runtime/verify.py", zipped.namelist())
            self.assertFalse(any("test" in name or "key" in name or "build" in name for name in zipped.namelist()))

    def test_systemd_retains_compiler_ownership_and_executable_mappings(self):
        unit = (ROOT / "packaging/linux/lsf.service").read_text()
        for value in ("User=lsf", "Group=lsf", "UMask=0077", "KillMode=mixed", "TimeoutStopSec=90s",
                      "NoNewPrivileges=yes", "readiness --system", "WorkingDirectory=/var/lib/lsf"):
            self.assertIn(value, unit)
        for value in ("MemoryDenyWriteExecute", "PrivateUsers", "SystemCallFilter", "docker", "podman"):
            self.assertNotIn(value, unit)


@unittest.skipUnless(LINUX, "Linux descriptor/permission boundary")
class FileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_single_link_protected_files_and_symlink_ancestors(self):
        leaf = self.root / "private"
        files.create(leaf, b"private")
        self.assertEqual(files.read(leaf, private=True, owners={0, os.geteuid()}), b"private")
        os.link(leaf, self.root / "hardlink")
        with self.assertRaises(InstallError):
            files.read(leaf)
        (self.root / "hardlink").unlink()
        (self.root / "link").symlink_to(leaf)
        with self.assertRaises(OSError):
            files.read(self.root / "link")
        (self.root / "directory-link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            files.read(self.root / "directory-link/private")
        leaf.chmod(0o644)
        with self.assertRaises(InstallError):
            files.read(leaf, private=True, owners={0, os.geteuid()})

    def test_directory_acl_mode_and_unexpected_types(self):
        self.root.chmod(0o777)
        with self.assertRaises(InstallError):
            with files.directory(self.root, {0, os.geteuid()}):
                pass
        self.root.chmod(0o700)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(InstallError):
            files.read(fifo)

    def test_serialized_lock_is_finite_and_not_replaceable(self):
        lock = self.root / "install.lock"
        with files.lock(lock):
            with self.assertRaisesRegex(InstallError, "busy"):
                with files.lock(lock, timeout=0):
                    pass
        lock.unlink()
        lock.symlink_to(self.root / "outside")
        with self.assertRaises(OSError):
            with files.lock(lock):
                pass

    def test_bounded_subprocess_timeout_and_output_are_reaped(self):
        with self.assertRaisesRegex(InstallError, "timeout"):
            execute([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
        with self.assertRaisesRegex(InstallError, "output-limit"):
            execute([sys.executable, "-c", "print('x' * 10000)"], maximum=128)
        status, output = execute([sys.executable, "-c", "print('bounded')"])
        self.assertEqual((status, output), (0, b"bounded\n"))
        status, output = execute([sys.executable, "-c", "import sys; print('diagnostic', file=sys.stderr); print('{}')"], stdout_only=True)
        self.assertEqual((status, output), (0, b"{}\n"))
        with self.assertRaisesRegex(InstallError, "output-limit"):
            execute([sys.executable, "-c", "import sys; print('x' * 10000, file=sys.stderr)"], stdout_only=True, maximum=128)

    def test_archive_exact_files_and_modes(self):
        with selected(self.root) as release:
            destination = self.root / "stage"
            destination.mkdir(mode=0o700)
            archive.extract(release.archive_fd, destination, release.metadata["files"])
            archive.check_tree(destination, release.metadata["files"])
            (destination / "untracked").write_bytes(b"extra")
            with self.assertRaisesRegex(InstallError, "untracked"):
                archive.check_tree(destination, release.metadata["files"])

    def test_archive_links_devices_traversal_duplicates_and_truncation(self):
        metadata, payload = fixture()
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.XHDTYPE):
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as output:
                member = tarfile.TarInfo("bin/latent")
                member.type = kind
                output.addfile(member)
            path = self.root / "malicious.gz"
            path.write_bytes(gzip.compress(raw.getvalue()))
            with tempfile.TemporaryDirectory(dir=self.root) as staging, path.open("rb") as source:
                with self.subTest(kind=kind), self.assertRaises(InstallError):
                    archive.extract(source.fileno(), Path(staging), metadata["files"])
        for replacement in (payload[:-16], gzip.compress(gzip.decompress(payload) + b"untracked")):
            path = self.root / "malicious.gz"
            path.write_bytes(replacement)
            with tempfile.TemporaryDirectory(dir=self.root) as staging, path.open("rb") as source:
                with self.assertRaises((InstallError, EOFError)):
                    archive.extract(source.fileno(), Path(staging), metadata["files"])

    def test_purge_does_not_follow_links_or_remove_foreign_target(self):
        outside = self.root / "outside"
        outside.write_bytes(b"retain")
        owned = self.root / "owned"
        owned.mkdir(mode=0o700)
        (owned / "substitution").symlink_to(outside)
        with self.assertRaisesRegex(InstallError, "unexpected-file-type"):
            files.remove_tree(owned)
        self.assertEqual(outside.read_bytes(), b"retain")


@unittest.skipUnless(LINUX, "Linux protected trust files; gh is mocked, real crypto runs in the VM gate")
class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        parent = Path(self.temporary.name)
        self.root = parent / "release"
        self.root.mkdir(mode=0o700)
        self.trust = verify.PublisherTrust(parent / "policy.json", parent / "trusted_root.jsonl", parent / "mock-gh")
        files.create(self.trust.roots, b"unit-test-root-not-real-sigstore-material")
        files.create(self.trust.verifier, b"not-an-executable-verification-is-mocked", 0o755)
        self.metadata, payload = fixture()
        files.create(self.trust.policy, encode(policy_fixture(self.metadata)))
        (self.root / self.metadata["archive"]["name"]).write_bytes(payload)
        (self.root / "lsf-install.pyz").write_bytes(b"synthetic-not-an-executable\n")
        (self.root / "release.json").write_bytes(encode(self.metadata))
        sums = "".join(files.digest(self.root / name) + "  " + name + "\n"
                       for name in sorted((self.metadata["archive"]["name"], "lsf-install.pyz", "release.json")))
        (self.root / "SHA256SUMS").write_text(sums)
        (self.root / "SHA256SUMS.sigstore.json").write_bytes(b"mock-attestation")
        self.verifier = patch("tools.native_runtime.verify.execute", side_effect=self.mock_verifier).start()
        self.addCleanup(patch.stopall)

    @staticmethod
    def mock_verifier(command, **options):
        if "--version" in command:
            return 0, b"gh version 2.96.0 (2026-07-02)\n"
        return 0, b"unit-test-verification-result"

    def test_each_attested_artifact_is_checked_after_verifier_success(self):
        with verify.release(self.root, self.metadata["version"], self.trust) as release:
            self.assertEqual(release.metadata, self.metadata)
            self.assertRegex(release.publisher, "^[0-9a-f]{64}$")
            self.assertEqual(release.authentication["policy"], policy_fixture(self.metadata))
        for name in ("release.json", "lsf-install.pyz", self.metadata["archive"]["name"]):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.subTest(name=name), self.assertRaises(InstallError):
                with verify.release(self.root, self.metadata["version"], self.trust):
                    pass
            path.write_bytes(original)

    def test_missing_attestation_wrong_version_and_writable_trust_are_rejected(self):
        with self.assertRaises(InstallError):
            with verify.release(self.root, "0.1.0-test.2", self.trust):
                pass
        self.trust.roots.chmod(0o666)
        with self.assertRaises(InstallError):
            with verify.release(self.root, self.metadata["version"], self.trust):
                pass
        self.trust.roots.chmod(0o644)
        (self.root / "SHA256SUMS.sigstore.json").unlink()
        with self.assertRaises(OSError):
            with verify.release(self.root, self.metadata["version"], self.trust):
                pass

    def test_verifier_failure_cannot_fall_back_to_checksum_only(self):
        self.verifier.side_effect = [(0, b"gh version 2.96.0\n"), (1, b"untrusted")]
        with self.assertRaisesRegex(InstallError, "publisher-attestation-rejected"):
            with verify.release(self.root, self.metadata["version"], self.trust):
                pass
        environment = self.verifier.call_args.kwargs["environment"]
        self.assertNotIn("GH_TOKEN", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertIn("--custom-trusted-root", self.verifier.call_args.args[0])
        self.assertIn("--bundle", self.verifier.call_args.args[0])

    def test_bundle_cannot_supply_its_own_publisher_trust(self):
        trust = verify.PublisherTrust(self.root / "policy.json", self.trust.roots, self.trust.verifier)
        with self.assertRaisesRegex(InstallError, "separately-from-bundle"):
            with verify.release(self.root, self.metadata["version"], trust):
                pass
        self.verifier.assert_not_called()


@unittest.skipUnless(UNPRIVILEGED, "actual unprivileged Linux filesystem; systemd is mocked explicitly")
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.layout = Layout.local(self.root / "evaluation")
        self.probe = patch("tools.native_runtime.lifecycle.child_check", return_value={"syntheticCheck": True}).start()
        self.addCleanup(patch.stopall)

    def install(self, release, **options):
        return lifecycle.install(self.layout, release, profile=configuration.LOCAL, acknowledge=True, **options)

    def test_repeat_install_retains_credentials_config_and_deployment_data(self):
        with selected(self.root) as release:
            first = self.install(release)
            node = self.layout.node.read_bytes()
            client = self.layout.client.read_bytes()
            (self.layout.data / "retained-deployment").write_bytes(b"catalog-placeholder")
            second = self.install(release)
            self.assertEqual(first["installationId"], second["installationId"])
            self.assertEqual(self.layout.node.read_bytes(), node)
            self.assertEqual(self.layout.client.read_bytes(), client)
            self.assertFalse(second["activationReady"])
            self.assertNotIn(json.loads(node)["credentials"][0]["token"], json.dumps(second))
            self.assertEqual(stat.S_IMODE(self.layout.client.stat().st_mode), 0o600)

    def test_profile_selection_and_untracked_existing_roots_are_not_adopted(self):
        with selected(self.root) as release:
            with self.assertRaisesRegex(InstallError, "acknowledgement"):
                lifecycle.install(self.layout, release, profile=configuration.LOCAL)
            self.layout.prefix.mkdir(mode=0o700)
            self.layout.data.mkdir(mode=0o700)
            with self.assertRaisesRegex(InstallError, "untracked"):
                self.install(release)

    def test_failure_remains_unactivated_and_requires_exact_resume(self):
        with selected(self.root) as release:
            self.probe.side_effect = InstallError("synthetic-preflight-failure")
            with self.assertRaisesRegex(InstallError, "preflight"):
                self.install(release)
            node = self.layout.node.read_bytes()
            self.assertTrue(self.layout.transaction.exists())
            self.assertFalse(self.layout.state.exists())
            self.probe.side_effect = None
            with self.assertRaisesRegex(InstallError, "interrupted"):
                self.install(release)
            self.install(release, resume=True)
            self.assertEqual(self.layout.node.read_bytes(), node)
            self.assertFalse(self.layout.transaction.exists())

    def test_unsupported_upgrade_is_refused_before_mutation_and_allowed_pair_is_exact(self):
        with selected(self.root) as first:
            self.install(first)
            state = self.layout.state.read_bytes()
            with selected(self.root, "0.1.0-test.2") as unsupported:
                with self.assertRaisesRegex(InstallError, "unsupported-upgrade"):
                    self.install(unsupported, upgrade=True)
                self.assertEqual(self.layout.state.read_bytes(), state)
                self.assertFalse(self.layout.transaction.exists())
            with selected(self.root, "0.1.0-test.2", first.metadata) as supported:
                self.install(supported, upgrade=True)
                self.assertEqual(lifecycle.read_state(self.layout)["currentVersion"], "0.1.0-test.2")
            with self.assertRaisesRegex(InstallError, "unsupported-upgrade"):
                self.install(first, upgrade=True)

    def test_removal_retention_reinstallation_and_explicit_purge(self):
        with selected(self.root) as release:
            installed = self.install(release)
            node = self.layout.node.read_bytes()
            deployment = self.layout.data / "retained-deployment"
            deployment.write_bytes(b"catalog-placeholder")
            with self.assertRaisesRegex(InstallError, "requires-removal"):
                lifecycle.remove(self.layout, purge=installed["installationId"])
            receipt = lifecycle.remove(self.layout)
            self.assertTrue(receipt["configurationAndDataRetained"])
            self.assertEqual(self.layout.node.read_bytes(), node)
            self.assertTrue(deployment.exists())
            self.install(release)
            self.assertTrue(deployment.exists())
            self.assertEqual(self.layout.node.read_bytes(), node)
            lifecycle.remove(self.layout)
            with self.assertRaises(InstallError):
                lifecycle.remove(self.layout, purge="not-this-installation")
            lifecycle.remove(self.layout, purge=installed["installationId"])
            self.assertTrue(all(not path.exists() for path in self.layout.roots().values()))
            self.assertEqual(lifecycle.read_state(self.layout)["status"], "purged")
            lifecycle.remove(self.layout, purge=installed["installationId"])
            replacement = self.install(release)
            self.assertNotEqual(replacement["installationId"], installed["installationId"])

    def test_interrupted_purge_finalization_keeps_a_resumable_tombstone(self):
        with selected(self.root) as release:
            installed = self.install(release)
            lifecycle.remove(self.layout)
            unlink = os.unlink

            def interrupted(name, **options):
                if name == "purge.json":
                    raise OSError("synthetic-interruption-after-durable-purge")
                return unlink(name, **options)

            with patch("tools.native_runtime.lifecycle.os.unlink", side_effect=interrupted):
                with self.assertRaises(OSError):
                    lifecycle.remove(self.layout, purge=installed["installationId"])
            self.assertEqual(lifecycle.read_state(self.layout)["status"], "purged")
            self.assertTrue((self.layout.prefix / "purge.json").exists())
            with self.assertRaisesRegex(InstallError, "interrupted-purge"):
                self.install(release)
            lifecycle.remove(self.layout, purge=installed["installationId"])
            self.assertFalse((self.layout.prefix / "purge.json").exists())

    def test_substituted_root_and_modified_binary_are_not_removed(self):
        with selected(self.root) as release:
            self.install(release)
            original = self.layout.data
            renamed = self.root / "original-data"
            original.rename(renamed)
            original.mkdir(mode=0o700)
            with self.assertRaisesRegex(InstallError, "root-substitution"):
                lifecycle.remove(self.layout)
            original.rmdir()
            renamed.rename(original)
            executable = self.layout.prefix / "releases" / release.metadata["version"] / "bin/latentd"
            executable.write_bytes(b"operator modification")
            with self.assertRaisesRegex(InstallError, "file-changed"):
                lifecycle.remove(self.layout)
            self.assertTrue(executable.exists())


if __name__ == "__main__":
    unittest.main()

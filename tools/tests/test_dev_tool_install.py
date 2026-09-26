"""Authentication gates, interrupted extraction and private tool selection."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.dev_workflow import assets, bundle, common, paths, state, tool_install
from tools.native_runtime.common import InstallError
from tools.tests.test_dev_contracts import descriptor


@unittest.skipUnless(sys.platform == "linux", "private Linux compiler installation")
class GuestTools(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.guest, self.frontend, self.release = (self.root / name for name in ("guest", "frontend", "release"))
        for directory in (self.guest, self.frontend, self.release):
            paths.new_directory(directory)
        content = {"sdk/bin/tool": b"compiler-test-fixture", "recipe/build.py": b"recipe-test-fixture"}
        inventory = {"schemaVersion": "latent.dev.guest-tools.v1", "language": "rust", "ownerIssue": 544,
            "sourceCommit": "a" * 40, "hostAbi": common.HOST_ABI, "host": "linux-x86_64",
            "files": [{"path": name, "size": len(raw), "sha256": common.digest(raw)} for name, raw in content.items()]}
        inventory["identity"] = common.digest(common.encode(inventory))
        self.inventory = common.encode(inventory)
        content.update({"guest-tools.json": self.inventory, "licenses/license.txt": b"test-license", "sbom.spdx.json": b"{}"})
        archive = self.release / "test-tools.zip"
        with zipfile.ZipFile(archive, "w") as output:
            for name, raw in content.items():
                output.writestr(name, raw)
        self.selected = {"schemaVersion": "latent.dev.bundle.v1", "version": "test", "sourceCommit": "a" * 40,
            "target": "linux-x86_64", "hostAbi": common.HOST_ABI, "protocol": common.PROTOCOL,
            "archive": {"name": archive.name, "size": archive.stat().st_size, "sha256": common.digest(archive.read_bytes())},
            "files": [{"path": name, "size": len(raw), "sha256": common.digest(raw), "executable": name == "sdk/bin/tool"}
                      for name, raw in content.items()], "licenses": ["licenses/license.txt"], "sbom": "sbom.spdx.json"}
        (self.release / "developer-bundle.json").write_bytes(common.encode(self.selected))
        (self.release / "SHA256SUMS").write_bytes(b"checksums-test-fixture")
        (self.release / "attestation.json").write_bytes(b"attestation-test-fixture")
        self.policy = {"schemaVersion": "latent.native-publisher-policy.v1", "repository": bundle.REPOSITORY,
            "workflow": bundle.WORKFLOW, "sourceRef": "refs/heads/feat/test", "sourceCommit": "a" * 40,
            "version": "test", "purpose": "candidate"}
        (self.root / "policy.json").write_bytes(common.encode(self.policy))
        (self.root / "roots.jsonl").write_bytes(b"roots-test-fixture")
        (self.root / "gh").write_bytes(b"verifier-test-fixture")
        self.value = {"schemaVersion": "latent.dev.tool-inputs.v1", "bundleDirectory": str(self.release),
            "version": "test", "language": "rust", "publisherPolicy": str(self.root / "policy.json"),
            "trustedRoot": str(self.root / "roots.jsonl"), "verifier": str(self.root / "gh"),
            "verifierSha256": common.digest(b"verifier-test-fixture"), "allowCandidate": True, "consent": True}
        self.operations = []
        outer = self
        class Connection:
            def call(self, operation, arguments, **_options):
                outer.operations.append(operation)
                if operation == "install-tools":
                    return tool_install.install(outer.guest, arguments)
                return assets.receive(outer.guest, operation, arguments)
        self.connection = Connection()

    def install(self, **changes):
        # Authentication's process execution is substituted only in these focused
        # lifecycle tests. It is not publisher or packaged-host qualification.
        with patch.object(bundle, "authenticate", return_value=self.selected) as authenticated:
            result = tool_install.inputs(self.frontend, self.connection, {**self.value, **changes})
            authenticated.assert_called_once()
            return result

    def test_install_reuse_exact_pins_and_purge_preserves_source(self):
        result = self.install()
        self.assertEqual(self.install(), result)
        self.assertEqual(state.load(self.frontend, "tool-selection.json"), result)
        self.assertEqual((Path(result["directory"]) / "sdk/bin/tool").stat().st_mode & 0o777, 0o700)
        value = descriptor()
        value["build"]["inventory"] = {"path": "guest-tools.json", "sha256": common.digest(self.inventory)}
        self.assertEqual(tool_install.selected_root(self.frontend, value), result["directory"])
        value["template"]["revision"] = "b" * 40
        with self.assertRaisesRegex(common.DevError, "do-not-match-project"):
            tool_install.selected_root(self.frontend, value)
        tool_install.purge(self.guest)
        self.assertFalse((self.guest / "tools").exists())
        self.assertTrue((self.release / "test-tools.zip").exists())

    def test_rejected_authentication_never_extracts_or_selects_tools(self):
        with patch.object(bundle, "authenticate", side_effect=common.DevError("publisher-rejected")):
            with self.assertRaisesRegex(common.DevError, "publisher-rejected"):
                tool_install.inputs(self.frontend, self.connection, self.value)
        self.assertFalse((self.guest / "tools").exists())
        self.assertFalse((self.frontend / "tool-selection.json").exists())

    def test_changed_completed_payload_is_rejected_and_not_implicitly_repaired(self):
        result = self.install()
        path = Path(result["directory"]) / "sdk/bin/tool"
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(common.DevError, "cache-changed"):
            self.install(resume=True)
        self.assertEqual(path.read_bytes(), b"changed")

    def test_interrupted_extraction_requires_explicit_resume_and_reauthentication(self):
        original = bundle.extract
        def interrupted(source, selected, destination, **_options):
            paths.new_directory(destination)
            paths.write_new(destination / "partial", b"partial")
            raise KeyboardInterrupt()
        with patch.object(bundle, "extract", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.install()
        self.assertFalse((self.frontend / "tool-selection.json").exists())
        with self.assertRaisesRegex(common.DevError, "explicit-resume"):
            self.install()
        result = self.install(resume=True)
        self.assertFalse((Path(result["directory"]) / "partial").exists())
        self.assertEqual(bundle.extract, original)

    def test_wrong_version_or_verifier_rejected_before_transfer(self):
        for change in ({"version": "wrong"}, {"verifierSha256": "sha256:" + "0" * 64}, {"consent": False}):
            with self.assertRaises(common.DevError):
                self.install(**change)
            self.assertEqual(self.operations, [])

    def test_unsafe_partial_payload_cannot_be_followed_or_purged(self):
        result = self.install()
        slot = Path(result["directory"]).parent
        owner = state.load(slot, "owner.json")
        state.atomic(slot, "owner.json", {**owner, "state": "extracting"})
        outside = self.root / "unrelated"
        paths.new_directory(outside)
        paths.write_new(outside / "keep", b"unrelated")
        (slot / "payload/escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(InstallError, "purge-unexpected-file-type"):
            self.install(resume=True)
        with self.assertRaisesRegex(InstallError, "purge-unexpected-file-type"):
            tool_install.purge(self.guest)
        self.assertEqual((outside / "keep").read_bytes(), b"unrelated")


if __name__ == "__main__":
    unittest.main()

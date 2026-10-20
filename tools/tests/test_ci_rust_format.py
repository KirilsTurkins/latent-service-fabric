"""Only exact third-party bytes may be excluded from owned Rust formatting."""
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import ci_cargo as cargo, ci_fast as fast, ci_suite_inventory as registry
from tools import host_stream_tls_provider as provider
from tools.ci_rust_artifacts import ArtifactError


class AuthenticatedRustFormat(unittest.TestCase):
    def fixture(self, root):
        names = {"Cargo.toml", "Cargo.lock", provider.RECORD,
                 "crates/latent-streams/src/tls.rs", "sdk/host-stream-tls/rustls-0.23.46-bounds/PATCH.json"}
        manifest = tomllib.loads((provider.ROOT / "Cargo.toml").read_text())
        names.update(member + "/Cargo.toml" for member in manifest["workspace"]["members"])
        for name in names:
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((provider.ROOT / name).read_bytes())
        shutil.copytree(provider.ROOT / provider.PROVIDER, root / provider.PROVIDER)

    def test_real_command_checks_every_owned_package_and_only_omits_authenticated_dependency(self):
        command = cargo.format_command(provider.ROOT)
        self.assertEqual(command[:2], ["cargo", "fmt"])
        self.assertEqual(command[-1], "--check")
        selected = command[3:-1:2]
        self.assertEqual(command[2:-1:2], ["--package"] * len(selected))
        self.assertEqual(selected, sorted(registry.workspace(provider.ROOT)))
        self.assertNotIn(provider.NAME, selected)
        self.assertIn("latent-streams", selected)
        self.assertNotIn("--all", command)

    def test_legacy_workspace_without_this_derivation_keeps_original_all_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_bytes(b'[workspace]\nmembers=[]\nexclude=["another-private-source"]\n')
            self.assertEqual(cargo.format_command(root), ["cargo", "fmt", "--all", "--check"])

    def test_new_owned_member_is_automatically_included_instead_of_a_frozen_allowlist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            original = cargo.format_command(root)
            manifest = root / "Cargo.toml"
            raw = manifest.read_bytes()
            self.assertEqual(raw.count(b"members = ["), 1)
            manifest.write_bytes(raw.replace(b"members = [", b'members = ["crates/new-format-owner",', 1))
            new = root / "crates/new-format-owner/Cargo.toml"
            new.parent.mkdir()
            new.write_bytes(b'[package]\nname="new-format-owner"\nversion="0.0.0"\nedition="2021"\n')
            changed = cargo.format_command(root)
            self.assertIn("new-format-owner", changed)
            self.assertEqual(set(changed) - set(original), {"new-format-owner"})
            self.assertEqual(len(changed), len(original) + 2)

    def test_unknown_excluded_dependency_or_changed_vendor_cannot_be_silently_skipped(self):
        for kind in ("unknown", "changed"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.fixture(root)
                if kind == "changed":
                    target = root / provider.PROVIDER / "Cargo.toml"
                    target.write_bytes(target.read_bytes() + b"\n")
                else:
                    foreign = root / "crates/unreviewed/Cargo.toml"
                    foreign.parent.mkdir()
                    foreign.write_bytes(b'[package]\nname="unreviewed"\nversion="0.0.0"\n')
                    target = root / "crates/latent-core/Cargo.toml"
                    target.write_bytes(target.read_bytes() + b'\n[dependencies.unreviewed]\npath="../unreviewed"\n')
                with self.assertRaises(ValueError):
                    cargo.format_command(root)

    def test_fast_and_central_execution_share_the_same_exact_owned_selection(self):
        expected = cargo.plan("format")["commands"][0]["argv"]
        self.assertEqual(expected, cargo.format_command(provider.ROOT))
        with tempfile.TemporaryDirectory() as temporary, \
                patch("sys.argv", ["ci_fast", "--packages-json", '["latent-core"]', "--output", temporary]), \
                patch.object(fast, "require_source"), \
                patch.object(fast, "format_command", wraps=cargo.format_command) as selected, \
                patch.object(fast, "run_owned", side_effect=ArtifactError("stop-after-format-selection")) as execute:
            self.assertEqual(fast.main(), 1)
            selected.assert_called_once_with(registry.ROOT)
            self.assertEqual(execute.call_args.args[0], expected)
            receipt = json.loads((Path(temporary) / "receipt.json").read_bytes())
            self.assertFalse(receipt["passed"])
            self.assertEqual(receipt["error"], "stop-after-format-selection")


if __name__ == "__main__":
    unittest.main()

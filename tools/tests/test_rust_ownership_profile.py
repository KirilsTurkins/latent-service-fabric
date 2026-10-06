"""Actual creator input checks, separate from the required wasm32 campaign."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from tools.check_rust_capsule_ownership import select_transaction_types
from tools.rust_capsule_project import create, snapshot


class RustOwnershipProfile(unittest.TestCase):
    def test_feature_selection_preserves_every_other_captured_byte_and_project_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "project", "greeting", "borrow-checks")
            before = snapshot(project)
            original = tomllib.loads(before["Cargo.toml"].decode())
            select_transaction_types(project)
            after = snapshot(project)
            self.assertEqual({key: value for key, value in before.items() if key != "Cargo.toml"},
                             {key: value for key, value in after.items() if key != "Cargo.toml"})
            selected = tomllib.loads(after["Cargo.toml"].decode())
            dependency = selected["target"]['cfg(target_arch = "wasm32")']["dependencies"]["latent-guest"]
            self.assertEqual(dependency, {"path": "vendor/lsf/sdk/rust-guest", "features": ["transaction"]})
            dependency.pop("features")
            self.assertEqual(selected, original)

    def test_manifest_drift_and_second_selection_refuse_without_rewriting_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "project", "greeting", "borrow-checks")
            path = project / "Cargo.toml"
            original = path.read_bytes()
            drifted = original.replace(b'path = "vendor/lsf/sdk/rust-guest"', b'path = "unreviewed-sdk"')
            path.write_bytes(drifted)
            with self.assertRaisesRegex(ValueError, "ownership SDK manifest"):
                select_transaction_types(project)
            self.assertEqual(path.read_bytes(), drifted)
            path.write_bytes(original)
            select_transaction_types(project)
            selected = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "ownership SDK manifest"):
                select_transaction_types(project)
            self.assertEqual(path.read_bytes(), selected)

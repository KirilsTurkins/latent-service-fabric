"""The provider selects exactly its own authenticated bounded TLS dependency."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest

from tools import host_stream_tls_provider as provider
from tools.native_runtime.common import InstallError
from tools.native_runtime_build import dependency_inventory
from tools import ci_suite_inventory as registry
from unittest.mock import patch


class BoundedTlsProviderSource(unittest.TestCase):
    def fixture(self, root):
        for name in (provider.RECORD, "Cargo.toml", "Cargo.lock", "crates/latent-streams/Cargo.toml",
                     "crates/latent-streams/src/tls.rs",
                     "sdk/host-stream-tls/rustls-0.23.46-bounds/PATCH.json"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((provider.ROOT / name).read_bytes())
        shutil.copytree(provider.ROOT / provider.PROVIDER, root / provider.PROVIDER)

    def test_complete_current_source_and_license_closure_are_authenticated(self):
        result = provider.verify()
        record = json.loads((provider.ROOT / provider.RECORD).read_bytes())
        self.assertEqual(len(result["files"]), 119)
        changed = {name for name, row in record["files"].items()
                   if row["beforeSha256"] != row["afterSha256"]}
        self.assertEqual(changed, provider.captured.CURRENT_FILES | {"Cargo.toml"})
        self.assertFalse(result["accountingQualified"])
        self.assertFalse(result["installed"])
        for name, expected in record["licenseFiles"].items():
            self.assertEqual(result["files"][name]["sha256"], expected)
            self.assertEqual((provider.ROOT / provider.PROVIDER / name).read_bytes(),
                             (provider.captured.PATCH_ROOT / name).read_bytes())

    def test_only_package_name_changes_in_the_exact_upstream_cargo_manifest(self):
        derived = (provider.ROOT / provider.PROVIDER / "Cargo.toml").read_bytes()
        original = derived.replace(b'\nname = "latent-rustls-outbound"\nversion = "0.23.46"\n',
                                   b'\nname = "rustls"\nversion = "0.23.46"\n', 1)
        self.assertEqual(hashlib.sha256(original).hexdigest(), provider.UPSTREAM_MANIFEST_SHA256)
        self.assertEqual(provider.derived_manifest(original), derived)
        expected = tomllib.loads(original.decode())
        actual = tomllib.loads(derived.decode())
        actual["package"]["name"] = "rustls"
        self.assertEqual(actual, expected)
        for changed in (original + b"\n", original.replace(b'features = ["alloc"]', b'features = []', 1)):
            self.assertNotEqual(changed, original)
            with self.assertRaisesRegex(ValueError, "manifest-preimage"):
                provider.derived_manifest(changed)

    def test_unbounded_old_selection_and_any_mixed_or_extra_source_are_refused(self):
        for kind in ("old-selection", "parser", "license", "extra", "record"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.fixture(root)
                if kind == "old-selection":
                    target = root / "crates/latent-streams/Cargo.toml"
                    raw = target.read_bytes()
                    changed = raw.replace(b'package = "latent-rustls-outbound", path = "../vendor/rustls-outbound", ', b"", 1)
                    self.assertNotEqual(raw, changed)
                    target.write_bytes(changed)
                elif kind == "record":
                    target = root / provider.RECORD
                    target.write_bytes(target.read_bytes() + b"\n")
                elif kind == "extra":
                    (root / provider.PROVIDER / "unreviewed.rs").write_bytes(b"unreviewed\n")
                else:
                    target = root / provider.PROVIDER / ("src/conn.rs" if kind == "parser" else "LICENSE-MIT")
                    target.write_bytes(target.read_bytes() + b"changed\n")
                with self.assertRaises(ValueError):
                    provider.verify(root)

    def test_global_shadowing_changed_lock_and_accounting_enablement_are_refused(self):
        for kind in ("global-patch", "workspace", "lock", "accounting"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.fixture(root)
                if kind == "global-patch":
                    target = root / "Cargo.toml"
                    target.write_bytes(target.read_bytes() + b'\n[patch.crates-io]\nrustls = {path="crates/vendor/rustls-outbound"}\n')
                elif kind == "workspace":
                    target = root / "Cargo.toml"
                    target.write_bytes(target.read_bytes().replace(b'exclude = ["crates/vendor/rustls-outbound"]', b"exclude = []", 1))
                elif kind == "accounting":
                    target = root / "crates/latent-streams/src/tls.rs"
                    target.write_bytes(target.read_bytes().replace(b"ACCOUNTING_QUALIFIED: bool = false", b"ACCOUNTING_QUALIFIED: bool = true", 1))
                else:
                    target = root / "Cargo.lock"
                    raw = target.read_bytes()
                    needle = b'name = "latent-rustls-outbound"\nversion = "0.23.46"'
                    self.assertEqual(raw.count(needle), 1)
                    target.write_bytes(raw.replace(needle, needle + b'\nsource = "registry+https://github.com/rust-lang/crates.io-index"', 1))
                with self.assertRaises(ValueError):
                    provider.verify(root)

    def test_native_inventory_retains_all_authenticated_local_third_party_licenses(self):
        package = {"id": "bounded-local", "name": provider.NAME, "version": "0.23.46",
                   "source": None, "license": "Apache-2.0 OR ISC OR MIT",
                   "manifest_path": str(provider.ROOT / provider.PROVIDER / "Cargo.toml")}
        metadata = {"packages": [package], "resolve": {"nodes": [{"id": package["id"], "deps": []}]}}
        lock = tomllib.loads((provider.ROOT / "Cargo.lock").read_text(encoding="utf-8"))
        sbom, licenses = dependency_inventory(metadata, lock, "a" * 40, 0, {},
                                             root_names=frozenset({provider.NAME}))
        checked = provider.verify()
        self.assertEqual(len(licenses), 3)
        for name, path in licenses.items():
            self.assertEqual(name, "licenses/latent-rustls-outbound-0.23.46/" + path.name)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), checked["licenseFiles"][path.name])
        self.assertIn(provider.RECORD_SHA256, sbom["packages"][0]["comment"])
        self.assertNotIn("checksums", sbom["packages"][0])
        for change in ({"source": "registry+https://github.com/rust-lang/crates.io-index"},
                       {"version": "0.23.47"}, {"license": "MIT"}):
            with self.subTest(change=change):
                bad = {**metadata, "packages": [{**package, **change}]}
                with self.assertRaises(InstallError):
                    dependency_inventory(bad, lock, "a" * 40, 0, {}, root_names=frozenset({provider.NAME}))

    def test_ci_graph_keeps_only_authenticated_excluded_dependency_outside_test_targets(self):
        graph = registry.workspace(provider.ROOT)
        self.assertIn("latent-streams", graph)
        self.assertNotIn(provider.NAME, graph)
        self.assertNotIn(provider.NAME, graph["latent-streams"].dependencies)
        with patch.object(provider, "verify", side_effect=ValueError("tampered-vendor-source")), \
                self.assertRaisesRegex(ValueError, "tampered-vendor-source"):
            registry.workspace(provider.ROOT)


if __name__ == "__main__":
    unittest.main()

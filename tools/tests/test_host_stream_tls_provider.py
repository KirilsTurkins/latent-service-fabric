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
        self.assertEqual(changed, provider.captured.CURRENT_FILES | {"Cargo.toml", "Cargo.lock"})
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

    def test_current_lock_is_the_exact_cargo_generated_security_derivation(self):
        record = json.loads((provider.ROOT / provider.RECORD).read_bytes())
        original = record["lockDerivation"]["original"].encode()
        self.assertEqual(len(original), 31170)
        self.assertEqual(hashlib.sha256(original).hexdigest(), provider.UPSTREAM_LOCK_SHA256)
        maintained = (provider.ROOT / provider.PROVIDER / "Cargo.lock").read_bytes()
        self.assertEqual(provider.derived_lock(original), maintained)
        before = tomllib.loads(original.decode())["package"]
        after = tomllib.loads(maintained.decode())["package"]
        self.assertEqual(len(before), 134)
        self.assertEqual(len(after), 134)
        renamed = next(row for row in after if row["name"] == provider.NAME)
        self.assertEqual({**renamed, "name": "rustls"}, next(row for row in before if row["name"] == "rustls"))
        changed = {"rustls", provider.NAME, "rustls-webpki", "webpki-roots"}
        self.assertEqual([row for row in before if row["name"] not in changed],
                         [row for row in after if row["name"] not in changed])
        for name, _, version, _, checksum in provider.LOCK_UPDATES:
            old = next(row for row in before if row["name"] == name)
            new = next(row for row in after if row["name"] == name)
            self.assertEqual(new, {**old, "version": version, "checksum": checksum})

    def test_lock_preimage_and_maintained_result_drift_are_refused(self):
        record = json.loads((provider.ROOT / provider.RECORD).read_bytes())
        original = record["lockDerivation"]["original"].encode()
        for changed in (original + b"\n", original.replace(b'"0.103.15"', b'"0.103.14"', 1),
                        original.replace(b'"ring"', b'"foreign"', 1)):
            self.assertNotEqual(original, changed)
            with self.assertRaisesRegex(ValueError, "lock-preimage"):
                provider.derived_lock(changed)
        with patch.object(provider, "MAINTAINED_LOCK_SHA256", "0" * 64), \
                self.assertRaisesRegex(ValueError, "lock-result"):
            provider.derived_lock(original)

    def test_selected_root_trust_dependencies_use_patched_versions(self):
        lock = tomllib.loads((provider.ROOT / "Cargo.lock").read_text(encoding="utf-8"))
        for name, version in (("rustls-webpki", "0.103.16"), ("webpki-roots", "1.0.10"),
                              ("webpki-root-certs", "1.0.10")):
            selected = [row["version"] for row in lock["package"] if row["name"] == name]
            self.assertEqual(selected, [version])
        for crate in ("latent-http", "latent-nats", "latent-oci"):
            manifest = provider.ROOT / "crates" / crate / "Cargo.toml"
            self.assertEqual(tomllib.loads(manifest.read_text(encoding="utf-8"))["dependencies"]["webpki-roots"],
                             "=1.0.10")

    def test_global_shadowing_changed_lock_and_accounting_enablement_are_refused(self):
        for kind in ("global-patch", "global-replace", "workspace", "lock", "accounting"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.fixture(root)
                if kind == "global-patch":
                    target = root / "Cargo.toml"
                    target.write_bytes(target.read_bytes() + b'\n[patch.crates-io]\nrustls = {path="crates/vendor/rustls-outbound"}\n')
                elif kind == "global-replace":
                    target = root / "Cargo.toml"
                    target.write_bytes(target.read_bytes() + b'\n[replace]\n"latent-rustls-outbound:0.23.46" = {path="foreign"}\n')
                elif kind == "workspace":
                    target = root / "Cargo.toml"
                    raw = target.read_bytes()
                    excluded = tomllib.loads(raw.decode())["workspace"]["exclude"]
                    self.assertEqual(excluded.count(provider.PROVIDER), 1)
                    before = ("exclude = " + json.dumps(excluded)).encode()
                    after = ("exclude = " + json.dumps(
                        [name for name in excluded if name != provider.PROVIDER])).encode()
                    self.assertEqual(raw.count(before), 1)
                    changed = raw.replace(before, after, 1)
                    self.assertNotEqual(raw, changed)
                    self.assertNotIn(provider.PROVIDER,
                                     tomllib.loads(changed.decode())["workspace"]["exclude"])
                    target.write_bytes(changed)
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

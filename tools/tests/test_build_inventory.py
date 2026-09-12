"""Tiny Cargo unit and declared-attribution tests; no compiler invocation."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
import jsonschema

from tools.build_inventory_manifests import ManifestReader
from tools.build_inventory_licenses import license_expression, load_license_ids
from tools.build_inventory_units import InventoryLimits, collect_units
from tools.build_sbom_inputs import InventoryCollector
from tools.build_snapshot import SnapshotError, canonical, digest


def artifact(root: Path, manifest: Path, name: str, kind="lib", *, host=False):
    domain = "release" if host else "wasm32-unknown-unknown/release"
    return {"reason": "compiler-artifact", "package_id": "private-id:" + str(manifest),
            "manifest_path": str(manifest), "target": {"name": name, "kind": [kind],
            "crate_types": ["bin" if kind in ("example", "custom-build") else kind]},
            "filenames": [str(root / domain / "deps" / (name + ".artifact"))]}


def messages(records):
    return "\n".join(json.dumps(row) for row in [*records, {"reason": "build-finished", "success": True}])


def source_fixture(root: Path):
    source = root / "source"
    cache = root / "cargo"
    cache.mkdir()
    files = {
        "Cargo.toml": b'[workspace]\nmembers=["crates/local"]\n[workspace.package]\nversion="1.0.0"\nlicense="Apache-2.0"\nlicense-file="LICENSE"\n',
        "Cargo.lock": b'version=4\n[[package]]\nname="latent-toolchain-smoke"\nversion="1.0.0"\n[[package]]\nname="local"\nversion="1.0.0"\n[[package]]\nname="external"\nversion="2.0.0"\nsource="registry+https://github.com/rust-lang/crates.io-index"\nchecksum="' + b"a" * 64 + b'"\n',
        "tools/toolchain-smoke/Cargo.toml": b'[package]\nname="latent-toolchain-smoke"\nversion.workspace=true\nlicense.workspace=true\n',
        "crates/local/Cargo.toml": b'[package]\nname="local"\nversion.workspace=true\nlicense.workspace=true\nlicense-file.workspace=true\nrepository="https://example.invalid/local"\n',
        "LICENSE": b"declared workspace license text",
    }
    for name, data in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    inventory = canonical([{"path": name, "digest": digest(data), "size": len(data), "mode": 420}
                           for name, data in sorted(files.items())])
    registry = cache / "registry/src/crates-index/external-2.0.0"
    registry.mkdir(parents=True)
    (registry / "Cargo.toml").write_bytes(b'[package]\nname="external"\nversion="2.0.0"\nlicense="MIT OR Apache-2.0"\nrepository="https://user:secret@example.invalid/repo"\n')
    return source, inventory, cache, registry / "Cargo.toml"


class BuildInventoryTests(unittest.TestCase):
    def test_license_subset_omits_unknown_exceptions_and_invalid_expressions(self):
        licenses = load_license_ids()
        for expression in ("MIT", "Apache-2.0 OR MIT", "(MIT AND Apache-2.0) OR BSD-3-Clause"):
            self.assertEqual(license_expression(expression, licenses), expression)
        for expression in (None, "", "MIT/Apache-2.0", "MIT AND", "MIT OROR MIT", "MIT MIT",
                "GPL-2.0", "GPL-CC-1.0", "Linux-syscall-note", "389-exception", "Net-SNMP",
                "MIT WITH LLVM-exception", "LicenseRef-private", "(MIT", "MIT)",
                "MIT\nOR MIT", "MIT and Apache-2.0", "(" * 17 + "MIT" + ")" * 17,
                " OR ".join(["MIT"] * 129)):
            with self.subTest(expression=expression):
                self.assertIsNone(license_expression(expression, licenses))

    def test_normalized_inventory_is_private_path_free_and_repeated_roles_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, inventory, cache, registry = source_fixture(root)
            collector = InventoryCollector(source, inventory, cache)
            selected = source / "tools/toolchain-smoke/Cargo.toml"
            build_a, build_b = root / "build-a", root / "build-b"
            for build in (build_a, build_b):
                build.mkdir()
                collector.observe(messages([artifact(build, selected, "echo-capsule", "example"),
                    artifact(build, source / "crates/local/Cargo.toml", "local"),
                    artifact(build, registry, "external"),
                    artifact(build, registry, "external", host=True)]), build)
            package = root / "package"
            package.mkdir()
            component, wit = b"tiny component", b"package example:api@1.0.0;"
            (package / "component.wasm").write_bytes(component)
            (package / "api.wit").write_bytes(wit)
            recipe = {"kind": "capsule", "name": "fixture", "version": "1.0.0", "layers": [
                {"path": "component.wasm", "source": "component.wasm", "role": "component"},
                {"path": "api.wit", "source": "api.wit", "role": "asset"}]}
            (package / "package-source.json").write_bytes(canonical(recipe))
            (package / "wit-lock.json").write_bytes(canonical({"packages": [{"id": "example:api@1.0.0",
                "sourcePath": "api.wit", "digest": digest(wit)}]}))
            tools = [{"name": name, "digest": digest(name.encode()), "size": len(name)}
                     for name in ("cargo", "rustc", "wasm-tools")]
            toolchain = {"rust": {"toolchain": "1.97.1"}, "contracts": {"wasm-tools": "1.254.0"}}
            raw = collector.finish(package, toolchain, tools, reproducible=True)
            document = json.loads(raw)
            schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/package-sbom-inputs.schema.json").read_bytes())
            jsonschema.Draft202012Validator(schema).validate(document)
            self.assertEqual(raw, canonical(document))
            self.assertNotIn(str(root), raw.decode())
            self.assertNotIn("private-id", raw.decode())
            self.assertEqual(document["sourceSnapshotDigest"], digest(inventory))
            rows = document["entries"]
            self.assertEqual(len(rows), 8)
            external = [row for row in rows if row["name"] == "external"]
            self.assertEqual({row["kind"] for row in external}, {"guest-dependency", "build-dependency"})
            self.assertTrue(all(row["digestScope"] == "registry-archive-declared" and "size" not in row
                                and row["manifestDigest"] != row["digest"] for row in external))
            self.assertEqual([row["kind"] for row in rows if row.get("path") == "api.wit"], ["wit-package"])
            output = next(row for row in rows if row["kind"] == "component")
            self.assertEqual(output["licenseExpression"], "Apache-2.0")
            self.assertEqual(output["source"], "urn:lsf:workspace:tools/toolchain-smoke/Cargo.toml")
            self.assertNotIn("version", output)
            self.assertNotIn("manifestDigest", output)
            self.assertFalse(any(value is None for row in rows for value in row.values()))
            (package / "api.wit").write_bytes(b"changed WIT")
            with self.assertRaises(SnapshotError):
                collector.finish(package, toolchain, tools, reproducible=True)

    def test_changed_repeated_unit_set_or_forged_selected_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, inventory, cache, registry = source_fixture(root)
            collector = InventoryCollector(source, inventory, cache)
            selected = artifact(root, source / "tools/toolchain-smoke/Cargo.toml", "echo-capsule", "example")
            collector.observe(messages([selected, artifact(root, registry, "external")]), root)
            with self.assertRaises(SnapshotError):
                collector.observe(messages([selected]), root)
            with self.assertRaises(SnapshotError):
                InventoryCollector(source, inventory, cache).observe(messages([
                    artifact(root, source / "crates/local/Cargo.toml", "echo-capsule", "example")]), root)

    def test_unit_roles_distinguish_guest_host_macro_script_and_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "Cargo.toml"
            rows = [artifact(root, manifest, "echo-capsule", "example"),
                    artifact(root, root / "guest/Cargo.toml", "guest"),
                    artifact(root, root / "host/Cargo.toml", "host", host=True),
                    artifact(root, root / "macro/Cargo.toml", "macro", "proc-macro", host=True),
                    artifact(root, root / "script/Cargo.toml", "build_script_build", "custom-build", host=True)]
            units = collect_units(messages(rows), root)
            self.assertEqual({unit.role for unit in units},
                             {"component", "guest-dependency", "build-dependency", "proc-macro", "build-script"})
            self.assertEqual(collect_units(messages(list(reversed(rows))), root), units)

    def test_dual_role_package_is_preserved_and_conflicting_or_outside_records_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "shared/Cargo.toml"
            selected = artifact(root, root / "Cargo.toml", "echo-capsule", "example")
            guest = artifact(root, manifest, "shared")
            host = artifact(root, manifest, "shared", host=True)
            units = collect_units(messages([selected, guest, host]), root)
            self.assertEqual({unit.role for unit in units if unit.manifest == manifest},
                             {"guest-dependency", "build-dependency"})
            conflicts = [dict(host, manifest_path=str(root / "different/Cargo.toml")),
                         dict(host, filenames=[str(root.parent / "outside.artifact")]),
                         artifact(root, manifest, "macro", "proc-macro"),
                         dict(host, filenames=[guest["filenames"][0], host["filenames"][0]])]
            for changed in conflicts:
                with self.subTest(changed=changed), self.assertRaises(SnapshotError):
                    collect_units(messages([selected, guest, changed]), root)

    def test_unit_bounds_completion_and_duplicate_json_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = artifact(root, root / "Cargo.toml", "echo-capsule", "example")
            for payload, limits in ((messages([selected, selected]), InventoryLimits(max_units=1)),
                    (messages([selected]), InventoryLimits(max_record_bytes=20)),
                    (json.dumps(selected), InventoryLimits()),
                    (messages([selected]).replace('"success": true', '"success": false'), InventoryLimits()),
                    (messages([selected]).replace('"reason": "compiler-artifact"',
                     '"reason": "ignored", "reason": "compiler-artifact"'), InventoryLimits())):
                with self.subTest(limits=limits), self.assertRaises(SnapshotError):
                    collect_units(payload, root, limits)
            with self.assertRaises(SnapshotError):
                replace(InventoryLimits(), max_packages=513).validate()

    def test_declared_local_and_cache_attribution_have_separate_hash_meaning(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, inventory, cache, registry = source_fixture(Path(temporary))
            reader = ManifestReader(source, inventory, cache)
            local = reader.package(source / "crates/local/Cargo.toml")
            external = reader.package(registry)
            self.assertEqual(local.license_expression, "Apache-2.0")
            self.assertNotIn(source / "LICENSE", reader.observed)
            self.assertEqual(local.origin, "captured-source:crates/local/Cargo.toml")
            self.assertIsNone(local.archive_digest)
            self.assertEqual(external.source_kind, "observed-cache")
            self.assertEqual(external.archive_digest, "sha256:" + "a" * 64)
            self.assertNotEqual(external.manifest_digest, external.archive_digest)
            self.assertIsNone(external.repository)
            reader.verify_unchanged()

    def test_changed_source_or_cache_metadata_suppresses_inventory(self):
        for changed in ("source", "cache"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                source, inventory, cache, registry = source_fixture(Path(temporary))
                reader = ManifestReader(source, inventory, cache)
                path = source / "crates/local/Cargo.toml" if changed == "source" else registry
                reader.package(path)
                path.write_bytes(path.read_bytes() + b"\n# changed\n")
                with self.assertRaises(SnapshotError):
                    reader.verify_unchanged()

    def test_manifest_bounds_and_host_path_escape_fail_before_attribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, inventory, cache, registry = source_fixture(root)
            with self.assertRaises(SnapshotError):
                ManifestReader(source, inventory, cache, InventoryLimits(max_manifest_bytes=8))
            reader = ManifestReader(source, inventory, cache)
            with self.assertRaises(SnapshotError):
                reader.package(root / "outside/Cargo.toml")
            registry.write_bytes(registry.read_bytes() + b'license-file="../../outside"\n')
            # License-file paths are declarations only, never followed.
            self.assertEqual(reader.package(registry).license_expression, "MIT OR Apache-2.0")


if __name__ == "__main__":
    unittest.main()

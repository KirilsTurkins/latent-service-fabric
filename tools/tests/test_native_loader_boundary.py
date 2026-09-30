from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_loader_boundary as boundary


class NativeLoaderBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write("Cargo.toml", '''
[workspace]
members = ["crates/latent-wasmtime", "crates/other"]
[workspace.lints.rust]
unsafe_code = "forbid"
[workspace.lints.clippy]
all = "warn"
[workspace.dependencies]
wasmtime = {version = "=48.0.3", default-features = false}
''')
        self.write(f"{boundary.CRATE}/Cargo.toml", '''
[lints.rust]
unsafe_code = "deny"
[lints.clippy]
all = "warn"
''')
        self.write("crates/other/Cargo.toml", "[lints]\nworkspace = true\n")
        self.write(f"{boundary.CRATE}/src/lib.rs", "#![deny(unsafe_code)]\n")
        self.loader = boundary.ALLOW + "\n" + boundary.FUNCTION + "\nfn load_failed() {}\n"
        self.write(boundary.LOADER, self.loader)

    def write(self, name: str, value: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def test_reviewed_boundary_passes(self) -> None:
        self.assertEqual(boundary.validate(self.root), [])

    def test_actual_guest_matches_the_two_closed_profile_generators(self) -> None:
        self.assertEqual(boundary.validate_guest(Path(__file__).resolve().parents[2]), [])

    def test_guest_profile_conditions_cannot_be_removed_or_coenabled(self) -> None:
        self.write(f"{boundary.GUEST}/src/lib.rs", '#![cfg(target_arch = "wasm32")]\n' + boundary.GUEST_ALLOW)
        for selector in ('#[cfg(not(feature = "backend-http"))]', '#[cfg(feature = "backend-http")]'):
            for replacement in ("", '#[cfg(feature = "another-backend")]'):
                with self.subTest(selector=selector, replacement=replacement):
                    self.write(f"{boundary.GUEST}/src/abi.rs", boundary.GUEST_ABI.replace(selector, replacement))
                    self.assertTrue(boundary.validate_guest(self.root))
        self.write(f"{boundary.GUEST}/src/abi.rs", boundary.GUEST_ABI.replace(
            '#[cfg(not(feature = "backend-http"))]', '#[cfg(feature = "backend-http")]'))
        self.assertTrue(boundary.validate_guest(self.root))

    def test_guest_world_and_wit_sources_remain_exact(self) -> None:
        self.write(f"{boundary.GUEST}/src/lib.rs", '#![cfg(target_arch = "wasm32")]\n' + boundary.GUEST_ALLOW)
        for before, after in (
            ('adapter-http@0.1.0', 'adapter-http@0.2.0'),
            ('adapter@0.1.0', 'adapter-http@0.1.0'),
            ('"../../wit/platform/http-v2"', '"../../wit/platform/sockets"'),
            ('generate_all,', 'generate_all, with: {"latent:ambient/io": custom_io},'),
        ):
            with self.subTest(replacement=after):
                self.write(f"{boundary.GUEST}/src/abi.rs", boundary.GUEST_ABI.replace(before, after))
                self.assertTrue(boundary.validate_guest(self.root))

    def test_second_unsafe_site_and_nested_allowance_fail(self) -> None:
        for addition in ("unsafe { second_load() }", "#[allow(unsafe_code)]\nfn extra() {}"):
            with self.subTest(addition=addition):
                self.write(f"{boundary.CRATE}/src/extra.rs", addition)
                self.assertTrue(boundary.validate(self.root))

    def test_file_loader_or_arbitrary_bytes_cannot_replace_proof(self) -> None:
        for replacement in ("Component::deserialize_file(engine, path)",
                            "Component::deserialize(engine, arbitrary_bytes)"):
            with self.subTest(replacement=replacement):
                self.write(boundary.LOADER, self.loader.replace(
                    "Component::deserialize(engine, proof.bytes())", replacement))
                self.assertTrue(boundary.validate(self.root))

    def test_allowance_cannot_expand_to_module_or_another_function(self) -> None:
        self.write(boundary.LOADER, self.loader.replace(
            "fn deserialize_authenticated(", "fn unrelated() {}\nfn deserialize_authenticated("))
        self.assertTrue(boundary.validate(self.root))

    def test_engine_update_requires_review(self) -> None:
        path = self.root / "Cargo.toml"
        path.write_text(path.read_text().replace("=48.0.3", "=48.0.0"), encoding="utf-8")
        self.assertTrue(boundary.validate(self.root))

    def test_other_workspace_member_cannot_relax_lints(self) -> None:
        self.write("crates/other/Cargo.toml", '[lints.rust]\nunsafe_code = "allow"\n')
        self.assertTrue(boundary.validate(self.root))

    def test_guest_allowance_is_wasm_only_and_cannot_contain_handwritten_unsafe(self) -> None:
        self.write(f"{boundary.GUEST}/src/lib.rs", '#![cfg(target_arch = "wasm32")]\n' + boundary.GUEST_ALLOW)
        self.write(f"{boundary.GUEST}/src/abi.rs", boundary.GUEST_ABI)
        self.assertEqual(boundary.validate_guest(self.root), [])
        for addition in ("unsafe { something() }", "#[allow(unsafe_code)] fn extra() {}"):
            with self.subTest(addition=addition):
                self.write(f"{boundary.GUEST}/src/extra.rs", addition)
                self.assertTrue(boundary.validate_guest(self.root))
        self.write(f"{boundary.GUEST}/src/extra.rs", "")
        self.write(f"{boundary.GUEST}/src/abi.rs", boundary.GUEST_ABI + "\nfn handwritten() {}")
        self.assertTrue(boundary.validate_guest(self.root))


    def test_current_engine_minimum_rust_and_host_descriptors_are_aligned(self) -> None:
        import json
        root = Path(__file__).resolve().parents[2]
        workspace = boundary.tomllib.loads((root / "Cargo.toml").read_text())["workspace"]
        pins = boundary.tomllib.loads((root / "tools/toolchain.toml").read_text())
        self.assertEqual(workspace["dependencies"]["wasmtime"]["version"], "=48.0.3")
        self.assertEqual(workspace["package"]["rust-version"], "1.95.0")
        self.assertEqual(pins["rust"]["msrv"], "1.95.0")
        self.assertEqual(pins["rust"]["dependencies"]["wasmtime"], "48.0.3")
        # Only v4 is active. Superseded matrices retain their tested runtime,
        # independently fingerprinted by test_host_abi_profile.
        for name, version in (("v2", "47.0.4"), ("v3", "47.0.4"), ("v4", "48.0.3")):
            with self.subTest(descriptor=name):
                descriptor = json.loads((root / f"wit/host-abi-phase3-{name}.json").read_text())
                self.assertEqual(descriptor["wasmtimeVersion"], version)
        self.assertEqual(boundary.validate(root), [])

    def test_resolved_runtime_and_authoring_locks_use_the_patched_engine_family(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for name in ("Cargo.lock", "tools/rust_capsule.lock"):
            with self.subTest(lock=name):
                packages = boundary.tomllib.loads((root / name).read_text())["package"]
                family = [p for p in packages if p["name"].startswith(("wasmtime", "pulley-"))]
                self.assertTrue(any(p["name"] == "wasmtime" for p in family))
                self.assertTrue(all(p["version"] == "48.0.3" for p in family))

    def test_real_standalone_authoring_lock_remains_in_the_workspace_closure(self) -> None:
        from tools.rust_capsule_project import locked_dependencies
        raw = locked_dependencies("security-regression-template")
        packages = boundary.tomllib.loads(raw.decode())["package"]
        self.assertEqual([p["version"] for p in packages if p["name"] == "wasmtime"], ["48.0.3"])


if __name__ == "__main__":
    unittest.main()

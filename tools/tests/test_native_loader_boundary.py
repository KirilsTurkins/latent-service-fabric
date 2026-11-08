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
wasmtime = {version = "=48.0.8", default-features = false}
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
        actual = Path(__file__).resolve().parents[2]
        source = (actual / boundary.STREAM_FACTORY / "src/lib.rs").read_text(encoding="utf-8")
        manifest = '''
[package]
name = "latent-stream-factory-native"
[lints.rust]
unsafe_code = "deny"
[lints.clippy]
all = "warn"
[target.'cfg(all(target_os = "linux", target_arch = "x86_64"))'.dependencies]
rustix = { version = "=1.1.5", features = ["fs"] }
'''
        self.write(f"{boundary.STREAM_FACTORY}/Cargo.toml", manifest)
        self.write(f"{boundary.STREAM_FACTORY}/src/lib.rs", source)
        workspace = self.root / "Cargo.toml"
        workspace.write_text(workspace.read_text(encoding="utf-8").replace(
            'members = [', f'members = ["{boundary.STREAM_FACTORY}", '), encoding="utf-8")
        self.assertEqual(boundary.validate(self.root), [])
        # These real outside files evade the leaf's src inventory; its Cargo
        # target/build selection must independently remain closed.
        self.write("crates/outside.rs", "#![allow(unsafe_code)]\nunsafe fn outside() {}\n")
        for changed in (manifest.replace('unsafe_code = "deny"', 'unsafe_code = "allow"'),
                        manifest.replace('unsafe_code = "deny"', ''),
                        manifest.replace('name = "latent-stream-factory-native"', 'name = "unknown-native"'),
                        manifest.replace('=1.1.5', '=1.1.6'),
                        manifest + '\n[lib]\npath = "../outside.rs"\n',
                        manifest.replace('[package]', '[package]\nbuild = "../outside.rs"')):
            with self.subTest(manifest=changed):
                self.write(f"{boundary.STREAM_FACTORY}/Cargo.toml", changed)
                self.assertTrue(boundary.validate(self.root))
        self.write(f"{boundary.STREAM_FACTORY}/Cargo.toml", manifest)
        self.write(f"{boundary.STREAM_FACTORY}/src/lib.rs", source + '\nunsafe fn extra() {}\n')
        self.assertTrue(boundary.validate(self.root))
        self.write(f"{boundary.STREAM_FACTORY}/src/lib.rs", source)
        self.write(f"{boundary.STREAM_FACTORY}/src/extra.rs", "fn another_target() {}\n")
        self.assertTrue(boundary.validate(self.root))

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
        source = (Path(__file__).resolve().parents[2] / boundary.STREAM_COPY_RESULT).read_text(encoding="utf-8")
        self.write(boundary.STREAM_COPY_RESULT, source)
        self.assertEqual(boundary.validate(self.root), [])
        for changed in (
            source.replace('pub(super) struct ChunkBytes(pub(super) IoOutputCopy);', 'pub(super) struct ChunkBytes(pub(super) ());'),
            source.replace('self.0.as_ref().linear_lower_to_memory(cx, ty, offset)', 'unrelated_lower(cx, ty, offset)'),
            source + '\nunsafe fn extra_copy_site() {}\n',
            source + '\n#[allow(unsafe_code)] fn extra_copy_allowance() {}\n',
            source.replace('#[allow(', '#![allow(', 1),
        ):
            with self.subTest(copy_change=changed[-120:]):
                self.assertNotEqual(changed, source)
                self.write(boundary.STREAM_COPY_RESULT, changed)
                self.assertTrue(boundary.validate(self.root))
        self.write(boundary.STREAM_COPY_RESULT, source)
        self.assertEqual(boundary.validate(self.root), [])
        for addition in ("unsafe { second_load() }", "#[allow(unsafe_code)]\nfn extra() {}"):
            with self.subTest(addition=addition):
                self.write(f"{boundary.CRATE}/src/extra.rs", addition)
                self.assertTrue(boundary.validate(self.root))

    def test_refusing_memory_creator_exception_is_one_exact_test_item(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.REFUSING_CREATOR_TEST).read_text(encoding="utf-8")
        self.write(boundary.REFUSING_CREATOR_TEST, source)
        self.assertEqual(boundary.validate(self.root), [])
        for changed in (
            source.replace('Err("native-linear-original-creator-refusal".into())', 'Ok(create_memory())'),
            source + '\nunsafe fn extra() {}\n',
            source + '\n#[allow(unsafe_code)] fn extra() {}\n',
            source + '\n' + boundary.REFUSING_CREATOR_IMPL,
            source.replace('#[allow(unsafe_code)]', '#![allow(unsafe_code)]'),
        ):
            with self.subTest(changed=changed[-120:]):
                self.write(boundary.REFUSING_CREATOR_TEST, changed)
                self.assertTrue(boundary.validate(self.root))
        self.write(boundary.REFUSING_CREATOR_TEST, source)
        self.write(f"{boundary.CRATE}/src/copied_creator.rs", boundary.REFUSING_CREATOR_IMPL)
        self.assertTrue(any("copied_creator.rs" in error for error in boundary.validate(self.root)))

    def test_go_overlap_allocator_exception_is_exact_test_only_and_not_transferable(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.GO_OVERLAP_TEST).read_text(encoding="utf-8")
        self.write(boundary.GO_OVERLAP_TEST, source)
        self.assertEqual(boundary.validate(self.root), [])
        marker = boundary.GO_OVERLAP_TEST_MARKER
        for name, changed in (
            ("alloc", source.replace("unsafe { System.alloc(layout) }", "std::ptr::null_mut()", 1)),
            ("dealloc", source.replace("unsafe { System.dealloc(pointer, layout) };", "", 1)),
            ("cfg", source.replace(marker, "mod tests {\n", 1)),
            ("commented cfg", source.replace(marker, "//" + marker, 1)),
            ("global allocator", source.replace("#[global_allocator]", "", 1)),
            ("duplicate allocator", source.replace("    pub(super) fn record_before_refund() {",
                boundary.GO_OVERLAP_TEST_ALLOCATOR + "\n    pub(super) fn record_before_refund() {", 1)),
            ("allowance scope", source.replace(
                '#[allow(unsafe_code, reason = "test-only exact allocator-release observation")]',
                '#![allow(unsafe_code)]', 1)),
        ):
            with self.subTest(change=name):
                self.assertNotEqual(changed, source)
                self.write(boundary.GO_OVERLAP_TEST, changed)
                errors = boundary.validate(self.root)
                self.assertTrue(any("Go overlap test allocator changed" in error for error in errors))
                self.assertTrue(any("unreviewed unsafe code or allowance" in error for error in errors))
        for addition in ("unsafe fn extra() {}\n", "#[allow(unsafe_code)] fn extra() {}\n"):
            with self.subTest(outside_test_module=addition):
                self.write(boundary.GO_OVERLAP_TEST, source.replace(marker, addition + marker, 1))
                self.assertTrue(any("unreviewed unsafe code or allowance" in error for error in boundary.validate(self.root)))
        self.write(boundary.GO_OVERLAP_TEST, source)
        self.write(f"{boundary.CRATE}/src/copied_allocator.rs", boundary.GO_OVERLAP_TEST_ALLOCATOR)
        self.assertTrue(any("copied_allocator.rs" in error for error in boundary.validate(self.root)))

    def test_native_stack_exception_binds_guard_original_admission_and_physical_retirement(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.NATIVE_STACK).read_text(encoding="utf-8")
        self.write(boundary.NATIVE_STACK, source)
        self.assertEqual(boundary.validate(self.root), [])
        for before, after in (
            ('ProtFlags::empty()', 'ProtFlags::READ | ProtFlags::WRITE'),
            ('runtime.register(OwnerKind::Native, None)?', 'unrelated_runtime.register(OwnerKind::Native, None)?'),
            ('drop(permit);', 'std::mem::forget(permit);'),
            ('#![allow(unsafe_code)]', '#![allow(unsafe_code)]\nunsafe fn extra() {}'),
        ):
            with self.subTest(change=before):
                self.assertIn(before, source)
                self.write(boundary.NATIVE_STACK, source.replace(before, after))
                self.assertTrue(boundary.validate(self.root))

    def test_file_loader_or_arbitrary_bytes_cannot_replace_proof(self) -> None:
        for replacement in ("Component::deserialize_file(engine, path)",
                            "Component::deserialize(engine, arbitrary_bytes)"):
            with self.subTest(replacement=replacement):
                self.write(boundary.LOADER, self.loader.replace(
                    "Component::deserialize(engine, proof.bytes())", replacement))
                self.assertTrue(boundary.validate(self.root))

    def test_random_result_exception_binds_abi_zeroization_and_affine_call_retirement(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.RANDOM_RESULT).read_text(encoding="utf-8")
        self.write(boundary.RANDOM_RESULT, source)
        self.assertEqual(boundary.validate(self.root), [])
        for before, after in (
            ('type Value = Result<Vec<u8>, wit::RandomError>;', 'type Value = Vec<u8>;'),
            ('_call: Option<ProviderCall>', '_call: ()'),
            ('bytes.zeroize();', 'bytes.clear();'),
            ('self.value.linear_lower_to_memory(cx, ty, offset)', 'unrelated_lower(cx, ty, offset)'),
            ('unsafe impl Lower for Bytes', 'unsafe fn additional_site() {}\nunsafe impl Lower for Bytes'),
        ):
            with self.subTest(change=before):
                self.assertIn(before, source)
                self.write(boundary.RANDOM_RESULT, source.replace(before, after))
                self.assertTrue(boundary.validate(self.root))

    def test_child_admission_and_retirement_notification_cannot_be_bypassed(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.NATIVE_STACK_CHILD).read_text(encoding="utf-8")
        self.write(boundary.NATIVE_STACK_CHILD, source)
        self.assertEqual(boundary.validate(self.root), [])
        for before, after in (
            ('self.active.load(Ordering::Acquire) != 0', 'false'),
            ('register_from_task(OwnerKind::Native, continuation)', 'register_from_task(OwnerKind::Task, continuation)'),
            ('children.accepted >= children.maximum', 'false'),
        ):
            with self.subTest(change=before):
                self.assertIn(before, source)
                self.write(boundary.NATIVE_STACK_CHILD, source.replace(before, after))
                self.assertTrue(boundary.validate(self.root))

    def test_worker_live_parent_original_limits_and_retirement_remain_reviewed(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.NATIVE_STACK_WORKER).read_text(encoding="utf-8")
        self.write(boundary.NATIVE_STACK_WORKER, source)
        self.assertEqual(boundary.validate(self.root), [])
        for before, after in (
            ('workers.parents.len() >= workers.maximum', 'false'),
            ('.register(OwnerKind::Native, Some(parent))', '.register(OwnerKind::Native, None)'),
            ('.reserve_host_memory(self.mapped as u64)', '.reserve_host_memory(0)'),
            ('.retain(|parent| *parent != token)', '.clear()'),
            ('use super::*;', 'use super::*;\n#[allow(unsafe_code)] unsafe fn extra() {}'),
        ):
            with self.subTest(change=before):
                self.assertIn(before, source)
                self.write(boundary.NATIVE_STACK_WORKER, source.replace(before, after))
                self.assertTrue(boundary.validate(self.root))

    def test_combined_selection_requires_the_exact_proof_and_shared_original_ledgers(self) -> None:
        source = (Path(__file__).resolve().parents[2] / boundary.NATIVE_STACK_COMBINED).read_text(encoding="utf-8")
        self.write(boundary.NATIVE_STACK_COMBINED, source)
        self.assertEqual(boundary.validate(self.root), [])
        for before, after in (
            ('proof.check_before_instantiation(descriptor)?;', ''),
            ('Authentication::RustCombinedHttpVerified(_)', 'Authentication::RustSyncVerified(_)'),
            ('maximum_native.saturating_sub(1)', '8191'),
            ('Some(maximum_native)', 'Some(8192)'),
            ('            runtime,', '            unrelated_runtime,'),
            ('use super::*;', 'use super::*;\n#[allow(unsafe_code)] unsafe fn extra() {}'),
        ):
            with self.subTest(change=before):
                self.assertIn(before, source)
                self.write(boundary.NATIVE_STACK_COMBINED, source.replace(before, after))
                errors = boundary.validate(self.root)
                self.assertTrue(any("combined stack selection changed" in error for error in errors))
                if 'unsafe fn' in after:
                    self.assertTrue(any("unreviewed unsafe" in error for error in errors))
        self.write(boundary.NATIVE_STACK_COMBINED, source)
        self.assertEqual(boundary.validate(self.root), [])

    def test_allowance_cannot_expand_to_module_or_another_function(self) -> None:
        self.write(boundary.LOADER, self.loader.replace(
            "fn deserialize_authenticated(", "fn unrelated() {}\nfn deserialize_authenticated("))
        self.assertTrue(boundary.validate(self.root))

    def test_engine_update_requires_review(self) -> None:
        path = self.root / "Cargo.toml"
        path.write_text(path.read_text().replace("=48.0.8", "=48.0.0"), encoding="utf-8")
        self.assertTrue(boundary.validate(self.root))

    def test_other_workspace_member_cannot_relax_lints(self) -> None:
        for level in ("allow", "deny"):
            self.write("crates/other/Cargo.toml", f'[lints.rust]\nunsafe_code = "{level}"\n')
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
        self.assertEqual(workspace["dependencies"]["wasmtime"]["version"], "=48.0.8")
        self.assertEqual(workspace["package"]["rust-version"], "1.95.0")
        self.assertEqual(pins["rust"]["msrv"], "1.95.0")
        self.assertEqual(pins["rust"]["dependencies"]["wasmtime"], "48.0.8")
        self.assertEqual(json.loads((root / "examples/renderer-profile/profile.json").read_text())["wasmtime"], "48.0.8")
        self.assertEqual(json.loads((root / "wit/host-abi-phase4-v1.json").read_text())["wasmtimeVersion"], "48.0.8")
        # Current v5/v6/v7 descriptors advance together. Superseded matrices retain their tested runtime,
        # independently fingerprinted by test_host_abi_profile.
        for name, version in (("v2", "47.0.4"), ("v3", "47.0.4"), ("v4", "48.0.3"),
                              ("v5", "48.0.8"), ("v6", "48.0.8"), ("v7", "48.0.8")):
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
                self.assertTrue(all(p["version"] == "48.0.8" for p in family))
                cranelift = [p for p in packages if p["name"].startswith("cranelift-")]
                self.assertEqual(len(family), 14)
                self.assertEqual(len(cranelift), 13)
                self.assertTrue(all(p["version"] == "0.135.8" for p in cranelift))

    def test_real_standalone_authoring_lock_remains_in_the_workspace_closure(self) -> None:
        from tools.rust_capsule_project import locked_dependencies
        raw = locked_dependencies("security-regression-template")
        packages = boundary.tomllib.loads(raw.decode())["package"]
        self.assertEqual([p["version"] for p in packages if p["name"] == "wasmtime"], ["48.0.8"])


if __name__ == "__main__":
    unittest.main()

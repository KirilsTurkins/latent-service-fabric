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
wasmtime = {version = "=47.0.3", default-features = false}
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
        path.write_text(path.read_text().replace("=47.0.3", "=48.0.0"), encoding="utf-8")
        self.assertTrue(boundary.validate(self.root))

    def test_other_workspace_member_cannot_relax_lints(self) -> None:
        self.write("crates/other/Cargo.toml", '[lints.rust]\nunsafe_code = "allow"\n')
        self.assertTrue(boundary.validate(self.root))


if __name__ == "__main__":
    unittest.main()

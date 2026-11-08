"""The allocation-retirement observer is one exact test-only unsafe boundary."""
from pathlib import Path
import tempfile
import unittest

from tools import native_loader_boundary as boundary


class TimerAllocatorBoundary(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write("Cargo.toml", '''[workspace]
members = ["crates/latent-wasmtime"]
[workspace.lints.rust]
unsafe_code = "forbid"
[workspace.lints.clippy]
all = "warn"
[workspace.dependencies]
wasmtime = { version = "=48.0.8", default-features = false }
''')
        self.write(f"{boundary.CRATE}/Cargo.toml", '''[lints.rust]
unsafe_code = "deny"
[lints.clippy]
all = "warn"
''')
        self.write(f"{boundary.CRATE}/src/lib.rs", "#![deny(unsafe_code)]\n")
        self.write(boundary.LOADER, boundary.ALLOW + "\n" + boundary.FUNCTION + "\nfn load_failed() {}\n")
        self.source = boundary.TIMER_ALLOCATOR_TEST_PREFIX + "}\n"

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def errors(self, source):
        self.write(boundary.TIMER_ALLOCATOR_TEST, source)
        return boundary.validate(self.root)

    def test_exact_test_observer_passes_without_exempting_safe_test_edits(self):
        self.assertEqual(self.errors(self.source), [])
        self.assertEqual(self.errors(self.source + "fn ordinary_safe_control() {}\n"), [])

    def test_production_or_module_wide_allowance_is_rejected(self):
        for before, after in (
            ("#[cfg(test)]\n", ""),
            ("#[cfg(test)]", '#[cfg(feature = "development-go-timer-overlap")]'),
            ("mod tests {", "mod tests {\n    #![allow(unsafe_code)]"),
            ("#[allow(unsafe_code,", "#![allow(unsafe_code,"),
            ("mod tests {", "mod different_tests {"),
        ):
            with self.subTest(before=before):
                self.assertTrue(self.errors(self.source.replace(before, after, 1)))

    def test_system_delegation_and_nonallocating_post_free_observation_are_bound(self):
        for before, after in (
            ("System.alloc(layout)", "System.alloc_zeroed(layout)"),
            ("System.dealloc(pointer, layout)", "System.dealloc(other, layout)"),
            ("System.dealloc(pointer, layout)", "retain_instead_of_free(pointer, layout)"),
            ("WATCH.try_with", "WATCH.with"),
            ("cell.set(watch);", 'panic!("observer panic");'),
            ("cell.set(watch);", 'let _ = Vec::<u8>::with_capacity(8);'),
            ("payload: 0, billing: 0", "payload: 1, billing: 1"),
        ):
            with self.subTest(before=before):
                self.assertTrue(self.errors(self.source.replace(before, after, 1)))

    def test_duplicate_foreign_and_following_unsafe_sites_are_not_exempted(self):
        for extra in (self.source, "unsafe fn extra() {}\n",
                      "#[allow(unsafe_code)] fn extra() {}\n"):
            with self.subTest(extra=extra[:50]):
                self.assertTrue(self.errors(self.source + extra))
        self.assertEqual(self.errors(self.source), [])
        self.write(f"{boundary.CRATE}/src/copied_timer_allocator.rs", self.source)
        self.assertTrue(any("copied_timer_allocator.rs" in error for error in boundary.validate(self.root)))


if __name__ == "__main__":
    unittest.main()

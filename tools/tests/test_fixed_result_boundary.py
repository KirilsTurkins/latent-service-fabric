from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

import test_native_loader_boundary as loader_tests
import native_loader_boundary as boundary


class FixedResultBoundaryTests(unittest.TestCase):
    def test_exact_physical_completion_boundary_is_reviewed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (root / boundary.FIXED_RESULT).read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(), boundary.FIXED_RESULT_SHA256)
        self.assertEqual(boundary.validate(root), [])

    def test_new_result_shapes_and_allocation_cannot_enter_reviewed_boundary(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (root / boundary.FIXED_RESULT).read_text(encoding="utf-8")
        for before, after in (
            ("fixed_values!((), u64, wit::Token, wit::Observation);", "fixed_values!(String, (), u64, wit::Token, wit::Observation);"),
            ("!<Result<$value, wit::Error> as ComponentType>::MAY_REQUIRE_REALLOC", "true"),
            ("const MAY_REQUIRE_REALLOC: bool = R::MAY_REQUIRE_REALLOC;", "const MAY_REQUIRE_REALLOC: bool = false;"),
        ):
            with self.subTest(change=after):
                self.assertIn(before, source)
                fixture = loader_tests.NativeLoaderBoundaryTests(methodName="test_reviewed_boundary_passes")
                fixture.setUp()
                try:
                    fixture.write(boundary.FIXED_RESULT, source.replace(before, after, 1))
                    self.assertTrue(boundary.validate(fixture.root))
                finally:
                    fixture.doCleanups()

    def test_canonical_storage_and_owner_cannot_change_under_reviewed_allowance(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (root / boundary.FIXED_RESULT).read_text(encoding="utf-8")
        for before, after in (
            ("type Lower = R::Lower;", "type Lower = u64;"),
            ("_call: Option<ProviderCall>,", "_call: (),"),
            ("self.value.linear_lower_to_memory(cx, ty, offset)", "unsafe { custom_pointer_write(cx, offset) }"),
        ):
            with self.subTest(change=after):
                self.assertIn(before, source)
                fixture = loader_tests.NativeLoaderBoundaryTests(methodName="test_reviewed_boundary_passes")
                fixture.setUp()
                try:
                    fixture.write(boundary.FIXED_RESULT, source.replace(before, after, 1))
                    self.assertTrue(boundary.validate(fixture.root))
                finally:
                    fixture.doCleanups()

    def test_additional_unsafe_or_allowance_is_rejected_in_reviewed_file(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (root / boundary.FIXED_RESULT).read_text(encoding="utf-8")
        for extra in ("unsafe impl Send for HiddenOwner {}", "#[allow(unsafe_code)] fn extra() {}"):
            with self.subTest(extra=extra):
                fixture = loader_tests.NativeLoaderBoundaryTests(methodName="test_reviewed_boundary_passes")
                fixture.setUp()
                try:
                    fixture.write(boundary.FIXED_RESULT, source + "\n" + extra + "\n")
                    self.assertTrue(boundary.validate(fixture.root))
                finally:
                    fixture.doCleanups()

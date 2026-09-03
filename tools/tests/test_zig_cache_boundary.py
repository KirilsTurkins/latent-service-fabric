from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository_zig_cache", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ZigCacheBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        validator.ERRORS.clear()
        validator.WARNINGS.clear()

    def tearDown(self) -> None:
        validator.ERRORS.clear()
        validator.WARNINGS.clear()

    def test_empty_zig_timestamp_is_excluded_from_source_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("authoritative source\n", encoding="utf-8")
            timestamp = root / ".zig-cache/h/timestamp"
            timestamp.parent.mkdir(parents=True)
            timestamp.touch()

            traversed = {path.relative_to(root) for path in validator.iter_source_files(root)}
            self.assertEqual(traversed, {Path("source.txt")})

            validator.validate_nonempty_files(root)
            self.assertEqual(validator.ERRORS, [])


if __name__ == "__main__":
    unittest.main()

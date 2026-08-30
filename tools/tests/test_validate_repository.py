from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class SourceTraversalTests(unittest.TestCase):
    def setUp(self) -> None:
        validator.ERRORS.clear()
        validator.WARNINGS.clear()

    def tearDown(self) -> None:
        validator.ERRORS.clear()
        validator.WARNINGS.clear()

    def test_generated_directories_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source.json").write_text("{}", encoding="utf-8")
            for directory in validator.IGNORED_DIRECTORY_NAMES:
                generated = root / directory
                generated.mkdir(parents=True)
                (generated / "broken.json").write_text("{", encoding="utf-8")
            generated_paths = [
                root / "sdk/typescript-client/dist",
                root / "sdk/java-client/build",
                root / "sdk/dotnet/Latent.Sdk/bin",
                root / "sdk/dotnet/Latent.Sdk/obj",
            ]
            for generated in generated_paths:
                generated.mkdir(parents=True)
                (generated / "broken.json").write_text("{", encoding="utf-8")

            validator.validate_json(root)
            self.assertEqual(validator.ERRORS, [])
            self.assertEqual(
                {path.relative_to(root) for path in validator.iter_source_files(root)},
                {Path("source.json")},
            )

    def test_authoritative_source_remains_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/build"
            source.mkdir(parents=True)
            (source / "broken.json").write_text("{", encoding="utf-8")

            validator.validate_json(root)
            self.assertEqual(len(validator.ERRORS), 1)
            self.assertIn("src/build/broken.json", validator.ERRORS[0])

    def test_documentation_svg_requires_accessibility_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/valid.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"title description\">
  <title id=\"title\">Valid diagram</title>
  <desc id=\"description\">A valid accessible SVG.</desc>
  <rect width=\"10\" height=\"10\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertEqual(validator.ERRORS, [])

    def test_documentation_svg_rejects_active_or_incomplete_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/unsafe.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"presentation\" aria-labelledby=\"title missing\">
  <title id=\"title\">Unsafe diagram</title>
  <script>alert('no')</script>
  <use href=\"https://example.invalid/external.svg#shape\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertTrue(
                any("aria-labelledby references missing ID(s) missing" in error for error in validator.ERRORS)
            )
            self.assertTrue(any("role must be img" in error for error in validator.ERRORS))
            self.assertTrue(any("missing non-empty <desc>" in error for error in validator.ERRORS))
            self.assertTrue(any("disallowed <script>" in error for error in validator.ERRORS))
            self.assertTrue(any("non-local reference in href" in error for error in validator.ERRORS))

    def test_documentation_svg_labels_reference_its_title_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/mislabelled.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"title shape\">
  <title id=\"title\">Mislabelled diagram</title>
  <desc id=\"description\">Its description is not announced.</desc>
  <rect id=\"shape\" width=\"10\" height=\"10\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertTrue(
                any(
                    "aria-labelledby must reference a non-empty <desc>" in error
                    for error in validator.ERRORS
                )
            )


if __name__ == "__main__":
    unittest.main()

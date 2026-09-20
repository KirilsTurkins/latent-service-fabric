from __future__ import annotations

import importlib.util
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

VALID_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"
    role="img" aria-labelledby="title description">
  <title id="title">Diagram</title>
  <desc id="description">An accessible diagram.</desc>
  <rect id="shape" width="10" height="10"/>
</svg>"""
RELATIVE_PATH = "docs/assets/nested/diagram.svg"
ROOTS = (
    PurePosixPath("/checkout"),
    PureWindowsPath("C:/checkout"),
    PureWindowsPath("//server/share/checkout"),
)


class SvgDiagnosticPathTests(unittest.TestCase):
    def setUp(self) -> None:
        validator.ERRORS.clear()
        self.addCleanup(validator.ERRORS.clear)

    def assert_diagnostics(self, source: str | Exception, expected: list[str]) -> None:
        # Supply path flavours independently of the host; XML parsing and native
        # filesystem traversal remain covered by SourceTraversalTests.
        for root in ROOTS:
            with self.subTest(root=str(root), source=source):
                validator.ERRORS.clear()
                path = root / RELATIVE_PATH
                with patch.object(validator, "files_with_suffix", return_value=[path]) as files:
                    with patch.object(validator.ElementTree, "parse") as parse:
                        if isinstance(source, Exception):
                            parse.side_effect = source
                        else:
                            parse.return_value = ElementTree.ElementTree(ElementTree.fromstring(source))
                        validator.validate_svg(root)
                files.assert_called_once_with(".svg", root)
                # Only diagnostics are normalized, not the path passed to I/O.
                parse.assert_called_once_with(path)
                self.assertEqual(validator.ERRORS, expected)

    def test_valid_document_has_no_diagnostics(self) -> None:
        self.assert_diagnostics(VALID_SVG, [])

    def test_duplicate_id_path_uses_forward_slashes(self) -> None:
        self.assert_diagnostics(
            VALID_SVG.replace('id="shape"', 'id="title"'),
            [f"SVG contains duplicate ID title: {RELATIVE_PATH}"],
        )

    def test_invalid_root_path_uses_forward_slashes(self) -> None:
        self.assert_diagnostics("<html/>", [f"SVG root must be <svg>: {RELATIVE_PATH}"])

    def test_safety_and_accessibility_paths_use_forward_slashes(self) -> None:
        source = """<svg role="presentation" aria-labelledby="title missing">
  <title id="title">Unsafe diagram</title>
  <script onclick="unsafe()">unsafe()</script>
  <use href="https://example.invalid/external.svg#shape"
       style="filter: url(https://example.invalid/filter.svg#filter)"/>
  <style>@import 'https://example.invalid/style.css';</style>
</svg>"""
        self.assert_diagnostics(source, [
            f"SVG missing viewBox: {RELATIVE_PATH}",
            f"SVG role must be img: {RELATIVE_PATH}",
            f"SVG aria-labelledby references missing ID(s) missing: {RELATIVE_PATH}",
            f"SVG missing non-empty <desc>: {RELATIVE_PATH}",
            f"SVG contains disallowed <script>: {RELATIVE_PATH}",
            f"SVG contains event handler onclick: {RELATIVE_PATH}",
            f"SVG contains non-local reference in href: {RELATIVE_PATH}",
            f"SVG contains non-local URL reference: {RELATIVE_PATH}",
            f"SVG contains external CSS import: {RELATIVE_PATH}",
        ])

    def test_parse_and_io_error_paths_use_forward_slashes(self) -> None:
        for error in (ElementTree.ParseError("malformed XML"), OSError("unreadable SVG")):
            self.assert_diagnostics(error, [f"invalid SVG {RELATIVE_PATH}: {error}"])


if __name__ == "__main__":
    unittest.main()

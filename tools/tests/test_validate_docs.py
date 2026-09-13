from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "validate_docs", Path(__file__).resolve().parents[1] / "validate_docs.py"
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"
role="img" aria-labelledby="title description">
<title id="title">Diagram</title><desc id="description">Its description.</desc>
<rect id="shape" width="10" height="10"/>{extra}</svg>'''


class DocumentationValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tracked: set[str] = set()

    def write(self, name: str, text: str, *, tracked: bool = True) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if tracked:
            self.tracked.add(name)
        return path

    def report(self) -> dict:
        return validator.validate_docs(self.root, self.tracked)

    def test_valid_local_links_encoded_names_references_and_svg_fragment(self) -> None:
        self.write("README.md", '''# Intro
[directory](docs/)
[second](docs/Usage%20Guide.md#hello-world-1)
[third](<docs/Usage Guide.md#hello-world-1-1> "title")
[Unicode](docs/Usage%20Guide.md#caf%C3%A9)
![diagram](docs/diagram.svg#shape)
[reference][guide]
[guide]: docs/Usage%20Guide.md#named-anchor "guide"
''')
        self.write("docs/Usage Guide.md", '''# Hello, world!
# Hello, world!
# Hello-world-1
Café
====
<a id="named-anchor"></a>
''')
        self.write("docs/diagram.svg", SVG.format(extra=""))
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["documents"], 2)
        self.assertEqual(report["svgs"], 1)
        self.assertGreaterEqual(report["anchors"], 5)

    def test_duplicate_slug_collision_matches_github(self) -> None:
        self.write("README.md", "# Repeat\n# Repeat-1\n# Repeat\n[third](#repeat-2)\n")
        self.assertEqual(self.report()["errors"], [])
        self.write("README.md", "# Repeat\n# Repeat-1\n# Repeat\n[absent](#repeat-3)\n")
        self.assertIn("missing anchor", self.report()["errors"][0])

    def test_code_examples_are_not_links_or_headings(self) -> None:
        self.write("README.md", '''# Real
`[inline](missing-inline.md)`
````markdown
```sh
[example](missing-fenced.md)
# Fake heading
```
````
> ~~~markdown
> [quoted](missing-quote.md)
> ~~~
<!-- [comment](missing-comment.md) -->
[actual](#real)
''')
        report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["local_links"], 1)
        self.write("other.md", "[not a heading](README.md#fake-heading)\n")
        self.assertIn("missing anchor", self.report()["errors"][0])

    def test_shorter_or_different_fence_does_not_close_block(self) -> None:
        for text in ["````md\ntext\n```\n", "~~~md\ntext\n```\n"]:
            with self.subTest(text=text):
                self.write("README.md", text)
                self.assertEqual(len(self.report()["errors"]), 1)
                self.assertIn("README.md:1: unclosed", self.report()["errors"][0])

    def test_missing_case_wrong_and_untracked_destinations_fail(self) -> None:
        self.write("docs/Present.md", "# Present\n")
        self.write("docs/untracked.md", "# Untracked\n", tracked=False)
        self.write("README.md", "[missing](docs/missing.md)\n[case](docs/present.md)\n[untracked](docs/untracked.md)\n")
        errors = self.report()["errors"]
        self.assertEqual(len(errors), 3)
        self.assertTrue(all("missing or case-wrong" in error for error in errors))

    def test_percent_encoded_parent_cannot_escape_repository(self) -> None:
        self.write("README.md", "[escape](%2e%2e/outside.md)\n[bad](bad%zz.md)\n")
        errors = self.report()["errors"]
        self.assertEqual(len(errors), 2)
        self.assertIn("missing or case-wrong", errors[0])
        self.assertIn("invalid local URL", errors[1])

    def test_link_with_balanced_parentheses_and_title(self) -> None:
        self.write("docs/plan(v1).md", "# The plan\n")
        self.write("README.md", '[plan](docs/plan(v1).md#the-plan "version one")\n')
        self.assertEqual(self.report()["errors"], [])
        self.assertEqual(self.report()["anchors"], 1)

    def test_linked_image_checks_outer_destination_and_reference_once(self) -> None:
        self.write("README.md", "[![diagram](diagram.svg)](missing.md)\n[ref][known]\n[known]: diagram.svg\n")
        self.write("diagram.svg", SVG.format(extra=""))
        report = self.report()
        self.assertEqual(report["local_links"], 3)
        self.assertEqual(len(report["errors"]), 1)
        self.assertIn("missing.md", report["errors"][0])

    def test_missing_markdown_and_svg_anchors_fail(self) -> None:
        self.write("README.md", "# Existing\n[missing](#absent)\n![missing shape](diagram.svg#absent)\n")
        self.write("diagram.svg", SVG.format(extra=""))
        errors = self.report()["errors"]
        self.assertEqual(len(errors), 2)
        self.assertIn("missing anchor", errors[0])
        self.assertIn("missing SVG anchor", errors[1])

    def test_shared_svg_rules_reject_script_and_missing_accessibility(self) -> None:
        self.write("README.md", "![diagram](diagram.svg)\n")
        self.write("diagram.svg", SVG.format(extra="<script>alert(1)</script>"))
        self.assertTrue(any("disallowed <script>" in error for error in self.report()["errors"]))
        self.write("diagram.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertTrue(any("aria-labelledby" in error for error in self.report()["errors"]))

    def test_only_tracked_documents_are_read_and_evidence_is_not_parsed(self) -> None:
        self.write("README.md", "[evidence](benchmarks/result.json)\n")
        self.write("benchmarks/result.json", "deliberately not JSON")
        self.write("untracked.md", "```unclosed\n", tracked=False)
        self.write("untracked.svg", "invalid XML", tracked=False)
        read_text = Path.read_text

        def guarded(path: Path, *args, **kwargs):
            self.assertNotEqual(path.suffix, ".json", "evidence contents must not be read")
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded):
            report = self.report()
        self.assertEqual(report["errors"], [])
        self.assertEqual((report["documents"], report["svgs"]), (1, 0))

    def test_dangling_symlink_cannot_satisfy_tracked_link(self) -> None:
        self.write("README.md", "[dangling](dangling.txt)\n")
        link = self.root / "dangling.txt"
        try:
            link.symlink_to(self.root / "missing.txt")
        except OSError:
            self.skipTest("Host does not permit creating symlinks")
        self.tracked.add("dangling.txt")
        self.assertIn("missing or case-wrong", self.report()["errors"][0])

    def test_tracked_inventory_uses_nul_records_and_disables_auto_gc(self) -> None:
        with patch.object(validator.subprocess, "check_output", return_value=b"a b.md\0docs/x.md\0") as call:
            self.assertEqual(validator.tracked_files(self.root), {"a b.md", "docs/x.md"})
        self.assertEqual(call.call_args.args[0], ["git", "-c", "gc.auto=0", "ls-files", "-z"])


if __name__ == "__main__":
    unittest.main()

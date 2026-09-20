"""Bounded, offline regression coverage for the shared SVG resource contract."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from tools import svg_references as references
from tools import validate_docs as docs
from tools import validate_repository as repository

ROOT = Path(__file__).resolve().parents[2]
XLINK = "{http://www.w3.org/1999/xlink}href"


def diagram() -> ET.Element:
    svg = ET.Element("svg", {"viewBox": "0 0 10 10", "role": "img", "aria-labelledby": "title desc"})
    ET.SubElement(svg, "title", {"id": "title"}).text = "Reference regression"
    ET.SubElement(svg, "desc", {"id": "desc"}).text = "A self-contained diagram."
    return svg


class CssTokenTests(unittest.TestCase):
    def values(self, text: str) -> list[str]:
        return [value for _, value in references.css_references(text)]

    def test_quoted_unquoted_case_and_ascii_whitespace(self) -> None:
        for value in ("url(#paint)", "URL( #paint )", "url(\t'#paint'\r\n)", 'uRl( "#paint" )'):
            with self.subTest(value=value):
                self.assertEqual(self.values(value), ["#paint"])

    def test_multiple_and_nested_functions_preserve_source_offsets(self) -> None:
        text = ".a { filter: url(#first) blur(2px) var(--filter, URL('#second')); }"
        self.assertEqual(list(references.css_references(text)),
                         [(text.index("url("), "#first"), (text.index("URL("), "#second")])

    def test_comments_and_non_url_strings_are_inert(self) -> None:
        text = '''/* url(https://example.invalid) @import "bad.css"; \\75rl( */
        .url /* ordinary class */ { content: "url(https://example.invalid) @import";
        font-family: 'Example Font'; fill: /* before */ url(#paint) /* after */; }'''
        self.assertEqual(self.values(text), ["#paint"])
        self.assertEqual(self.values('"/*" url(#paint) "*/"'), ["#paint"])
        self.assertEqual(self.values("myurl(#not-a-reference) --url(#also-not)"), [])

    def test_comments_never_join_identifier_tokens(self) -> None:
        self.assertEqual(self.values("u/**/rl(#not-a-url)"), [])
        for value in ("url (#paint)", "url/**/(#paint)", "url \t/**/ \n(#paint)"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(references.CssReferenceError, "immediately"):
                    self.values(value)

    def test_comments_inside_unquoted_urls_are_not_stripped(self) -> None:
        for value in ("url(/* comment */#paint)", "url(#paint/**/)", "url('#paint'/**/)"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(references.CssReferenceError, "comments inside"):
                    self.values(value)
        # Inside a quoted URL these are literal string characters, not a comment.
        self.assertEqual(self.values("url('#paint/*literal*/')"), ["#paint/*literal*/"])

    def test_all_css_escape_spellings_are_explicitly_rejected(self) -> None:
        for value in (r"u\72l(#paint)", r"\75rl(#paint)", r"url(\23paint)",
                      r"url('#pa\69nt')", r"@\69mport 'x'", "url('#paint\\\n')",
                      r".\61 { fill: red }", r"content: '\75rl(hidden)'"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(references.CssReferenceError, "escapes are unsupported"):
                    self.values(value)

    def test_import_is_rejected_with_any_literal_target_or_case(self) -> None:
        for value in ('@import "other.css";', "@IMPORT url(#paint);", "@import/**/'other.css';"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(references.CssReferenceError, "external CSS import"):
                    self.values(value)

    def test_indirect_string_resource_functions_are_not_accepted(self) -> None:
        for name in references.INDIRECT_RESOURCE_FUNCTIONS:
            with self.subTest(name=name):
                with self.assertRaisesRegex(references.CssReferenceError, "unsupported; use url"):
                    self.values(f'{name}("https://example.invalid/a")')

    def test_malformed_tokens_fail_without_browser_style_recovery(self) -> None:
        for value in ("url(", "url(#paint", "url('#paint)", 'url("#paint\n")',
                      "url(#paint extra)", "url('#paint' extra)", "url((#paint))",
                      "url(#pa'int)", "/* unterminated", "url(#paint))", ".a { fill: red;",
                      ".a { fill: red; ]}", "url(\0)", 'content: "\x01"'):
            with self.subTest(value=value):
                with self.assertRaises(references.CssReferenceError):
                    self.values(value)

    def test_deep_input_uses_no_recursive_parser(self) -> None:
        self.assertEqual(self.values("(" * 2048 + "url(#paint)" + ")" * 2048), ["#paint"])
        with self.assertRaises(references.CssReferenceError):
            self.values("(" * 2048 + "url(#paint)")


class SvgReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        repository.ERRORS.clear()
        repository.WARNINGS.clear()
        self.addCleanup(repository.ERRORS.clear)
        self.addCleanup(repository.WARNINGS.clear)

    def write(self, svg: ET.Element, name: str = "docs/assets/case.svg") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(svg).write(path, encoding="utf-8")
        return path

    def check(self) -> list[str]:
        repository.ERRORS.clear()
        repository.validate_svg(self.root)
        errors = list(repository.ERRORS)
        # Exercise the actual documentation entry point, not a copy of its rules.
        paths = [path.relative_to(self.root).as_posix() for path in self.root.rglob("*.svg")]
        report = docs.validate_docs(self.root, paths, require_documents=False)
        self.assertEqual(report["errors"], errors)
        return errors

    def test_five_original_reproductions(self) -> None:
        for body, expected in (
            ('<path marker-end="url(#arrow)"/><marker id="arrow"/>', False),
            ('<path marker-end="url(#absent)"/>', True),
            ('<style>.a { filter: url(#absent) }</style>', True),
            ('<style>.a { filter: url(https://example.invalid/filter.svg#f) }</style>', True),
            ('<path filter="url(https://example.invalid/filter.svg#f)"/>', True),
        ):
            with self.subTest(body=body):
                svg = diagram()
                svg.extend(ET.fromstring(f"<g>{body}</g>"))
                self.write(svg)
                self.assertEqual(bool(self.check()), expected)

    def test_all_resource_locations_reject_external_references(self) -> None:
        attributes = ("href", XLINK, "src", "fill", "stroke", "filter", "clip-path", "mask",
                      "marker-start", "marker-mid", "marker-end", "cursor", "style", "stylesheet")
        targets = ("https://example.invalid/x#paint", "//example.invalid/x#paint",
                   "data:image/svg+xml,paint", "other.svg#paint", "/image.svg#paint",
                   "file:///tmp/image.svg#paint", "javascript:alert(1)")
        for attribute in attributes:
            for target in targets:
                with self.subTest(attribute=attribute, target=target):
                    svg = diagram()
                    ET.SubElement(svg, "linearGradient", {"id": "paint"})
                    css = f'fill: url("{target}");'
                    if attribute == "stylesheet":
                        ET.SubElement(svg, "style").text = f".a {{ {css} }}"
                    else:
                        value = target if attribute in ("href", XLINK, "src") else (
                            css if attribute == "style" else f'url("{target}")')
                        ET.SubElement(svg, "use", {attribute: value})
                    self.write(svg)
                    errors = self.check()
                    self.assertEqual(len(errors), 1)
                    self.assertIn(target, errors[0])
                    self.assertIn("non-local reference", errors[0])
                    self.assertIn(str(Path("docs/assets/case.svg")), errors[0])

    def test_multiple_forward_resources_and_namespaced_links_pass(self) -> None:
        svg = diagram()
        ET.SubElement(svg, "path", {"fill": "url( '#paint' )", "filter": "url(#shadow)",
                                  "clip-path": 'url( "#clip" )', "mask": "url(#mask)",
                                  "marker-end": "url(#arrow)"})
        ET.SubElement(svg, "use", {XLINK: " #shape ", "href": "#shape"})
        ET.SubElement(svg, "style").text = ".a { filter: url(#shadow) url('#shadow'); fill: URL(#paint) }"
        for tag, identifier in (("linearGradient", "paint"), ("filter", "shadow"),
                                ("clipPath", "clip"), ("mask", "mask"),
                                ("marker", "arrow"), ("path", "shape")):
            ET.SubElement(svg, tag, {"id": identifier})
        self.write(svg)
        self.assertEqual(self.check(), [])

    def test_empty_missing_encoded_and_whitespace_fragments_are_rejected(self) -> None:
        for value in ("", "#", "#missing", "#pa%69nt", "#pa int", "#paint\\", "#svgView(viewBox(0,0,1,1))"):
            for attribute in ("href", XLINK, "filter", "style", "stylesheet"):
                with self.subTest(value=value, attribute=attribute):
                    svg = diagram()
                    # Even a matching literal ID cannot authorize URI/CSS decoding.
                    ET.SubElement(svg, "path", {"id": value.removeprefix("#") if value != "#missing" else "paint"})
                    css = f"filter: url('{value}')"
                    if attribute == "stylesheet":
                        ET.SubElement(svg, "style").text = f".a {{ {css} }}"
                    else:
                        ET.SubElement(svg, "use", {attribute: value if attribute in ("href", XLINK) else (
                            css if attribute == "style" else f"url('{value}')")})
                    self.write(svg)
                    errors = self.check()
                    self.assertTrue(errors)
                    self.assertTrue(any("resource" in error or "CSS escapes" in error for error in errors))

    def test_every_missing_reference_is_reported_in_order(self) -> None:
        svg = diagram()
        ET.SubElement(svg, "path", {"style": "fill:url(#one); filter:url(#two) url(#three)"})
        self.write(svg)
        errors = self.check()
        self.assertEqual(len(errors), 3)
        for error, value in zip(errors, ("#one", "#two", "#three"), strict=True):
            self.assertIn(value, error)
            self.assertIn("missing ID", error)
        self.assertEqual(self.check(), errors)

    def test_ids_are_case_sensitive_and_scoped_per_file(self) -> None:
        first = diagram()
        ET.SubElement(first, "path", {"id": "paint", "fill": "url(#paint)"})
        self.write(first, "docs/assets/a.svg")
        second = diagram()
        ET.SubElement(second, "path", {"fill": "url(#paint)"})
        self.write(second, "docs/assets/b.svg")
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn(str(Path("docs/assets/b.svg")), errors[0])
        ET.SubElement(second, "linearGradient", {"id": "paint"})
        self.write(second, "docs/assets/b.svg")
        self.assertEqual(self.check(), [])
        second[-1].set("id", "Paint")
        self.write(second, "docs/assets/b.svg")
        self.assertEqual(len(self.check()), 1)

    def test_comments_cdata_and_namespaced_style_have_the_same_policy(self) -> None:
        path = self.root / "case.svg"
        path.write_text('''<s:svg xmlns:s="http://www.w3.org/2000/svg" viewBox="0 0 1 1"
          role="img" aria-labelledby="t d"><s:title id="t">Title</s:title><s:desc id="d">Description</s:desc>
          <s:style><![CDATA[/* url(https://ignored.invalid) @import 'ignored'; */
          .a { filter: url('#missing') }]]></s:style></s:svg>''', encoding="utf-8")
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("#missing", errors[0])
        self.assertIn("<style>", errors[0])

    def test_each_css_source_fails_closed_and_other_sources_continue(self) -> None:
        svg = diagram()
        ET.SubElement(svg, "path", {"style": "filter:url('#unfinished)", "fill": "url(#missing)"})
        ET.SubElement(svg, "style").text = "/* unterminated"
        ET.SubElement(svg, "style").text = ".a { fill:url(#other) }"
        self.write(svg)
        (self.root / "bad.svg").write_text("<broken", encoding="utf-8")
        other = diagram()
        ET.SubElement(other, "use", {XLINK: "#absent"})
        self.write(other, "docs/assets/other.svg")
        errors = self.check()
        self.assertEqual(len(errors), 6)
        for token in ("unterminated CSS string", "#missing", "unterminated CSS comment", "#other", "invalid SVG", "#absent"):
            self.assertTrue(any(token in error for error in errors), token)

    def test_xml_base_cannot_redirect_fragment_resolution(self) -> None:
        svg = diagram()
        svg.set("{http://www.w3.org/XML/1998/namespace}base", "https://example.invalid/")
        ET.SubElement(svg, "use", {"id": "shape", "href": "#shape"})
        self.write(svg)
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("xml:base", errors[0])

    def test_non_css_metadata_is_not_interpreted_as_css(self) -> None:
        svg = diagram()
        ET.SubElement(svg, "text", {"aria-label": "User's url( example", "data-note": "/* unfinished"})
        self.write(svg)
        self.assertEqual(self.check(), [])

    def test_existing_safety_and_accessibility_failures_are_retained(self) -> None:
        svg = diagram()
        svg.set("role", "presentation")
        svg.set("aria-labelledby", "title absent")
        for tag in sorted(repository.SVG_UNSAFE_ELEMENTS):
            ET.SubElement(svg, tag)
        ET.SubElement(svg, "path", {"id": "title", "onLoad": "bad()", "href": "https://example.invalid"})
        self.write(svg)
        errors = self.check()
        for token in ("duplicate ID title", "role must be img", "references missing ID(s) absent",
                      "must reference a non-empty <desc>", "event handler onLoad", "non-local reference in href"):
            self.assertTrue(any(token in error for error in errors), token)
        for tag in repository.SVG_UNSAFE_ELEMENTS:
            self.assertTrue(any(f"disallowed <{tag}>" in error for error in errors), tag)

    def test_resource_validation_never_fetches_or_executes_a_reference(self) -> None:
        svg = diagram()
        ET.SubElement(svg, "style").text = '.a { filter:url("https://example.invalid/x#f") }'
        self.write(svg)
        with patch("socket.socket", side_effect=AssertionError("network access")), \
                patch("subprocess.Popen", side_effect=AssertionError("process execution")):
            self.assertEqual(len(self.check()), 1)

    def test_current_documentation_assets_pass_without_byte_changes(self) -> None:
        assets = sorted((ROOT / "docs/assets").glob("*.svg"))
        self.assertIn(ROOT / "docs/assets/phase2-delivery-boundary.svg", assets)
        before = {path: path.read_bytes() for path in assets}
        self.assertEqual(docs.svg_errors(ROOT, assets), [])
        self.assertEqual({path: path.read_bytes() for path in assets}, before)
        # Ensure this is not just a corpus of trivial empty SVGs.
        reference_attributes = {key for path in assets for node in ET.parse(path).iter()
                                for key, value in node.attrib.items() if "url(#" in value}
        self.assertTrue({"fill", "filter", "marker-end"} <= reference_attributes)

    def test_real_asset_missing_definitions_fail_on_both_paths(self) -> None:
        source = (ROOT / "docs/assets/phase2-delivery-boundary.svg").read_bytes()
        for kind in ("background", "arrow", "shadow"):
            with self.subTest(kind=kind):
                svg = ET.fromstring(source)
                identifier = f"phase2-delivery-{kind}"
                definition = next(node for node in svg.iter() if node.get("id") == identifier)
                definition.set("id", identifier + "-renamed")
                self.write(svg)
                errors = self.check()
                self.assertTrue(errors)
                self.assertTrue(all(identifier in error and "missing ID" in error for error in errors))
        self.assertEqual((ROOT / "docs/assets/phase2-delivery-boundary.svg").read_bytes(), source)

    def test_xml_character_references_are_checked_after_xml_decoding(self) -> None:
        path = self.root / "case.svg"
        prefix = ET.tostring(diagram(), encoding="unicode").removesuffix("</svg>")
        for body, bad in (("<path fill=\"&#x75;rl(&#x23;paint)\"/><linearGradient id=\"paint\"/>", False),
                          ("<use href=\"&#x68;ttps://example.invalid/image.svg\"/>", True),
                          ("<style>.a { filter: &#x75;rl(&#x23;missing) }</style>", True)):
            with self.subTest(body=body):
                path.write_text(prefix + body + "</svg>", encoding="utf-8")
                self.assertEqual(bool(self.check()), bad)

    def test_animation_values_retain_the_external_url_tripwire(self) -> None:
        for attribute in ("from", "to", "by", "values"):
            with self.subTest(attribute=attribute):
                svg = diagram()
                ET.SubElement(svg, "animate", {"attributeName": "fill",
                                              attribute: "url(https://example.invalid/paint.svg#p)"})
                self.write(svg)
                errors = self.check()
                self.assertEqual(len(errors), 1)
                self.assertIn("non-local reference", errors[0])

    def test_each_supported_css_attribute_uses_the_shared_policy(self) -> None:
        for attribute in sorted(references.CSS_ATTRIBUTES):
            with self.subTest(attribute=attribute):
                svg = diagram()
                ET.SubElement(svg, "path", {attribute: "url(#missing)"})
                self.write(svg)
                errors = self.check()
                self.assertEqual(len(errors), 1)
                self.assertIn("missing ID", errors[0])

    def test_docs_cli_rejects_then_accepts_a_repaired_resource(self) -> None:
        required = ("README.md", "ARCHITECTURE.md", "VALIDATION.md", "docs/architecture/overview.md",
                    "docs/api-surface.md", "docs/development/build-foundation.md", "docs/development/toolchain.md",
                    "docs/svg-style.md", "docs/testing/invariants.md",
                    "adr/0005-forbid-per-service-idle-execution-allocation.md")
        for name in required:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Fixture\n", encoding="utf-8")
        svg = diagram()
        ET.SubElement(svg, "path", {"filter": "url(#missing)"})
        self.write(svg)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True, capture_output=True)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        command = [sys.executable, str(ROOT / "tools/validate_docs.py"), "--root", str(self.root)]
        failed = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("#missing", failed.stdout)
        ET.SubElement(svg, "filter", {"id": "missing"})
        self.write(svg)
        passed = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)


if __name__ == "__main__":
    unittest.main()

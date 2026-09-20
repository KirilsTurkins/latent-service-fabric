from __future__ import annotations

from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import validate_issue_forms as forms


ROOT = Path(__file__).resolve().parents[2]


class IssueFormValidationTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def minimal_form(self, extra: str = "") -> str:
        return (
            "name: Test form\n"
            "description: A bounded test form\n"
            "body:\n"
            "  - type: input\n"
            "    id: subject\n"
            "    attributes:\n"
            "      label: Subject\n"
            "    validations:\n"
            "      required: true\n"
            + extra
        )

    def test_repository_forms_pass_with_the_current_optional_inventory(self) -> None:
        expected = sum((ROOT / path).exists() for path in (*forms.KNOWN_FORMS, forms.CONFIG_PATH))
        self.assertEqual(forms.validate_repository(ROOT), expected)

    def test_valid_optional_config_uses_https_contact_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(
                root,
                str(forms.CONFIG_PATH),
                "blank_issues_enabled: false\n"
                "contact_links:\n"
                "  - name: Security reports\n"
                "    url: https://github.com/KirilsTurkins/latent-service-fabric/security\n"
                "    about: Use the private security reporting path.\n",
            )
            self.assertEqual(forms.validate_repository(root), 1)

    def test_malformed_duplicate_and_multiple_documents_are_rejected(self) -> None:
        cases = {
            "malformed": "name: [\n",
            "duplicate": self.minimal_form().replace(
                "description: A bounded test form\n",
                "description: A bounded test form\ndescription: duplicate\n",
            ),
            "multiple": self.minimal_form() + "---\nname: second\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content in cases.items():
                path = self.write(root, f"{name}.yml", content)
                with self.subTest(name=name), self.assertRaises(forms.ValidationError):
                    forms.read_yaml(path)

    def test_alias_anchor_tag_and_directive_features_are_rejected(self) -> None:
        cases = {
            "alias": "name: &shared Test\ndescription: *shared\nbody: []\n",
            "tag": "name: !example Test\ndescription: Test\nbody: []\n",
            "directive": "%YAML 1.1\n---\nname: Test\ndescription: Test\nbody: []\n",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content in cases.items():
                path = self.write(root, f"{name}.yml", content)
                with self.subTest(name=name), self.assertRaisesRegex(
                    forms.ValidationError, "unsupported-yaml-feature"
                ):
                    forms.read_yaml(path)

    def test_duplicate_ids_unknown_attributes_and_string_boolean_are_rejected(self) -> None:
        duplicate = self.minimal_form(
            "  - type: textarea\n"
            "    id: subject\n"
            "    attributes:\n"
            "      label: Details\n"
        )
        bad_attribute = self.minimal_form().replace(
            "      label: Subject\n", "      label: Subject\n      options: [one]\n"
        )
        string_boolean = self.minimal_form().replace("required: true", 'required: "true"')
        for name, content in {
            "duplicate-id": duplicate,
            "bad-attribute": bad_attribute,
            "string-boolean": string_boolean,
        }.items():
            with self.subTest(name=name):
                value = forms.read_yaml(self._temporary_yaml(content))
                with self.assertRaises(forms.ValidationError):
                    forms.validate_issue_form(value)

    def _temporary_yaml(self, content: str) -> Path:
        temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".yml", delete=False)
        temporary.write(content)
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return Path(temporary.name)

    def test_supported_subset_requires_user_input_and_valid_ids(self) -> None:
        only_markdown = (
            "name: Test form\n"
            "description: Test description\n"
            "body:\n"
            "  - type: markdown\n"
            "    attributes:\n"
            "      value: Context\n"
        )
        bad_id = self.minimal_form().replace("id: subject", "id: subject.value")
        unknown_type = self.minimal_form().replace("type: input", "type: dropdown")
        for content in (only_markdown, bad_id, unknown_type):
            with self.subTest(content=content.splitlines()[3]):
                with self.assertRaises(forms.ValidationError):
                    forms.validate_issue_form(forms.read_yaml(self._temporary_yaml(content)))

    def test_size_depth_and_unsafe_file_types_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            oversized = self.write(root, "oversized.yml", "x" * (forms.MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(forms.ValidationError, "file-size-limit"):
                forms.read_yaml(oversized)

            deep = "value:\n" + "".join("  " * level + "-\n" for level in range(forms.MAX_DEPTH + 2))
            path = self.write(root, "deep.yml", deep)
            with self.assertRaisesRegex(forms.ValidationError, "yaml-depth-limit"):
                forms.read_yaml(path)

            target = self.write(root, "target.yml", self.minimal_form())
            link = root / "link.yml"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(forms.ValidationError, "unsafe-file-type"):
                forms.read_yaml(link)

    def test_config_rejects_string_boolean_and_non_https_or_credentialed_urls(self) -> None:
        invalid = [
            'blank_issues_enabled: "false"\n',
            "contact_links:\n  - name: Help\n    url: http://example.com/help\n    about: Help\n",
            "contact_links:\n  - name: Help\n    url: https://user@example.com/help\n    about: Help\n",
        ]
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaises(forms.ValidationError):
                    forms.validate_config(forms.read_yaml(self._temporary_yaml(content)))


    def test_flow_depth_and_node_budgets_apply_before_construction(self) -> None:
        cases = {
            "yaml-depth-limit": "[" * 1000 + "0" + "]" * 1000,
            "yaml-node-limit": "[" + ",".join("[" + ",".join(["0"] * 128) + "]" for _ in range(9)) + "]",
        }
        for reason, content in cases.items():
            path = self._temporary_yaml(content)
            with self.subTest(reason=reason), patch.object(
                forms.UniqueSafeLoader, "construct_document", side_effect=AssertionError("construction started")
            ), self.assertRaisesRegex(forms.ValidationError, reason):
                forms.read_yaml(path)

    def test_depth_collection_node_and_string_boundaries(self) -> None:
        boundary = "[" * forms.MAX_DEPTH + "x" + "]" * forms.MAX_DEPTH
        forms.read_yaml(self._temporary_yaml(boundary))
        with patch.object(forms, "MAX_NODES", 3):
            self.assertEqual(forms.read_yaml(self._temporary_yaml("[1, 2]")), [1, 2])
            with self.assertRaisesRegex(forms.ValidationError, "yaml-node-limit"):
                forms.read_yaml(self._temporary_yaml("[1, 2, 3]"))
        for content, reason in (
            ("[" + ",".join(["0"] * (forms.MAX_COLLECTION_ITEMS + 1)) + "]", "yaml-collection-limit"),
            ("value: " + "x" * (forms.MAX_STRING_BYTES + 1), "yaml-string-limit"),
            ("value: " + "é" * (forms.MAX_STRING_BYTES // 2 + 1), "yaml-string-limit"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(forms.ValidationError, reason):
                forms.read_yaml(self._temporary_yaml(content))

    def test_document_and_scalar_errors_fail_cleanly_at_the_cli(self) -> None:
        cases = ("", "---\n{}\n---\n{}\n", "value: " + "9" * 5000, 'value: "\\uD800"')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for content in cases:
                self.write(root, str(forms.KNOWN_FORMS[0]), content)
                error = io.StringIO()
                with self.subTest(content=content[:20]), redirect_stderr(error):
                    self.assertEqual(forms.main(["--repo", str(root)]), 1)
                self.assertIn("Issue-form validation failed:", error.getvalue())
                self.assertNotIn("Traceback", error.getvalue())

    def test_nested_duplicates_and_non_string_mapping_keys_fail_closed(self) -> None:
        for content in (
            "attributes: {label: First, label: Second}",
            "{[one, two]: value}", "{1: value}", "value: 2026-09-20",
        ):
            with self.subTest(content=content), self.assertRaises(forms.ValidationError):
                forms.read_yaml(self._temporary_yaml(content))

    def test_read_is_bounded_even_when_file_growth_is_hidden_by_metadata(self) -> None:
        path = self._temporary_yaml("x" * (forms.MAX_FILE_BYTES + 1))
        metadata = path.stat()
        small = os.stat_result((*metadata[:6], 1, *metadata[7:]))
        original_open = os.fdopen
        reads = []

        class Reader:
            def __init__(self, *args):
                self.stream = original_open(*args)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, count):
                reads.append(count)
                return self.stream.read(count)

        with patch.object(Path, "lstat", return_value=small), \
             patch.object(forms.os, "fstat", return_value=small), \
             patch.object(forms.os, "fdopen", side_effect=Reader), \
             self.assertRaisesRegex(forms.ValidationError, "file-size-limit"):
            forms.read_yaml(path)
        self.assertEqual(reads, [forms.MAX_FILE_BYTES + 1])

    def test_invalid_utf8_directory_and_fifo_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "invalid.yml"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(forms.ValidationError, "invalid-utf8"):
                forms.read_yaml(path)
            with self.assertRaisesRegex(forms.ValidationError, "unsafe-file-type"):
                forms.read_yaml(root)
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo.yml"
                os.mkfifo(fifo)
                with self.assertRaisesRegex(forms.ValidationError, "unsafe-file-type"):
                    forms.read_yaml(fifo)

    def test_symlinked_template_directory_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "external"
            self.write(target, "bug_report.yml", self.minimal_form())
            (root / ".github").mkdir()
            try:
                (root / ".github/ISSUE_TEMPLATE").symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(forms.ValidationError, "unsafe-file-type"):
                forms.validate_repository(root)

    def test_chooser_can_be_added_and_known_files_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in forms.KNOWN_FORMS:
                self.write(root, str(relative), self.minimal_form())
            self.assertEqual(forms.validate_repository(root), 2)
            self.write(root, str(forms.CONFIG_PATH), "blank_issues_enabled: true\n")
            self.assertEqual(forms.validate_repository(root), 3)
            for relative in (*forms.KNOWN_FORMS, forms.CONFIG_PATH):
                (root / relative).unlink()
            self.assertEqual(forms.validate_repository(root), 0)

    def test_malformed_contact_urls_are_validation_errors(self) -> None:
        for url in (
            "https://[broken", "https://example.com:bad", "https://example.com:65536",
            "https://example.com:", "https://example.com:0", "https://@example.com",
            "https://example.com/a b", "https://exam\nple.com", "https://example.com\\evil",
            "/help", "//example.com", "https:///help", "https://example.com/\x7f",
        ):
            config = {"contact_links": [{"name": "Help", "about": "Help", "url": url}]}
            with self.subTest(url=url), self.assertRaisesRegex(forms.ValidationError, "invalid-contact-url"):
                forms.validate_config(config)
        for url in ("https://example.com/help", "https://example.com:8443/help", "https://[::1]:443/help"):
            forms.validate_config({"contact_links": [{"name": "Help", "about": "Help", "url": url}]})

    def test_both_label_representations_and_empty_optional_text_are_supported(self) -> None:
        for labels in ('["type:bug", "help wanted"]', '"type:bug, help wanted"'):
            content = self.minimal_form().replace("body:\n", f"labels: {labels}\ntitle: \"\"\nbody:\n")
            content = content.replace("      label: Subject\n", '      label: Subject\n      value: ""\n      placeholder: ""\n      description: ""\n')
            forms.validate_issue_form(forms.read_yaml(self._temporary_yaml(content)))
        for labels in ("true", "12", '"one,,two"', '"' + ",".join(["one"] * 33) + '"'):
            content = self.minimal_form().replace("body:\n", f"labels: {labels}\nbody:\n")
            with self.subTest(labels=labels), self.assertRaises(forms.ValidationError):
                forms.validate_issue_form(forms.read_yaml(self._temporary_yaml(content)))

    def test_unknown_structures_and_wrong_optional_types_are_rejected(self) -> None:
        for original, replacement in (
            ("body:\n", "unknown: value\nbody:\n"),
            ("body:\n", "title: 12\nbody:\n"),
            ("      label: Subject\n", "      label: Subject\n      value: false\n"),
            ("    id: subject\n", "    id: subject\n    unexpected: true\n"),
            ("      required: true", "      required: true\n      unexpected: true"),
        ):
            content = self.minimal_form().replace(original, replacement)
            with self.subTest(replacement=replacement), self.assertRaises(forms.ValidationError):
                forms.validate_issue_form(forms.read_yaml(self._temporary_yaml(content)))


if __name__ == "__main__":
    unittest.main()

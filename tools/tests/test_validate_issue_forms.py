from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

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

    def test_repository_forms_pass_unchanged_and_optional_config_is_absent(self) -> None:
        self.assertEqual(forms.validate_repository(ROOT), 2)

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


if __name__ == "__main__":
    unittest.main()

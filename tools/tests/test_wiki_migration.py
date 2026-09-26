"""Legacy entry preservation and complete inventory rejection controls."""
import copy
import json
import unittest

from tools.wiki_migration import INVENTORY, canonical, legacy_link, validate


class WikiMigrationTests(unittest.TestCase):
    def test_actual_complete_inventory_and_links(self):
        result = validate(json.loads(INVENTORY.read_text(encoding="utf-8")))
        self.assertEqual((result["pages"], result["assets"], result["files"]), (26, 4, 31))
        self.assertGreater(result["legacyLinks"], 100)

    def test_encoded_alias_and_original_fragment(self):
        files = {"First Node.md": {"sourceReference": "https://example.test/pinned/First-Node.md"},
                 "assets/a.svg": {"sourceReference": "https://example.test/pinned/a.svg"}}
        self.assertEqual(legacy_link("[[Start|First%20Node#setup]]", "Home.md", files),
                         "https://example.test/pinned/First-Node.md#setup")
        self.assertEqual(legacy_link("assets/a.svg", "Home.md", files), "https://example.test/pinned/a.svg")
        with self.assertRaises(ValueError):
            legacy_link("first%20node", "Home.md", files)

    def test_traversal_encoded_separators_queries_and_unknown_names(self):
        for value in ("../secret", "/absolute", "a%2fb", "a%5Cb", "a%00b", "a\\b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical(value)
        for value in ("Missing", "Home?other=1", "javascript:alert(1)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                legacy_link(value, "Home.md", {})

    def test_missing_extra_changed_and_case_colliding_entries_fail(self):
        original = json.loads(INVENTORY.read_text(encoding="utf-8"))
        for mutation in ("missing", "extra", "digest", "case", "destination"):
            data = copy.deepcopy(original)
            if mutation == "missing":
                data["files"].pop()
            elif mutation in ("extra", "case"):
                row = copy.deepcopy(data["files"][1])
                row["path"] = "extra.md" if mutation == "extra" else row["path"].swapcase()
                data["files"].append(row)
            elif mutation == "digest":
                data["files"][1]["sha256"] = "0" * 64
            else:
                data["files"][1]["destination"] = "docs/no-such-authority.md"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate(data)

"""Research examples remain registered even when Cargo forces all test targets.

These catalogue regressions do not replace the actual-component experiment or
pretend that a native Cargo example's empty libtest harness executed its main.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import ci_suite_inventory as registry

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / "tools/ci/suites.d/invocation-concurrency.json"


class SuiteFragmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "suites.json"
        self.directory = self.path.with_suffix(".d")
        self.fragment = json.loads(FRAGMENT.read_text())
        self.base = {
            "schemaVersion": registry.SCHEMA,
            "boundaries": dict.fromkeys(registry.BOUNDARIES, "test boundary"),
            "narrowPackages": [], "fastPackages": [],
            "resourceClasses": {"runtime-bounded": {}},
            "suites": [], "selections": {},
            "recipes": {"workspace-all-features": {"run": ["cargo", "test", "--all-targets"]}},
        }
        self.path.write_text(json.dumps(self.base))

    def save_fragment(self, value, name="research.json"):
        self.directory.mkdir(exist_ok=True)
        path = self.directory / name
        path.write_text(json.dumps(value))
        return path

    def test_primary_catalogue_works_without_a_fragment_directory(self):
        self.assertEqual(registry.load(self.path), self.base)

    def test_research_registrations_match_actual_cargo_sources(self):
        manifest = ROOT / "tools/toolchain-smoke/Cargo.toml"
        examples = {row["name"]: row for row in tomllib.loads(manifest.read_text())["example"]}
        rows = self.fragment["suites"]
        self.assertEqual([row["target"] for row in rows],
                         ["research-concurrency-guest", "research-concurrency-host"])
        for row in rows:
            with self.subTest(target=row["target"]):
                example = examples[row["target"]]
                self.assertFalse(example["test"])
                self.assertEqual(row["manifest"], "tools/toolchain-smoke/Cargo.toml")
                self.assertEqual(row["kind"], "example")
                self.assertEqual(row["source"], example["path"])
                self.assertTrue((manifest.parent / row["source"]).resolve(strict=True).is_relative_to(ROOT))
                self.assertEqual(row["mode"], "compile-only")
                self.assertEqual(row["minimumCases"], 0)
                self.assertEqual(row["expectedCases"], [])
                self.assertEqual(row["expectedIgnored"], [])
        self.save_fragment(self.fragment)
        self.assertEqual(registry.load(self.path)["suites"], rows)

    def test_fragments_are_additive_and_preserve_primary_recipes(self):
        original = copy.deepcopy(self.fragment["suites"][0])
        original.update(id="existing.lib.existing", target="existing", kind="lib", source="src/lib.rs")
        self.base["suites"] = [original]
        before = json.dumps(self.base)
        self.path.write_text(before)
        self.save_fragment(self.fragment)
        result = registry.load(self.path)
        self.assertEqual(result["suites"], [original, *self.fragment["suites"]])
        self.assertEqual(result["recipes"], self.base["recipes"])
        self.assertEqual(self.path.read_text(), before)

    def test_duplicate_suite_ids_across_primary_and_fragments_are_rejected(self):
        self.base["suites"] = self.fragment["suites"][:1]
        self.path.write_text(json.dumps(self.base))
        self.save_fragment(self.fragment)
        with self.assertRaisesRegex(ValueError, "duplicate-suite-id"):
            registry.load(self.path)
        self.base["suites"] = []
        self.path.write_text(json.dumps(self.base))
        self.save_fragment(self.fragment, "second.json")
        with self.assertRaisesRegex(ValueError, "duplicate-suite-id"):
            registry.load(self.path)

    def test_fragment_contract_cannot_override_shared_policy(self):
        variants = [dict(self.fragment, schemaVersion="unknown"),
                    dict(self.fragment, recipes={}), dict(self.fragment, selections={}),
                    dict(self.fragment, suites=[]), dict(self.fragment, suites={}),
                    dict(self.fragment, suites=[None]), []]
        for value in variants:
            with self.subTest(value=value):
                self.save_fragment(value)
                with self.assertRaisesRegex(ValueError, "suite-fragment"):
                    registry.load(self.path)
        self.save_fragment(self.fragment).write_text('{"suites":[],"suites":[]}')
        with self.assertRaisesRegex(ValueError, "duplicate-inventory-key"):
            registry.load(self.path)

    def test_fragment_rows_receive_the_same_suite_validation(self):
        variants = [{"mode": "libtest"}, {"timeoutSeconds": 0}, {"kind": "unknown"},
                    {"manifest": "../foreign/Cargo.toml"}, {"source": "../../../foreign.rs"},
                    {"expectedCases": ["new_unregistered_test"]}, {"expectedIgnored": ["unknown"]}]
        for change in variants:
            with self.subTest(change=change):
                value = copy.deepcopy(self.fragment)
                value["suites"][0].update(change)
                self.save_fragment(value)
                with self.assertRaises(ValueError):
                    registry.load(self.path)

    def test_sources_may_leave_a_package_but_not_the_checkout(self):
        manifest = "tools/toolchain-smoke/Cargo.toml"
        for name in ("src/main.rs", "../shared.rs", "../../research/invocation-concurrency/host.rs"):
            with self.subTest(name=name):
                self.assertTrue(registry.suite_source_name(manifest, name))
        for name in ("../../../outside.rs", "../../", "../../x/../y.rs", "./main.rs", "/tmp/main.rs",
                     ".././main.rs", "..//main.rs", "..\\main.rs", "../bad\0.rs", "x" * 4097, "", None):
            with self.subTest(name=name):
                self.assertFalse(registry.suite_source_name(manifest, name))
        self.assertFalse(registry.suite_source_name("Cargo.toml", "../outside.rs"))
        self.assertFalse(registry.suite_source_name("../Cargo.toml", "main.rs"))
        self.assertFalse(registry.path_name("../../research/host.rs"))

    def test_fragment_file_and_directory_links_are_rejected(self):
        self.directory.symlink_to(self.path.parent / "missing-directory", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "linked-suite-fragments"):
            registry.load(self.path)
        self.directory.unlink()
        self.directory.mkdir()
        link = self.directory / "linked.json"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "suite-fragment-file"):
            registry.load(self.path)
        link.unlink()
        self.save_fragment(self.fragment, "not-json.txt")
        with self.assertRaisesRegex(ValueError, "suite-fragment-file"):
            registry.load(self.path)

    def test_fragment_count_and_aggregate_bytes_are_bounded(self):
        self.save_fragment(self.fragment, "one.json")
        self.save_fragment(self.fragment, "two.json")
        with patch.object(registry, "MAX_FRAGMENTS", 1):
            with self.assertRaisesRegex(ValueError, "suite-fragment-count"):
                registry.load(self.path)
        size = (self.directory / "one.json").stat().st_size
        with patch.object(registry, "MAX_BYTES", size + 1):
            with self.assertRaisesRegex(ValueError, "suite-fragment-byte-limit"):
                registry.load(self.path)

    def test_fragment_order_is_deterministic(self):
        last = copy.deepcopy(self.fragment)
        last["suites"] = last["suites"][1:]
        first = copy.deepcopy(self.fragment)
        first["suites"] = first["suites"][:1]
        self.save_fragment(last, "z.json")
        self.save_fragment(first, "a.json")
        self.assertEqual(registry.load(self.path)["suites"], self.fragment["suites"])


if __name__ == "__main__":
    unittest.main()

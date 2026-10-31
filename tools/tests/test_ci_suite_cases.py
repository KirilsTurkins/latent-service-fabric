"""Owner-local additions preserve exact discovery and every prior suite contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_suite_cases, ci_suite_discovery, ci_suite_inventory as registry

ROOT = Path(__file__).resolve().parents[2]


class SuiteCaseFragmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "suites.json"
        self.directory = self.path.with_suffix(".cases.d")
        self.suite = {
            "id": "example.lib.example", "package": "example", "target": "example",
            "manifest": "crates/example/Cargo.toml", "source": "src/lib.rs", "kind": "lib",
            "boundary": "runtime", "resourceClass": "bounded", "timeoutSeconds": 30,
            "platforms": ["linux-x86_64"], "prerequisites": ["cargo"], "recipe": "ordinary",
            "mode": "libtest", "minimumCases": 2, "expectedCases": ["old", "opt_in"],
            "expectedIgnored": ["opt_in"], "ignoredLeaves": ["opt_in"],
        }
        self.base = {
            "schemaVersion": registry.SCHEMA,
            "boundaries": dict.fromkeys(registry.BOUNDARIES, "test boundary"),
            "narrowPackages": [], "fastPackages": [], "resourceClasses": {"bounded": {}},
            "suites": [self.suite], "selections": {}, "recipes": {"ordinary": {}},
        }
        self.path.write_text(json.dumps(self.base))
        self.fragment = {"schemaVersion": ci_suite_cases.SCHEMA,
                         "suiteId": self.suite["id"], "expectedCases": ["new"]}

    def save(self, value=None, name="owner.json"):
        self.directory.mkdir(exist_ok=True)
        path = self.directory / name
        path.write_text(json.dumps(self.fragment if value is None else value))
        return path

    def test_absent_directory_preserves_the_primary_catalogue(self):
        self.assertEqual(registry.load(self.path), self.base)

    def test_additions_preserve_all_prior_names_ignore_states_and_execution_fields(self):
        self.save()
        original_bytes = self.path.read_bytes()
        expected = copy.deepcopy(self.base)
        expected["suites"][0]["expectedCases"].append("new")
        expected["suites"][0]["minimumCases"] += 1
        self.assertEqual(registry.load(self.path), expected)
        self.assertEqual(self.path.read_bytes(), original_bytes)

    def test_actual_discovery_still_requires_every_added_and_original_case(self):
        self.save()
        suite = registry.load(self.path)["suites"][0]
        available, ignored = frozenset({"old", "opt_in", "new"}), frozenset({"opt_in"})
        ci_suite_discovery.validate_cases(suite, available, ignored, {})
        for names, opt_in in ((available - {"new"}, ignored),
                              (available - {"old"}, ignored),
                              (available | {"unknown"}, ignored),
                              (available, ignored | {"new"})):
            with self.subTest(names=names, ignored=opt_in), self.assertRaises(ValueError):
                ci_suite_discovery.validate_cases(suite, names, opt_in, {})

    def test_duplicate_case_additions_cannot_hide_drift(self):
        for cases in (["old"], ["opt_in"], ["new", "new"]):
            with self.subTest(cases=cases):
                self.save(dict(self.fragment, expectedCases=cases))
                with self.assertRaisesRegex(ValueError, "duplicate-suite-case-addition"):
                    registry.load(self.path)
        self.save()
        self.save(name="second.json")
        with self.assertRaisesRegex(ValueError, "duplicate-suite-case-addition"):
            registry.load(self.path)

    def test_unknown_owners_and_non_libtest_targets_are_rejected(self):
        self.save(dict(self.fragment, suiteId="absent.lib.absent"))
        with self.assertRaisesRegex(ValueError, "suite-case-fragment-owner"):
            registry.load(self.path)
        self.save()
        for mode in ("custom", "compile-only"):
            with self.subTest(mode=mode):
                self.base["suites"][0]["mode"] = mode
                self.path.write_text(json.dumps(self.base))
                with self.assertRaisesRegex(ValueError, "suite-case-fragment-libtest"):
                    registry.load(self.path)

    def test_additions_cannot_repair_an_invalid_primary_count_or_duplicate_owner(self):
        self.save()
        for count in (1, 3, True):
            with self.subTest(count=count):
                self.suite["minimumCases"] = count
                self.path.write_text(json.dumps(self.base))
                with self.assertRaisesRegex(ValueError, "case-count-contract"):
                    registry.load(self.path)
        self.suite.update(minimumCases=0, expectedCases=[], expectedIgnored=[])
        self.path.write_text(json.dumps(self.base))
        with self.assertRaisesRegex(ValueError, "case-count-contract"):
            registry.load(self.path)
        self.suite.update(minimumCases=2, expectedCases=["old", "opt_in"], expectedIgnored=["new"])
        self.path.write_text(json.dumps(self.base))
        with self.assertRaisesRegex(ValueError, "ignored-case-contract"):
            registry.load(self.path)
        self.suite["expectedIgnored"] = ["opt_in"]
        self.base["suites"].append(copy.deepcopy(self.suite))
        self.path.write_text(json.dumps(self.base))
        with self.assertRaisesRegex(ValueError, "duplicate-suite-id"):
            registry.load(self.path)

    def test_fragment_schema_cannot_change_limits_recipes_or_ignore_state(self):
        for field, value in (("timeoutSeconds", 7200), ("recipe", "replacement"),
                             ("expectedIgnored", ["old"]), ("minimumCases", 0),
                             ("source", "different.rs")):
            with self.subTest(field=field):
                self.save(dict(self.fragment, **{field: value}))
                with self.assertRaisesRegex(ValueError, "suite-case-fragment-contract"):
                    registry.load(self.path)
        for value in ({}, [], dict(self.fragment, schemaVersion="unknown")):
            self.save(value)
            with self.assertRaisesRegex(ValueError, "suite-case-fragment-contract"):
                registry.load(self.path)
        self.save().write_text('{"suiteId":"a","suiteId":"b"}')
        with self.assertRaisesRegex(ValueError, "duplicate-inventory-key"):
            registry.load(self.path)

    def test_cases_and_owner_types_are_closed_and_bounded(self):
        for cases in ([], None, {}, [None], [""], ["bad\ncase"], ["x" * 4097]):
            with self.subTest(cases=cases):
                self.save(dict(self.fragment, expectedCases=cases))
                with self.assertRaisesRegex(ValueError, "suite-case-fragment-cases"):
                    registry.load(self.path)
        self.save(dict(self.fragment, suiteId=[]))
        with self.assertRaisesRegex(ValueError, "suite-case-fragment-owner"):
            registry.load(self.path)

    def test_count_and_aggregate_byte_limits_accept_exactly_and_reject_one_over(self):
        first = self.save()
        with patch.object(registry, "MAX_FRAGMENTS", 1), \
                patch.object(registry, "MAX_BYTES", first.stat().st_size):
            rows = copy.deepcopy(self.base["suites"])
            ci_suite_cases.extend_suites(rows, self.path)
            self.assertEqual(rows[0]["minimumCases"], 3)
        second = self.save(dict(self.fragment, expectedCases=["second"]), "second.json")
        with patch.object(registry, "MAX_FRAGMENTS", 1):
            with self.assertRaisesRegex(ValueError, "suite-case-fragment-count"):
                registry.load(self.path)
        size = first.stat().st_size + second.stat().st_size
        # The primary read has its own bound; call the additive reader directly.
        with patch.object(registry, "MAX_BYTES", size):
            rows = copy.deepcopy(self.base["suites"])
            ci_suite_cases.extend_suites(rows, self.path)
            self.assertEqual(rows[0]["minimumCases"], 4)
        with patch.object(registry, "MAX_BYTES", size - 1):
            with self.assertRaisesRegex(ValueError, "suite-case-fragment-byte-limit"):
                ci_suite_cases.extend_suites(copy.deepcopy(self.base["suites"]), self.path)

    def test_directory_and_file_links_and_non_json_entries_are_refused(self):
        self.directory.symlink_to(self.path.parent / "missing", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "linked-suite-case-fragments"):
            registry.load(self.path)
        self.directory.unlink()
        self.directory.write_text("not a directory")
        with self.assertRaisesRegex(ValueError, "suite-case-fragment-directory"):
            registry.load(self.path)
        self.directory.unlink()
        self.directory.mkdir()
        child = self.directory / "owner.json"
        child.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "suite-case-fragment-file"):
            registry.load(self.path)
        child.unlink()
        for name in ("invalid.txt", "UPPER.json"):
            child = self.save(name=name)
            with self.assertRaisesRegex(ValueError, "suite-case-fragment-file"):
                registry.load(self.path)
            child.unlink()
        child.mkdir()
        with self.assertRaisesRegex(ValueError, "suite-case-fragment-file"):
            registry.load(self.path)

    def test_order_is_deterministic_and_suite_fragment_owners_are_supported(self):
        self.save(dict(self.fragment, expectedCases=["z"]), "z.json")
        self.save(dict(self.fragment, expectedCases=["a"]), "a.json")
        self.assertEqual(registry.load(self.path)["suites"][0]["expectedCases"],
                         ["old", "opt_in", "a", "z"])
        rows = copy.deepcopy(self.base["suites"])
        self.base["suites"] = []
        self.path.write_text(json.dumps(self.base))
        directory = self.path.with_suffix(".d")
        directory.mkdir()
        (directory / "suite.json").write_text(json.dumps({
            "schemaVersion": registry.FRAGMENT_SCHEMA, "suites": rows}))
        self.assertEqual(registry.load(self.path)["suites"][0]["expectedCases"],
                         ["old", "opt_in", "a", "z"])

    def test_merged_inventory_keeps_all_native_cors_and_java_cases(self):
        path = ROOT / "tools/ci/suites.json"
        primary = registry.read_json(path)
        data = registry.load(path)
        before = {row["id"]: row for row in primary["suites"]}
        after = {row["id"]: row for row in data["suites"]}
        fragment = registry.read_json(ROOT / "tools/ci/suites.cases.d/cross-origin-assets.json")
        self.assertEqual(len(fragment["expectedCases"]), 17)
        for key, original in before.items():
            expected = copy.deepcopy(original)
            if key == fragment["suiteId"]:
                expected["expectedCases"].extend(fragment["expectedCases"])
                expected["minimumCases"] += len(fragment["expectedCases"])
            self.assertEqual(after[key], expected, key)
        self.assertIn("java_checkpoint_gc_fault::tests::"
                      "java_gc_fault_visits_only_eight_numeric_frames_for_authenticated_profile",
                      after["latent-wasmtime.lib.latent-wasmtime"]["expectedCases"])


if __name__ == "__main__":
    unittest.main()

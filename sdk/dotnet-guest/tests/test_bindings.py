"""Generator/ownership regressions; these synthetic tests are not guest execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools import dotnet_guest_bindings as bindings


class BindingTests(unittest.TestCase):
    def test_resource_order_is_canonical_but_bodies_remain_authoritative(self):
        first = '    public class Body: global::System.IDisposable {\n        public void Dispose() { Drop(1); }\n    }\n'
        second = '    public class Upload: global::System.IDisposable {\n        public void Dispose() { Drop(2); }\n    }\n'
        left = 'namespace Test {\n' + first + '\n' + second + '}\n'
        right = 'namespace Test {\n' + second + '\n' + first + '}\n'
        self.assertEqual(bindings.canonical_resource_order(left), bindings.canonical_resource_order(right))
        self.assertNotEqual(bindings.canonical_resource_order(left),
                            bindings.canonical_resource_order(right.replace('Drop(2)', 'Drop(3)')))
        self.assertEqual(bindings.canonical_resource_order(left), left)

    def test_interop_resource_order_does_not_hide_unrelated_methods(self):
        first = '        internal static class Body\n        {\n\n        }\n'
        second = first.replace('Body', 'Upload')
        self.assertEqual(bindings.canonical_resource_order(second + first), first + second)
        self.assertEqual(bindings.canonical_resource_order('void Run() { Foo(); }'), 'void Run() { Foo(); }')
        with self.assertRaisesRegex(bindings.BindingError, 'duplicate-generated-resource-class'):
            bindings.canonical_resource_order(first + first)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.generated = self.root / "generated"
        self.generated.mkdir()
        (self.generated / "Contract.cs").write_text("// generated\n", encoding="utf-8")
        self.output = self.root / "output"

    def receipt(self):
        return {"schemaVersion": bindings.SCHEMA, "generator": bindings.GENERATOR,
                "world": "probe", "canonicalAbi": "stackful",
                "authoritativeWitSha256": "0" * 64,
                "outputs": bindings.output_hashes(self.generated)}

    def test_unknown_csharp_file_is_not_deleted(self):
        self.output.mkdir()
        hand = self.output / "Handwritten.cs"
        hand.write_text("public class Mine {}", encoding="utf-8")
        with self.assertRaisesRegex(bindings.BindingError, "unowned"):
            bindings.install(self.generated, self.output, self.receipt())
        self.assertEqual(hand.read_text(), "public class Mine {}")

    def test_changed_generated_file_is_not_overwritten(self):
        bindings.install(self.generated, self.output, self.receipt())
        edited = self.output / "Contract.cs"
        edited.write_text("// my change\n", encoding="utf-8")
        with self.assertRaisesRegex(bindings.BindingError, "modified-or-unowned"):
            bindings.install(self.generated, self.output, self.receipt())
        self.assertEqual(edited.read_text(), "// my change\n")

    def test_output_symlink_is_rejected_without_touching_target(self):
        self.output.symlink_to(self.generated, target_is_directory=True)
        before = bindings.output_hashes(self.generated)
        with self.assertRaisesRegex(bindings.BindingError, "unowned"):
            bindings.install(self.generated, self.output, self.receipt())
        self.assertEqual(bindings.output_hashes(self.generated), before)

    def test_generated_symlink_is_rejected(self):
        (self.generated / "Bad.cs").symlink_to(self.generated / "Contract.cs")
        with self.assertRaisesRegex(bindings.BindingError, "invalid-or-oversized"):
            self.receipt()
        self.assertFalse(self.output.exists())

    def test_owned_output_replacement_removes_only_stale_generated_files(self):
        bindings.install(self.generated, self.output, self.receipt())
        (self.generated / "Contract.cs").rename(self.generated / "NewContract.cs")
        bindings.install(self.generated, self.output, self.receipt())
        self.assertFalse((self.output / "Contract.cs").exists())
        self.assertTrue((self.output / "NewContract.cs").is_file())
        bindings.require_owned(self.output)

    def test_check_passes_without_modifying_bytes_or_file_timestamps(self):
        receipt = self.receipt()
        bindings.install(self.generated, self.output, receipt)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        bindings.install(self.generated, self.output, receipt, check=True)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        self.assertEqual(before, after)

    def test_check_reports_drift_and_keeps_previous_generation(self):
        bindings.install(self.generated, self.output, self.receipt())
        before = bindings.output_hashes(self.output)
        (self.generated / "Contract.cs").write_text("// next generation\n", encoding="utf-8")
        with self.assertRaisesRegex(bindings.BindingError, "generated-binding-drift"):
            bindings.install(self.generated, self.output, self.receipt(), check=True)
        self.assertEqual(bindings.output_hashes(self.output), before)

    def test_check_does_not_create_missing_output(self):
        with self.assertRaisesRegex(bindings.BindingError, "generated-binding-drift"):
            bindings.install(self.generated, self.output, self.receipt(), check=True)
        self.assertFalse(self.output.exists())

    def test_receipt_cannot_claim_other_files_or_digests(self):
        receipt = self.receipt()
        receipt["outputs"]["../user.cs"] = "0" * 64
        with self.assertRaisesRegex(bindings.BindingError, "generated-receipt-disagrees"):
            bindings.install(self.generated, self.output, receipt)
        self.assertFalse(self.output.exists())

    def test_new_unowned_file_blocks_an_otherwise_valid_receipt(self):
        bindings.install(self.generated, self.output, self.receipt())
        (self.output / "notes.txt").write_text("keep me", encoding="utf-8")
        with self.assertRaisesRegex(bindings.BindingError, "modified-or-unowned"):
            bindings.install(self.generated, self.output, self.receipt())
        self.assertEqual((self.output / "notes.txt").read_text(), "keep me")

    def test_only_async_implementation_kinds_change(self):
        graph = {
            "types": [{"kind": {"result": {"ok": "u64", "err": 1}}},
                      {"kind": {"option": "string"}}, {"kind": {"handle": {"own": 3}}},
                      {"kind": "resource"}, {"kind": {"list": "u8"}}],
            "interfaces": [{"name": "http", "package": 7, "functions": {
                "request": {"kind": "async-freestanding", "params": ["u64", 2], "result": 0},
                "read": {"kind": {"async-method": 3}, "params": [2], "result": 4},
                "open": {"kind": {"async-static": 3}, "params": [], "result": 2},
            }}],
            "worlds": [{"imports": {"direct": {"function": {"kind": "async-freestanding"}}},
                        "exports": {"sync": {"function": {"kind": "freestanding"}}}}],
        }
        before = copy.deepcopy(graph)
        actual = bindings.stackful_projection(graph)
        expected = copy.deepcopy(graph)
        functions = expected["interfaces"][0]["functions"]
        functions["request"]["kind"] = "freestanding"
        functions["read"]["kind"] = {"method": 3}
        functions["open"]["kind"] = {"static": 3}
        expected["worlds"][0]["imports"]["direct"]["function"]["kind"] = "freestanding"
        self.assertEqual(actual, expected)
        self.assertEqual(graph, before)

    def test_unqualified_value_types_are_explicitly_rejected(self):
        for kind in ("future", "stream", "map", "fixed-size-list"):
            with self.subTest(kind=kind), self.assertRaisesRegex(bindings.BindingError, kind):
                bindings.stackful_projection({"types": [{"kind": {kind: "u64"}}]})

    def test_documentation_is_the_only_removed_graph_field(self):
        value = {"docs": "comment", "name": "identity", "kind": {"result": {"ok": "u64"}},
                 "items": [{"docs": None, "owner": 42}]}
        self.assertEqual(bindings.contract_graph(value),
                         {"name": "identity", "kind": {"result": {"ok": "u64"}}, "items": [{"owner": 42}]})

    def test_failed_directory_install_restores_previous_owned_generation(self):
        bindings.install(self.generated, self.output, self.receipt())
        before = bindings.output_hashes(self.output)
        (self.generated / "Contract.cs").write_text("// replacement\n", encoding="utf-8")
        original = Path.rename
        def fail_new(path, target):
            if path.name == "new":
                raise OSError("injected rename failure")
            return original(path, target)
        with patch.object(Path, "rename", fail_new), self.assertRaisesRegex(OSError, "injected"):
            bindings.install(self.generated, self.output, self.receipt())
        self.assertEqual(bindings.output_hashes(self.output), before)

    def test_generation_rejects_source_overlap_before_invoking_any_tool(self):
        with patch.object(bindings, "run") as run:
            with self.assertRaisesRegex(bindings.BindingError, "overlaps-source"):
                bindings.generate(self.generated, self.generated, "probe", "bindgen", "wasm-tools")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

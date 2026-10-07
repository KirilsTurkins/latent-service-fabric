"""Explicit fault inputs preserve the original signed transaction requirements."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.java_capsule_project import validate
from tools.java_transaction_diagnostics import HELPER, SELECTORS, create, source_variant
from tools.java_transaction_schema import SOURCE, create as create_schema
from tools.rust_capsule_project import digest, snapshot
from tools.transaction_guest_project import HTTP_REQUIREMENTS


class JavaTransactionDiagnosticTests(unittest.TestCase):
    def test_value_capture_preserves_owned_abi_limits_and_emits_unsigned_utf8_and_absent_controls(self):
        from tools.java_transaction_values import SELECTORS as VALUE_SELECTORS, create as create_values
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = snapshot(create_schema(root / "ordinary", "legacy-v1", effect="put-once"))
            values = snapshot(create_values(root / "values"))
            source = values[SOURCE].decode("utf-8")
            declaration = json.loads(values["transaction-value-inputs.json"])
            descriptor, lock, _ = validate(values)
            self.assertEqual(descriptor["limits"], json.loads(original["capsule-project.json"])["limits"])
            for name in ("wit/world.wit", "transaction-binding.json", HTTP_REQUIREMENTS):
                self.assertEqual(values[name], original[name])
            self.assertIn("? Long.MIN_VALUE", source)
            self.assertIn("? -1L", source)
            self.assertIn("new Unsigned64(next)", source)
            self.assertIn("κλειδί / 値 / 🌍", source)
            self.assertIn("query.get(UTF8_KEY)", source)
            self.assertIn("query.get(ABSENT_KEY)", source)
            self.assertEqual(declaration["selectors"], VALUE_SELECTORS)
            self.assertEqual(declaration["expectedUnsignedValues"], {
                "highBit": "9223372036854775808", "unsignedMaximum": "18446744073709551615"})
            self.assertEqual(declaration["sourceDigest"], digest(values[SOURCE]))
            self.assertEqual(lock["template"]["sourceDigest"], declaration["sourceDigest"])
            self.assertIs(declaration["signedStateExecutionQualified"], False)
            self.assertIs(declaration["unsignedRoundtripQualified"], False)
            self.assertIs(declaration["utf8RoundtripQualified"], False)
            self.assertIs(declaration["absentOptionalQualified"], False)

    def test_generated_java_utf8_literal_has_exact_json_value_and_declared_raw_byte_digest(self):
        import re
        from tools.java_transaction_values import UTF8_TEXT, create as create_values
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create_values(Path(temporary) / "values"))
            source = files[SOURCE].decode("utf-8")
            declaration = json.loads(files["transaction-value-inputs.json"])
            literal = re.search(r'UTF8_VALUE = ("(?:[^"\\]|\\.)*")\.getBytes', source).group(1)
            # The emitted Java literal uses only the common JSON/Java string
            # escapes. Decode the literal before checking application bytes.
            actual = json.loads(literal).encode("utf-8")
            self.assertEqual(json.loads(actual), [None, UTF8_TEXT])
            expected = json.dumps([None, UTF8_TEXT], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.assertEqual(actual, expected)
            self.assertEqual(digest(actual), declaration["utf8PayloadDigest"])

    def test_forbidden_child_is_real_reachable_java_import_with_original_companion_and_zero_child_budget(self):
        from tools.transaction_guest_variants import CHILD, create as create_variant
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create_variant(root / "child", "java", "forbidden-child")
            files = snapshot(project)
            source = files[SOURCE].decode()
            self.assertIn("Bindings.LatentServiceInvoke.call", source)
            self.assertLess(source.index("State.acquireCommand"), source.index("Bindings.LatentServiceInvoke.call"))
            self.assertLess(source.index("Bindings.LatentServiceInvoke.call"), source.index("command.get(KEY)"))
            self.assertIn(CHILD, files["wit/world.wit"].decode())
            self.assertIn("wit/deps/invocation/package.wit", files)
            self.assertEqual(json.loads(files["capsule-project.json"])["limits"]["childCalls"], 0)
            self.assertEqual(json.loads(files["transaction-binding.json"])["operations"][0]["mode"], "strict-command")
            with self.assertRaisesRegex(ValueError, "unknown controlled"):
                create_variant(root / "wrong-language", "c", "forbidden-child")
            self.assertFalse((root / "wrong-language").exists())

    def test_memory_selector_is_separate_and_keeps_original_staging_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = snapshot(create(root / "original"))
            selected = snapshot(create(root / "memory", memory_after_stage=True))
            record = json.loads(selected["transaction-diagnostic-inputs.json"])
            self.assertEqual(record["selectors"], {**SELECTORS, "memoryAfterStage": "4294967292"})
            self.assertEqual(selected[SOURCE], original[SOURCE])
            for name in ("wit/world.wit", "transaction-binding.json", HTTP_REQUIREMENTS, "state-schema.json", "capsule-project.json"):
                self.assertEqual(selected[name], original[name])
            self.assertIn(b"allocated = new byte[80 * 1024 * 1024]", selected[HELPER])
            self.assertNotIn(b"MEMORY_DELTA", original[HELPER])
            self.assertEqual(record["helperDigest"], digest(selected[HELPER]))
            self.assertIs(record["memoryExhaustionQualified"], False)
            self.assertIs(record["crashBeforeCommitQualified"], False)
            self.assertEqual(record["faultAfter"], ["state-put", "captured-put-once-intent"])
            for value in (1, None, "true"):
                with self.assertRaisesRegex(ValueError, "explicit boolean"):
                    create(root / "not-created", memory_after_stage=value)
            self.assertFalse((root / "not-created").exists())

    def test_new_fault_capture_preserves_original_abi_payload_companion_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = snapshot(create_schema(root / "original", "legacy-v1", effect="put-once"))
            diagnostic = snapshot(create(root / "diagnostic"))
            descriptor, lock, _pins = validate(diagnostic)
            record = json.loads(diagnostic["transaction-diagnostic-inputs.json"])
            for name in ("wit/world.wit", "transaction-binding.json", HTTP_REQUIREMENTS, "state-schema.json"):
                self.assertEqual(diagnostic[name], original[name])
            self.assertEqual(descriptor["limits"], json.loads(original["capsule-project.json"])["limits"])
            self.assertEqual(descriptor["service"], "examples/transaction-java-aggregate")
            self.assertEqual(descriptor["version"], "1.0.1")
            self.assertEqual(lock["sdk"], json.loads(original["sdk-lock.json"])["sdk"])
            self.assertEqual(lock["template"]["sourceDigest"], digest(diagnostic[SOURCE]))
            self.assertEqual(json.loads(diagnostic["application-schema-inputs.json"])["sourceDigest"], digest(diagnostic[SOURCE]))
            self.assertNotEqual(diagnostic[SOURCE], original[SOURCE])
            self.assertEqual(record["selectors"], SELECTORS)
            self.assertEqual(record["originalSourceDigest"], digest(original[SOURCE]))
            self.assertEqual(record["sourceDigest"], digest(diagnostic[SOURCE]))
            self.assertEqual(record["helperDigest"], digest(diagnostic[HELPER]))
            self.assertTrue(record["freshInstanceRequired"])
            for key in ("componentCompiled", "stateExecutionQualified", "cancellationQualified",
                        "fuelExhaustionQualified", "freshInstanceQualified"):
                self.assertIs(record[key], False)
            self.assertEqual(record["faultAfter"], ["state-put", "captured-put-once-intent"])
            self.assertNotIn(b"latent:http/client", diagnostic["wit/world.wit"])

    def test_original_staging_drift_is_rejected_and_an_existing_capture_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ordinary = snapshot(create_schema(root / "ordinary", "legacy-v1", effect="put-once"))
            source = ordinary[SOURCE].decode()
            with self.assertRaisesRegex(ValueError, "source drift"):
                source_variant(source.replace('new Intent("qualified-http", "put-once", effectPayload)',
                                              'new Intent("unapproved", "put-once", effectPayload)'))
            with self.assertRaisesRegex(ValueError, "source drift"):
                source_variant(source.replace("long next = old + request.delta();", "long next = 0;"))
            project = create(root / "diagnostic")
            before = snapshot(project)
            with self.assertRaisesRegex(ValueError, "fresh output"):
                create(project)
            self.assertEqual(snapshot(project), before)


if __name__ == "__main__":
    unittest.main()

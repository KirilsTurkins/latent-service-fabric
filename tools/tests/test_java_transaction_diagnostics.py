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

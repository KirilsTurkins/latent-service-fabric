"""Captured application formats; guest State execution needs a signed node."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.java_capsule_project import validate
from tools.java_transaction_schema import CODEC, DEFINITIONS, SOURCE, VARIANTS, create, definitions, source_variant
from tools.rust_capsule_project import ROOT, digest, snapshot


class JavaTransactionSchemaTests(unittest.TestCase):
    def test_schema_variants_preserve_resources_business_identity_and_exact_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            projects = {variant: snapshot(create(Path(temporary) / variant, variant)) for variant in VARIANTS}
        original = projects["legacy-v1"]
        identities = set()
        for variant, files in projects.items():
            with self.subTest(variant=variant):
                project, lock, _pins = validate(files)
                inputs = json.loads(files["application-schema-inputs.json"])
                binding = json.loads(files["transaction-binding.json"])
                identities.add(digest(files[SOURCE]))
                self.assertEqual(project["service"], "examples/transaction-java-aggregate")
                self.assertEqual(files["wit/world.wit"], original["wit/world.wit"])
                self.assertEqual(binding["namespace"], "transactional-aggregate")
                self.assertEqual(binding["operations"], json.loads(original["transaction-binding.json"])["operations"])
                self.assertEqual(lock["sdk"], json.loads(original["sdk-lock.json"])["sdk"])
                self.assertEqual(lock["template"]["sourceDigest"], digest(files[SOURCE]))
                self.assertEqual(inputs["writers"], [binding["stateSchema"]])
                self.assertEqual(binding["stateSchema"], digest(files["state-schema.json"]))
                self.assertEqual(inputs["readers"], sorted([DEFINITIONS["v1"]] if variant == "legacy-v1" else DEFINITIONS.values()))
                for version, identity in DEFINITIONS.items():
                    self.assertEqual(digest(files["schemas/application-aggregate-" + version + ".schema.json"]), identity)
                self.assertFalse(inputs["publicationReviewGranted"])
                self.assertFalse(inputs["componentCompiled"])
                self.assertFalse(inputs["stateExecutionQualified"])
                self.assertEqual(project["limits"]["outboundRequests"], 0)
                self.assertNotIn("latent:http/client", files["wit/world.wit"].decode())
                self.assertIn("try (var command = State.acquireCommand().value())", files[SOURCE].decode())
                self.assertIn("try (var query = State.acquireQuery().value())", files[SOURCE].decode())
                self.assertIn('new Intent("approved-event", "event", payload).stage(command)', files[SOURCE].decode())
        self.assertEqual(len(identities), 3)
        self.assertEqual(projects["compatible-v2"][CODEC], projects["writer-v2"][CODEC])
        self.assertIn(b"WRITE_V2 = false;", projects["compatible-v2"][SOURCE])
        self.assertIn(b"WRITE_V2 = true;", projects["writer-v2"][SOURCE])
        self.assertEqual(json.loads(projects["compatible-v2"]["transaction-binding.json"])["stateSchema"], DEFINITIONS["v1"])
        self.assertEqual(json.loads(projects["writer-v2"]["transaction-binding.json"])["stateSchema"], DEFINITIONS["v2"])

    def test_unknown_profile_existing_capture_and_reader_drift_cannot_create_a_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "original"
            with self.assertRaisesRegex(ValueError, "unknown Java transaction schema variant"):
                create(project, "automatic-migration")
            self.assertFalse(project.exists())
            create(project, "legacy-v1")
            original = snapshot(project)
            with self.assertRaisesRegex(ValueError, "fresh output"):
                create(project, "writer-v2")
            self.assertEqual(snapshot(project), original)
        source = (ROOT / "sdk/java-guest/templates/transactional-aggregate.java").read_text()
        with self.assertRaisesRegex(ValueError, "reader source drift"):
            source_variant(source.replace("payload.bytes().length != 8", "payload.bytes().length != 9"), "compatible-v2")
        with self.assertRaisesRegex(ValueError, "source drift"):
            source_variant(source.replace("new byte[8]", "new byte[9]"), "writer-v2")
        self.assertEqual({name: digest(raw) for name, raw in definitions().items()}, DEFINITIONS)


if __name__ == "__main__":
    unittest.main()

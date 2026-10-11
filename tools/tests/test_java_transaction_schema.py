"""Captured application formats; guest State execution needs a signed node."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.java_capsule_project import validate
from tools.java_transaction_schema import CODEC, DEFINITIONS, RECOVERY_RECIPE, SOURCE, VARIANTS, create, definitions, source_variant
from tools.rust_capsule_project import ROOT, digest, snapshot


class JavaTransactionSchemaTests(unittest.TestCase):
    def test_recovery_recipe_keeps_real_teavm_clocks_and_closed_runtime_support_without_authority(self):
        from tools.java_capsule_project import runtime_wit
        from tools.java_transaction_schema import recovery_recipe
        source, world, recipe_raw = recovery_recipe()
        declaration = json.loads(recipe_raw)
        clocks = (b"latent:clock/monotonic@0.1.0", b"latent:clock/wall@0.1.0")
        service = world.split(b"world service {", 1)[1].split(b"}", 1)[0]
        support = world.split(b"world runtime-support {", 1)[1].split(b"}", 1)[0]
        for clock in clocks:
            self.assertEqual(service.count(b"import " + clock + b";"), 1)
            self.assertEqual(support.count(b"import " + clock + b";"), 1)
        base = world.split(b"\nworld runtime-support", 1)[0]
        declarations = b"\n" + b"".join(b"    import " + clock + b";\n" for clock in clocks)
        base = base.replace(declarations, b"", 1)
        # Use the maintained actual compiler template transformation exactly.
        self.assertEqual(runtime_wit(base, "service"), world)
        self.assertEqual(declaration["worldDigest"], digest(world))
        self.assertEqual(declaration["sourceDigest"], digest(source))
        self.assertIs(declaration["componentCompiled"], False)
        self.assertIs(declaration["signedExecutionQualified"], False)
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "source", "legacy-v1", effect="put-once"))
            self.assertEqual(files["wit/world.wit"], world)
            self.assertEqual(files["wit/deps/clock/package.wit"],
                             files["vendor/lsf/wit/platform/clock/package.wit"])
            self.assertEqual(json.loads(files["capsule-project.json"])["limits"]["memoryBytes"], 67108864)
            self.assertEqual(json.loads(files["deferred-http-requirements.json"])["authority"],
                             {"installed": False, "ruleGranted": False, "executionQualified": False})

    def test_explicit_recovery_recipe_preserves_three_fields_without_changing_shared_default(self):
        original_world = (ROOT / "examples/rust-capsules/transactional-aggregate/world.wit").read_bytes()
        original_source = (ROOT / "sdk/java-guest/templates/transactional-aggregate.java").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            files = snapshot(create(Path(temporary) / "recovery", "legacy-v1"))
            project, lock, _pins = validate(files)
            declaration = json.loads(files["java-recovery-recipe.json"])
            self.assertEqual(declaration["schemaVersion"], "latent.java.transaction-recovery-recipe.v1")
            self.assertEqual(files[SOURCE], (ROOT / RECOVERY_RECIPE / "Capsule.java").read_bytes())
            self.assertEqual(files["wit/world.wit"], (ROOT / RECOVERY_RECIPE / "world.wit.in").read_bytes())
            self.assertIn(b"view-version: list<u8>", files["wit/world.wit"])
            self.assertIn(b"key-version: option<list<u8>>", files["wit/world.wit"])
            for capability in (b"latent:clock/monotonic@0.1.0", b"latent:clock/wall@0.1.0"):
                self.assertEqual(files["wit/world.wit"].count(b"import " + capability + b";"), 2)
            self.assertIn(b"world runtime-support", files["wit/world.wit"])
            self.assertEqual(lock["template"]["witDigest"], digest(files["wit/world.wit"]))
            self.assertEqual(project["limits"]["outboundRequests"], 0)
            self.assertFalse(declaration["componentCompiled"])
            self.assertFalse(declaration["signedExecutionQualified"])
        self.assertEqual((ROOT / "examples/rust-capsules/transactional-aggregate/world.wit").read_bytes(), original_world)
        self.assertEqual((ROOT / "sdk/java-guest/templates/transactional-aggregate.java").read_bytes(), original_source)
        self.assertIn(b"view-version: list<u8>", original_world)
        self.assertIn(b"key-version: option<list<u8>>", original_world)

    def test_recovery_recipe_content_or_claim_drift_refuses_before_creating_a_project(self):
        from tools import java_transaction_schema as owner
        original = owner.read_file
        with tempfile.TemporaryDirectory() as temporary:
            for selected in ("Capsule.java", "world.wit.in", "recipe.json"):
                output = Path(temporary) / selected
                def changed(path, *args):
                    raw = original(path, *args)
                    if path == ROOT / RECOVERY_RECIPE / selected:
                        if selected == "recipe.json":
                            value = json.loads(raw)
                            value["signedExecutionQualified"] = True
                            return json.dumps(value).encode()
                        return raw + b"\n"
                    return raw
                with self.subTest(selected=selected), patch.object(owner, "read_file", autospec=True, side_effect=changed):
                    with self.assertRaisesRegex(ValueError, "recovery recipe identity drift"):
                        create(output, "legacy-v1")
                self.assertFalse(output.exists())

    def test_put_once_variants_capture_exact_payload_and_package_requirements_without_changing_companion(self):
        from tools.rust_capsule_build import package_inputs
        from tools.transaction_guest_project import HTTP_BODY, HTTP_REQUIREMENTS
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for variant in VARIANTS:
                with self.subTest(variant=variant):
                    original = snapshot(create(root / (variant + "-event"), variant))
                    files = snapshot(create(root / (variant + "-http"), variant, effect="put-once"))
                    project, lock, _pins = validate(files)
                    self.assertEqual(files["transaction-binding.json"], original["transaction-binding.json"])
                    self.assertEqual(files["wit/world.wit"], original["wit/world.wit"])
                    self.assertEqual(files["state-schema.json"], original["state-schema.json"])
                    self.assertEqual(project["limits"]["effectCount"], 1)
                    self.assertEqual(project["limits"]["outboundRequests"], 0)
                    self.assertEqual(project["limits"]["childCalls"], 0)
                    self.assertEqual(lock["template"]["sourceDigest"], digest(files[SOURCE]))
                    requirements = json.loads(files[HTTP_REQUIREMENTS])
                    self.assertEqual(len(HTTP_BODY), 27)
                    self.assertEqual(requirements["scope"]["companionDigest"], digest(files["transaction-binding.json"]))
                    self.assertEqual(requirements["intent"], {"binding": "qualified-http", "operation": "put-once", "count": 1,
                        "requestedExpiryUnixMillis": None,
                        "payload": {"bytes": "amF2YS1hZ2dyZWdhdGUtcHV0LW9uY2UtdjEA", "mediaType": "application/octet-stream", "metadata": []}})
                    self.assertTrue(all(value is False for value in requirements["authority"].values()))
                    output = root / (variant + "-packaged-inputs")
                    output.mkdir()
                    # This unit test checks real source packaging, never signing
                    # or execution of these explicit noncomponent fixture bytes.
                    package_inputs(output, project, {"imports": {}, "exports": {}}, files, b"unit-test-not-a-component")
                    layers = json.loads((output / "package-source.json").read_bytes())["layers"]
                    asset = [row for row in layers if row["path"] == HTTP_REQUIREMENTS]
                    self.assertEqual(asset, [{"path": HTTP_REQUIREMENTS, "source": HTTP_REQUIREMENTS,
                                             "role": "asset", "mediaType": "application/json"}])
                    self.assertEqual((output / HTTP_REQUIREMENTS).read_bytes(), files[HTTP_REQUIREMENTS])
                    self.assertEqual((output / "transaction-binding.json").read_bytes(), original["transaction-binding.json"])

    def test_requirements_reject_payload_authority_type_and_original_companion_drift(self):
        from tools.transaction_guest_project import HTTP_REQUIREMENTS, package_effect_requirements
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = snapshot(create(root / "source", "legacy-v1", effect="put-once"))
            project, _lock, _pins = validate(files)
            requirements = json.loads(files[HTTP_REQUIREMENTS])
            changed = [dict(requirements, url="https://unapproved.invalid"),
                       dict(requirements, protectedCredential="guest-selected"),
                       dict(requirements, authority={"installed": True, "ruleGranted": False, "executionQualified": False}),
                       dict(requirements, intent={**requirements["intent"], "count": True}),
                       dict(requirements, intent={**requirements["intent"], "requestedExpiryUnixMillis": "18446744073709551615"}),
                       dict(requirements, ceiling={**requirements["ceiling"], "maximumAttempts": 4}),
                       dict(requirements, intent={**requirements["intent"], "payload": {**requirements["intent"]["payload"], "bytes": ""}})]
            for value in changed:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    package_effect_requirements(root, project, {**files, HTTP_REQUIREMENTS: json.dumps(value).encode()})
            for raw in (b" " * 8193, b'{"schemaVersion":"one","schemaVersion":"two"}'):
                with self.assertRaises(ValueError):
                    package_effect_requirements(root, project, {**files, HTTP_REQUIREMENTS: raw})
            with self.assertRaises(ValueError):
                package_effect_requirements(root, project, {**files, "transaction-binding.json": files["transaction-binding.json"] + b" "})
            with self.assertRaises(ValueError):
                package_effect_requirements(root, project, {key: value for key, value in files.items() if key != "transaction-binding.json"})
            self.assertIsNone(package_effect_requirements(root, project, {key: value for key, value in files.items() if key != HTTP_REQUIREMENTS}))

    def test_unknown_effect_and_existing_capture_cannot_replace_original_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            with self.assertRaisesRegex(ValueError, "unknown Java transaction effect variant"):
                create(source, "legacy-v1", effect="immediate-http")
            self.assertFalse(source.exists())
            create(source, "legacy-v1")
            original = snapshot(source)
            with self.assertRaisesRegex(ValueError, "fresh output"):
                create(source, "legacy-v1", effect="put-once")
            self.assertEqual(snapshot(source), original)

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

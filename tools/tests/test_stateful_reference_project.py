"""Real language creators preserve their captured SDKs and narrow app scope."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import stateful_reference_project as app
from tools.rust_capsule_project import snapshot

HTTP_PROFILE = "qualified-http-v1:" + "a" * 64


class StatefulReferenceProject(unittest.TestCase):
    def test_six_real_creators_keep_exact_sdk_closures_and_language_runtime_worlds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for language in app.LANGUAGES:
                with self.subTest(language=language):
                    name = "order-draft-" + language
                    seed = app.creator(language)(root / (language + "-seed"), "transactional-aggregate", name)
                    project = app.create(root / language, language, draft_id="alice")
                    self.assertEqual(snapshot(seed / "vendor"), snapshot(project / "vendor"))
                    self.assertEqual((seed / "sdk-lock.json").read_bytes(), (project / "sdk-lock.json").read_bytes())
                    seed_world = (seed / "wit/world.wit").read_text()
                    world = (project / "wit/world.wit").read_text()
                    self.assertEqual("world runtime-support {" in world, "world runtime-support {" in seed_world)
                    self.assertIn("package examples:order-draft@1.0.0;", world)
                    self.assertNotIn("latent:http/", world)
                    self.assertNotIn("latent:service/", world)
                    self.assertIn("import latent:state/key-value@0.2.0;", world)
                    self.assertIn("import latent:intents/staging@0.1.0;", world)
                    declaration = json.loads((project / "transaction-binding.json").read_bytes())
                    self.assertEqual(declaration["namespace"], "order-drafts-alice")
                    self.assertEqual(declaration["stateSchema"], "sha256:" + hashlib.sha256((project / "state-schema.json").read_bytes()).hexdigest())
                    self.assertEqual([(entry["operation"], entry["mode"]) for entry in declaration["operations"]],
                                     [("edit", "strict-command"), ("query", "fresh-query")])
                    before = json.loads((seed / "capsule-project.json").read_bytes())["limits"]
                    after = json.loads((project / "capsule-project.json").read_bytes())["limits"]
                    self.assertEqual({key: value for key, value in before.items() if key not in {"stateReadBytes", "stateWriteBytes", "effectCount"}},
                                     {key: value for key, value in after.items() if key not in {"stateReadBytes", "stateWriteBytes", "effectCount"}})
                    self.assertEqual((after["stateReadBytes"], after["stateWriteBytes"], after["effectCount"]), (4096, 1024, 2))

    def test_six_notification_captures_package_exact_profile_bytes_without_grants(self):
        from tools.transaction_guest_project import HTTP_REQUIREMENTS, package_effect_requirements
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for language in app.LANGUAGES:
                with self.subTest(language=language):
                    project = app.create(root / language, language, draft_id="alice", http_profile=HTTP_PROFILE)
                    files = snapshot(project)
                    model = json.loads(files["capsule-project.json"])
                    requirements = json.loads(files[HTTP_REQUIREMENTS])
                    self.assertEqual(requirements["namespace"], "order-drafts-alice")
                    self.assertEqual(requirements["companionDigest"], "sha256:" + hashlib.sha256(files["transaction-binding.json"]).hexdigest())
                    self.assertEqual((requirements["binding"], requirements["operation"]), ("draft-http", "http"))
                    self.assertEqual((requirements["adapter"], requirements["payloadFormat"]), ("qualified-http-effect-v1", "http-body-value-v1"))
                    self.assertEqual(requirements["idempotencyProfile"], HTTP_PROFILE)
                    self.assertEqual(requirements["ceiling"], {"maximum_payload_bytes": 1024, "maximum_response_bytes": 22528,
                        "maximum_attempts": 3, "maximum_age_millis": 600000, "attempt_timeout_millis": 2000})
                    self.assertNotIn("authority", requirements)
                    output = root / (language + "-package"); output.mkdir()
                    self.assertEqual(package_effect_requirements(output, model, files), (HTTP_REQUIREMENTS, "asset", "application/json"))
                    self.assertEqual((output / HTTP_REQUIREMENTS).read_bytes(), files[HTTP_REQUIREMENTS])
                    self.assertEqual(snapshot(project), files)

    def test_notification_packaging_refuses_payload_scope_media_and_count_drift(self):
        import copy
        from tools.transaction_guest_project import HTTP_REQUIREMENTS, package_effect_requirements
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = app.create(root / "source", "java", draft_id="bob", http_profile=HTTP_PROFILE)
            files = snapshot(project); model = json.loads(files["capsule-project.json"]); original = json.loads(files[HTTP_REQUIREMENTS])
            mutated = []
            for key,value in (("namespace","order-drafts-alice"),("companionDigest","sha256:"+"0"*64),
                    ("binding","qualified-http"),("operation","put-once"),("idempotencyProfile","qualified-http-v1:"+"b"*64),
                    ("adapter","qualified-http-put-once-v1"),("payloadFormat","http-put-once-bytes-v1"),
                    ("count",2),("requestedExpiryUnixMillis","1"),("authority",{"installed":True}),
                    ("payload",{"bytes":"AA==","mediaType":"application/vnd.lsf.order-draft-v1","metadata":[["authorization","synthetic-not-a-credential"]]})):
                changed=copy.deepcopy(original);changed[key]=value;mutated.append(changed)
            for key,value in (("maximum_payload_bytes",65536),("maximum_response_bytes",2048),("maximum_attempts",4)):
                changed=copy.deepcopy(original);changed["ceiling"][key]=value;mutated.append(changed)
            for index,changed in enumerate(mutated):
                with self.subTest(index=index):
                    candidate=dict(files);candidate[HTTP_REQUIREMENTS]=json.dumps(changed).encode()
                    output=root/("refused-"+str(index));output.mkdir()
                    with self.assertRaisesRegex(ValueError,"deferred-http-requirements-drift"):
                        package_effect_requirements(output,model,candidate)
                    self.assertEqual(list(output.iterdir()),[])

    def test_notification_selector_requires_exact_namespace_and_command_query_contract(self):
        import copy
        from tools.transaction_guest_project import reference_http_requirements
        with tempfile.TemporaryDirectory() as temporary:
            project=app.create(Path(temporary)/"source","rust",draft_id="a"*32,http_profile=HTTP_PROFILE)
            files=snapshot(project);model=json.loads(files["capsule-project.json"]);declaration=json.loads(files["transaction-binding.json"])
            self.assertEqual(reference_http_requirements(model,files["transaction-binding.json"],HTTP_PROFILE)["namespace"],"order-drafts-"+"a"*32)
            for namespace in ("orders","order-drafts-Alice","order-drafts-","order-drafts-"+"a"*33):
                with self.subTest(namespace=namespace),self.assertRaises(ValueError):
                    reference_http_requirements(model,json.dumps(dict(declaration,namespace=namespace)).encode(),HTTP_PROFILE)
            changed=copy.deepcopy(declaration);changed["operations"][0]["operation"]="update"
            with self.assertRaisesRegex(ValueError,"order-draft notification binding"):
                reference_http_requirements(model,json.dumps(changed).encode(),HTTP_PROFILE)

    def test_unconfigured_http_emits_no_obsolete_descriptor_and_invalid_profile_writes_nothing(self):
        from tools.transaction_guest_project import HTTP_REQUIREMENTS
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);project=app.create(root/"source","rust")
            self.assertFalse((project/HTTP_REQUIREMENTS).exists())
            self.assertNotIn("httpProfile",json.loads((project/"order-draft-source.json").read_bytes()))
            for index,profile in enumerate(("retained-put-once-v1","qualified-http-v1:"+"A"*64,"https://private.invalid/token")):
                output=root/str(index)
                with self.assertRaisesRegex(ValueError,"configured qualified HTTP"):
                    app.create(output,"rust",http_profile=profile)
                self.assertFalse(output.exists())

    def test_draft_identity_is_bounded_before_the_language_creator_can_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ordinal, draft in enumerate(("", "-alice", "Alice", "a/b", "a\x00b", "a" * 33, "Ã©")):
                with self.subTest(draft=draft):
                    output = root / str(ordinal)
                    with self.assertRaisesRegex(ValueError, "order-draft identity"):
                        app.create(output, "java", draft_id=draft)
                    self.assertFalse(output.exists())
            project = app.create(root / "maximum", "c", draft_id="a" * 32)
            self.assertEqual(json.loads((project / "transaction-binding.json").read_bytes())["namespace"], "order-drafts-" + "a" * 32)

    def test_application_world_refuses_unreviewed_auxiliary_and_immediate_authority(self):
        for addition in ("import latent:http/client@0.2.0;", "import latent:service/invoke@0.1.0;"):
            with self.subTest(addition=addition), self.assertRaisesRegex(ValueError, "unreviewed language runtime"):
                app.application_world(("package x:y;\nworld service {\n" + addition + "\n}").encode())
        with self.assertRaisesRegex(ValueError, "unreviewed auxiliary"):
            app.application_world(b"package x:y;\nworld service {\n}\nworld extra { import latent:http/client@0.2.0; }")


if __name__ == "__main__":
    unittest.main()

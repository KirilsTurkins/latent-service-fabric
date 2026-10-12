"""Synthetic input/refusal tests; these are not node or compiler qualification."""
from __future__ import annotations

import json
import copy
from pathlib import Path
import tempfile
import unittest

from tools import stateful_reference_conductor as conductor
from tools.stateful_reference_project import create

PUBLICATION = "publication:sha256:" + "1" * 64


def write(path: Path, value):
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())


def fixture(root: Path):
    project = create(root / "project", "java", draft_id="alice")
    directory = root / "artifact"
    directory.mkdir()
    component = b"\0asm\x0d\0\x01\0synthetic-byte-identity-fixture"
    source = b'{"source-only-fixture":true}'
    model = json.loads((project / "capsule-project.json").read_bytes())
    manifest = {"metadata": {"name": model["service"], "tenant": "examples"},
                "component": {"digest": conductor.digest(component), "world": conductor.WORLD}}
    deployment = {"metadata": {"name": model["name"], "tenant": "examples"},
                  "spec": {"service": model["service"], "release": conductor.digest(component), "grants": [],
                           "resources": model["limits"]}}
    observation = {"formatVersion": 1, "buildType": conductor.BUILD_TYPES["java"],
                   "source": {"snapshotDigest": conductor.digest(source)},
                   "componentDigest": conductor.digest(component), "componentSize": len(component),
                   "materials": [{"name": "synthetic-source-unit-fixture", "digest": "sha256:" + "2" * 64, "size": 1}],
                   "parameters": {"sourceOnlyFixture": True}}
    write(directory / "build-observation.json", observation)
    complete = {"formatVersion": 1, "packageAssembled": True,
                "observationDigest": conductor.digest((directory / "build-observation.json").read_bytes()),
                "sourceDigest": conductor.digest(source), "componentDigest": conductor.digest(component)}
    for name, value in (("BUILD-COMPLETE.json", complete), ("source-inputs.json", source),
                        ("component.wasm", component), ("capsule.json", manifest), ("deployment.json", deployment),
                        ("transaction-binding.json", (project / "transaction-binding.json").read_bytes())):
        write(directory / name, value)
    return directory


class StatefulReferenceConductor(unittest.TestCase):
    def test_browser_matrix_requires_six_guest_languages_and_two_distinct_entity_plans(self):
        from tools.run_stateful_reference_browser import validate_inputs
        entity = {"directory": "/private/app", "publication": PUBLICATION, "resultPolicy": "draft-result",
                  "statePolicies": ["draft-state"], "grants": []}
        source = {"schemaVersion": "latent.stateful-reference.conductor-input.v1", "scope": "single-backend",
                  "cli": "/private/latent", "node": "/public/node", "operatorConfiguration": "/private/operator.json",
                  "aliceConfiguration": "/private/alice.json", "backends": [{"language": "java",
                      "entities": {name: dict(entity) for name in ("alice", "bob")}}],
                  "browser": {"origin": "http://stateful.test:19092", "toolchain": "/public/browser", "chrome": "/public/chrome",
                              "frontend": {}, "users": []}}
        self.assertEqual(validate_inputs(source)[0], "single-backend")
        matrix = copy.deepcopy(source)
        matrix["scope"] = "six-backend-matrix"
        matrix["backends"] = [{"language": language, "entities": copy.deepcopy(source["backends"][0]["entities"])}
                              for language in conductor.BUILD_TYPES]
        self.assertEqual(len(validate_inputs(matrix)[1]), 6)
        changes = []
        missing = copy.deepcopy(matrix); missing["backends"].pop(); changes.append(missing)
        duplicate = copy.deepcopy(matrix); duplicate["backends"][1]["language"] = duplicate["backends"][0]["language"]; changes.append(duplicate)
        omitted = copy.deepcopy(source); del omitted["backends"][0]["entities"]["bob"]; changes.append(omitted)
        unexpected = dict(source, permissions="synthetic-not-a-grant"); changes.append(unexpected)
        escaped = dict(source, node="/public/node\x00other"); changes.append(escaped)
        for candidate in changes:
            with self.subTest(candidate=candidate["scope"]), self.assertRaises(RuntimeError):
                validate_inputs(candidate)

    def test_byte_identity_refuses_relabelled_compiler_component_and_unassembled_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = fixture(Path(temporary))
            selected = conductor.Backend.read("java", "alice", directory, PUBLICATION)
            self.assertEqual(selected.entity, "alice")
            self.assertEqual(selected.component_digest, conductor.digest((directory / "component.wasm").read_bytes()))
            with self.assertRaisesRegex(RuntimeError, "compiler-and-source"):
                conductor.Backend.read("rust", "alice", directory, PUBLICATION)
            with self.assertRaisesRegex(RuntimeError, "entity-namespace"):
                conductor.Backend.read("java", "bob", directory, PUBLICATION)
            original = (directory / "component.wasm").read_bytes()
            (directory / "component.wasm").write_bytes(original + b"changed")
            with self.assertRaisesRegex(RuntimeError, "component-identity"):
                conductor.Backend.read("java", "alice", directory, PUBLICATION)
            (directory / "component.wasm").write_bytes(original)
            complete = json.loads((directory / "BUILD-COMPLETE.json").read_bytes())
            complete["packageAssembled"] = False
            write(directory / "BUILD-COMPLETE.json", complete)
            with self.assertRaisesRegex(RuntimeError, "assembled-app-build"):
                conductor.Backend.read("java", "alice", directory, PUBLICATION)

    def test_closed_json_and_byte_bounds_refuse_before_any_operator_request(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises((RuntimeError, ValueError)):
                conductor.decode(raw)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "input", b"12345")
            with self.assertRaisesRegex(RuntimeError, "byte-limit"):
                conductor.regular(root, "input", 4)
            self.assertEqual(conductor.regular(root, "input", 5), b"12345")

    def test_unknown_deployment_result_stops_without_trigger_or_mutation_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = conductor.Backend.read("java", "alice", fixture(root), PUBLICATION)
            class Client:
                directory = root
                calls = 0
                arguments = []
                def call(self, *arguments, **kwargs):
                    self.calls += 1
                    self.arguments.append(arguments)
                    if arguments[:2] == ("release", "get"):
                        return {"data": {"release": {"publication": {"id": PUBLICATION, "tenant": "examples"},
                            "digest": backend.component_digest, "world": conductor.WORLD,
                            "service": conductor.decode(backend.companion)["capsule"], "admitted": True,
                            "packageDigest": "sha256:" + "3" * 64}}}
                    if arguments[:2] == ("deployment", "get"):
                        return {"data": {"deployment": None, "stateVersion": "1"}}
                    return {"outcomeKnown": False, "data": {}}
            client = Client()
            with self.assertRaisesRegex(RuntimeError, "mutation-uncertain"):
                conductor.select(client, backend, result_policy="draft-result", state_policies=["draft-state"],
                    grants=[{"capability": capability, "policy": "draft-policy"} for capability in
                            ("latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0")])
            self.assertEqual(client.calls, 3)
            self.assertEqual(sum("apply" in arguments for arguments in client.arguments), 1)
            self.assertFalse(any("trigger" in arguments for arguments in client.arguments))

    def test_original_attestation_refuses_cross_publication_and_requires_explicit_entity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = conductor.Backend.read("java", "alice", fixture(root), PUBLICATION)
            class Client:
                arguments = []
                def call(self, *arguments):
                    self.arguments.append(arguments)
                    return {"data": {"command": {"commandId": "command", "metadataDurable": True,
                        "outcome": "COMMAND_OUTCOME_COMMITTED", "applicationStateCommitted": True,
                        "source": {"publicationId": "publication:sha256:" + "4" * 64,
                                   "componentDigest": backend.component_digest}, "key": {"clientKey": "original"}}}}
            client = Client()
            with self.assertRaisesRegex(RuntimeError, "original-app-command"):
                conductor.attest_originals(client, backend, {"language": "java", "lostCommit": {
                    "clientKey": "original", "commandId": "command", "effectIds": [], "resultDigest": "sha256:" + "5" * 64}})
            self.assertEqual(len(client.arguments), 1)
            args = client.arguments[0]
            self.assertEqual(args[args.index("--entity") + 1], "alice")
            self.assertEqual(args[args.index("--client-key") + 1], "original")

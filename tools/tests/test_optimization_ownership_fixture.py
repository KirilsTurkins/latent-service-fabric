"""Actual functional bytes and rehashed semantic mutations; no release claims."""
import base64
import gzip
from pathlib import Path, PurePosixPath
import tempfile
import unittest

from tools.artifact_identity_runner.files import reference
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import canonical, decode, read_json, require, sha256, uint
from tools.optimization_backend_revision.ownership.fixtures import load
from tools.optimization_backend_revision.ownership.parse import parse

FIXTURE = Path(__file__).parent / "fixtures" / "ownership_functional_control.json.gz"


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        with gzip.open(FIXTURE, "rb") as stream:
            encoded = stream.read(2 * 1024**2 + 1)
        require(len(encoded) <= 2 * 1024**2, "functional-fixture-expansion-bound")
        value = decode(encoded, 2 * 1024**2)
        require(value["scope"] == "functional-debug-only-nonqualifying-original-bytes" and len(value["files"]) <= 40,
                "functional-fixture-scope-or-count")
        for name, row in value["files"].items():
            path = PurePosixPath(name)
            require(not path.is_absolute() and all(part not in (".", "..") for part in path.parts), "functional-fixture-path")
            raw = base64.b64decode(row["base64"], validate=True)
            require(len(raw) == uint(row["bytes"]) <= 1024**2 and sha256(raw) == row["sha256"], "functional-fixture-original-bytes")
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

    def document(self, name):
        return read_json(self.root / name)

    def replace(self, name, value):
        (self.root / name).write_bytes(canonical(value))

    def replay(self, *, mode="normal"):
        artifacts = Artifacts(self.root, inventory(self.root), ())
        manifest = load(reference(self.root / "ownership-fixtures.json", self.root), artifacts,
                        self.document("ownership-fixture-input.json")["components"])
        raw_name = "normal/ownership.json" if mode == "normal" else "fixtures/generated/ownership.json"
        input_name = "ownership-fixtures.json" if mode == "normal" else "ownership-fixture-input.json"
        return parse(self.document(raw_name), self.document(mode + "-plan.json"), self.document("identity.json"), manifest,
                     reference(self.root / input_name, self.root)["sha256"], artifacts, "control")

    def mutate_raw(self, change, *, mode="normal"):
        name = "normal/ownership.json" if mode == "normal" else "fixtures/generated/ownership.json"
        value = self.document(name)
        change(value)
        self.replace(name, value)
        if mode == "fixtures":
            # Rebind both dependent hashes so the semantic oracle is exercised.
            manifest = self.document("ownership-fixtures.json")
            manifest["generation"] = reference(self.root / name, self.root)
            self.replace("ownership-fixtures.json", manifest)
        return self.replay(mode=mode)


class FunctionalReplayTests(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.fixture = Fixture(self.owner.name)

    def tearDown(self):
        self.owner.cleanup()

    def test_original_generation_and_normal_graphs(self):
        generated = self.fixture.replay(mode="fixtures")
        normal = self.fixture.replay()
        self.assertEqual(generated["work"], {"context_validation_checks": "13", "invoke_attempts": "0",
                                             "preparation_attempts": "1", "proof_attempts": "0"})
        self.assertEqual(normal["work"]["invoke_attempts"], "26")
        self.assertEqual(len(normal["calls"]), 24)
        self.assertEqual([row["drop_reason"] for row in normal["proofs"]], ["owner_scope_exit"] * 2)

    def test_removing_a_proof_and_decrementing_work_cannot_qualify(self):
        def mutate(value):
            value["samples"].pop()
            value["work"].update(invoke_attempts="25", proof_attempts="1")
        with self.assertRaisesRegex(ValueError, "population-incomplete"):
            self.fixture.mutate_raw(mutate)

    def test_declared_pending_requires_actual_live_native_store(self):
        def mutate(value):
            value["samples"][-1]["pending_resources"]["live_stores"] = "0"
        with self.assertRaisesRegex(ValueError, "pending-native-owners-not-live"):
            self.fixture.mutate_raw(mutate)

    def test_pending_boolean_cannot_be_replaced_by_a_finished_call(self):
        with self.assertRaisesRegex(ValueError, "proof-work-or-pending"):
            self.fixture.mutate_raw(lambda value: value["samples"][-1].update(pending=False))

    def test_retained_raw_input_after_native_cleanup_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "snapshot-conservation"):
            self.fixture.mutate_raw(lambda value: value["raw_inputs_after_shutdown"]["snapshot"].update(live_raw_owners="1"))

    def test_guest_dispatch_cannot_be_moved_after_the_action(self):
        def mutate(value):
            action = uint(value["samples"][-1]["action_nanos"])
            for parent in [value["samples"][-1]["at_pending"], value["samples"][-1]["after"],
                           value["before_factory_shutdown"]["input"], value["raw_inputs_after_shutdown"]]:
                origin = uint(parent["origin_offset_nanos"])
                for row in parent["snapshot"]["records"]:
                    if row["token"] == "1" and row["phase"] == "guest_call_start":
                        row["observed_nanos"] = str(action + 1 - origin)
        with self.assertRaises(ValueError):
            self.fixture.mutate_raw(mutate)

    def test_zero_preparations_cannot_disguise_context_generation_work(self):
        with self.assertRaisesRegex(ValueError, "work-counters-not-population"):
            self.fixture.mutate_raw(lambda value: value["work"].update(preparation_attempts="0"), mode="fixtures")

    def test_generation_must_not_create_a_guest_store(self):
        with self.assertRaisesRegex(ValueError, "fresh-store-population"):
            self.fixture.mutate_raw(lambda value: value["samples"][0]["resources"].update(stores_created="1"), mode="fixtures")

    def test_rehashed_context_output_cannot_expose_hidden_claims(self):
        def mutate(value):
            row = next(row for row in value["samples"] if row.get("shape") == "context-64k")
            output = row["result"]["output"]
            payload = decode(output["utf8"].encode())
            payload[0]["principal"]["claims"].append(["private.claim", "hidden"])
            raw = canonical(payload)
            output.update(utf8=raw.decode(), bytes=str(len(raw)), sha256=sha256(raw))
        with self.assertRaisesRegex(ValueError, "context-claims-or-principal"):
            self.fixture.mutate_raw(mutate)

    def test_lost_compiler_join_cannot_hide_behind_factory_success(self):
        with self.assertRaisesRegex(ValueError, "compiler-unjoined-workers"):
            self.fixture.mutate_raw(lambda value: value["compiler_after_shutdown"].update(workers_joined=1))


if __name__ == "__main__":
    unittest.main()

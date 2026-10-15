"""Historical receipt and synthetic refusal controls; no native qualification."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import configuration as cfg
from tools.java_transaction_qualification import lifecycle, offline_campaign, schema_view

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tools/tests/fixtures/java_schema_views_cacccd.json"


def binding(schema, *, tenant=cfg.TENANT, namespace=cfg.NAMESPACE, incarnation=1, entity=None):
    # Independent encoding of the documented native scope; altered scopes below
    # produce well-formed hashes and therefore exercise association, not syntax.
    prefix = b"state-v1\0"
    for text in (tenant, namespace):
        raw = text.encode("utf-8")
        prefix += len(raw).to_bytes(2, "little") + raw
    prefix += incarnation.to_bytes(8, "little") + bytes([entity is not None])
    if entity is not None:
        raw = entity.encode("utf-8")
        prefix += len(raw).to_bytes(2, "little") + raw
    return hashlib.sha256(b"lsf-namespace-view-v2\0" + prefix + schema.encode("ascii")).digest()


def number(view, offset, value):
    changed = bytearray(view)
    changed[offset:offset + 8] = value.to_bytes(8, "little")
    return list(changed)


class AfterSchema(Exception):
    """Stop a mocked conductor after its genuine schema observation check."""


class SchemaViewControls(unittest.TestCase):
    @contextmanager
    def descriptors(self):
        # These are digest-bound collector descriptors, not signed packages or
        # native authority. The current descriptor uses the genuine public file.
        value = json.loads(FIXTURE.read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            items = []
            writer = json.loads((ROOT / "apps/latentd/tests/fixtures/current-java-writer/transaction-binding.json").read_bytes())
            for name, key in (("original", "previous"), ("target", "current")):
                directory = Path(temporary) / name
                (directory / "project").mkdir(parents=True)
                descriptor = copy.deepcopy(writer)
                descriptor["stateSchema"] = value[key]["stateSchema"]
                raw = (json.dumps(descriptor, sort_keys=True) + "\n").encode()
                (directory / "project/transaction-binding.json").write_bytes(raw)
                items.append(SimpleNamespace(directory=directory,
                    companion_digest="sha256:" + hashlib.sha256(raw).hexdigest()))
            yield value["previous"]["view"], value["current"]["view"], *items

    def check(self, old, new, original, target):
        schema_view.advanced(old, new, original, target)

    def conductor(self, old, new, original, target, *, current=True):
        subject = offline_campaign.OfflineCampaign.__new__(offline_campaign.OfflineCampaign)
        subject.current_v2, subject.writer = current, "put-once-writer-v2"
        subject.campaign = SimpleNamespace(query=Mock(return_value=({}, None)),
            items={"put-once-legacy-v1": original, "put-once-writer-v2": target},
            publications={"put-once-compatible-v2": "compatible"})
        subject.node = SimpleNamespace()
        subject.recipient, subject.quiesce = Mock(return_value={}), Mock()
        subject.inspect = Mock(side_effect=[{"view": old}, {"view": new}])
        subject.snapshot = Mock(side_effect=[({"root": "snapshot", "name": "original"},
            {"snapshotDigest": "snapshot", "manifestDigest": "manifest"}), AfterSchema()])
        subject.action = Mock(side_effect=[{"completed": False}, {"completed": True}])
        return subject

    def test_actual_closed_schema_views_old_guard_red_and_exact_scope_check_green(self):
        with self.descriptors() as (old, new, original, target):
            fixture = json.loads(FIXTURE.read_bytes())
            self.assertEqual(fixture["sourceCommit"], "cacccd6d919eb1176189ddd85328a45efd1dff31")
            self.assertNotEqual(old[3:35], new[3:35])
            self.assertEqual(bytes(old[3:35]), binding(lifecycle.schema(original)))
            self.assertEqual(bytes(new[3:35]), binding(lifecycle.schema(target)))
            with self.assertRaisesRegex(ValueError, "actual-native-history-epoch-advanced"):
                offline_campaign.epoch_advanced(old, new, "schema")
            self.check(old, new, original, target)

    def test_old_view_foreign_tenant_or_namespace_is_refused(self):
        with self.descriptors() as (old, new, original, target):
            for scope in ({"tenant": "another-tenant"}, {"namespace": "another-namespace"}):
                altered = old[:]
                altered[3:35] = binding(lifecycle.schema(original), **scope)
                with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "schema-view-binding"):
                    self.check(altered, new, original, target)

    def test_new_view_foreign_tenant_or_namespace_is_refused(self):
        with self.descriptors() as (old, new, original, target):
            for scope in ({"tenant": "another-tenant"}, {"namespace": "another-namespace"}):
                altered = new[:]
                altered[3:35] = binding(lifecycle.schema(target), **scope)
                with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "schema-view-binding"):
                    self.check(old, altered, original, target)

    def test_other_entity_and_even_matching_foreign_incarnation_are_refused(self):
        with self.descriptors() as (old, new, original, target):
            for scope in ({"entity": "alice"}, {"incarnation": 2}):
                left, right = old[:], new[:]
                left[3:35] = binding(lifecycle.schema(original), **scope)
                right[3:35] = binding(lifecycle.schema(target), **scope)
                if "incarnation" in scope:
                    left, right = number(left, 35, 2), number(right, 35, 2)
                with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "schema-view-binding"):
                    self.check(left, right, original, target)

    def test_incorrect_original_target_or_unchanged_schema_cannot_match(self):
        with self.descriptors() as (old, new, original, target):
            for left, right in ((target, original), (target, target), (original, original)):
                with self.subTest(left=left.directory.name, right=right.directory.name), \
                     self.assertRaisesRegex(ValueError, "schema-view-binding"):
                    self.check(old, new, left, right)

    def test_copying_old_binding_to_new_view_is_not_a_schema_transition(self):
        with self.descriptors() as (old, new, original, target):
            new[3:35] = old[3:35]
            with self.assertRaisesRegex(ValueError, "schema-view-binding"):
                self.check(old, new, original, target)

    def test_schema_epoch_must_advance_exactly_once_without_overflow(self):
        with self.descriptors() as (old, new, original, target):
            for before, after in ((1, 1), (2, 1), (1, 3), (2**64 - 1, 1)):
                with self.subTest(before=before, after=after), self.assertRaisesRegex(ValueError, "schema-history-advanced"):
                    self.check(number(old, 51, before), number(new, 51, after), original, target)

    def test_generation_must_advance_exactly_once_without_overflow(self):
        with self.descriptors() as (old, new, original, target):
            for before, after in ((22, 22), (22, 21), (22, 24), (2**64 - 1, 1)):
                with self.subTest(before=before, after=after), self.assertRaisesRegex(ValueError, "schema-history-advanced"):
                    self.check(number(old, 43, before), number(new, 43, after), original, target)

    def test_schema_transition_cannot_advance_or_regress_recovery_epoch(self):
        with self.descriptors() as (old, new, original, target):
            for before, after in ((1, 2), (2, 1)):
                with self.subTest(before=before, after=after), self.assertRaisesRegex(ValueError, "schema-history-advanced"):
                    self.check(number(old, 59, before), number(new, 59, after), original, target)

    def test_malformed_zero_or_boolean_view_fields_are_refused(self):
        with self.descriptors() as (old, new, original, target):
            invalid = [new[:-1], new + [0], [True] + new[1:], [0] + new[1:],
                       number(new, 35, 0), number(new, 43, 0), number(new, 51, 0), number(new, 59, 0)]
            for changed in invalid:
                with self.subTest(changed=changed[:3], size=len(changed)), self.assertRaises(ValueError):
                    self.check(old, changed, original, target)

    def test_retained_companion_is_rechecked_and_missing_or_changed_bytes_fail(self):
        with self.descriptors() as (old, new, original, target):
            self.check(old, new, original, target)
            for item in (original, target):
                path = item.directory / "project/transaction-binding.json"
                raw = path.read_bytes()
                path.write_bytes(raw + b" ")
                with self.assertRaisesRegex(ValueError, "retained-original-companion"):
                    self.check(old, new, original, target)
                path.write_bytes(raw)
                path.unlink()
                with self.assertRaises(OSError):
                    self.check(old, new, original, target)
                path.write_bytes(raw)

    def test_malformed_present_schema_is_fatal_without_legacy_fallback(self):
        with self.descriptors() as (old, new, original, target):
            path = target.directory / "project/transaction-binding.json"
            for malformed in ("sha256:" + "0" * 64, "sha256:" + "A" * 64, "sha256:abc", 17, None):
                value = {"stateSchema": malformed}
                raw = json.dumps(value).encode()
                path.write_bytes(raw)
                target.companion_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
                subject = self.conductor(old, new, original, target)
                with self.subTest(malformed=malformed), patch.object(offline_campaign, "epoch_advanced") as legacy:
                    with self.assertRaises((ValueError, TypeError)):
                        subject.schema(4)
                    legacy.assert_not_called()
                    self.assertEqual(subject.action.call_count, 2)
                    self.assertEqual(subject.snapshot.call_count, 1)

    def test_current_schema_uses_exact_original_and_writer_descriptors_before_further_work(self):
        with self.descriptors() as (old, new, original, target):
            subject = self.conductor(old, new, original, target)
            with patch.object(schema_view, "advanced", wraps=schema_view.advanced) as checked, \
                 patch.object(offline_campaign, "epoch_advanced", side_effect=AssertionError("legacy fallback")):
                with self.assertRaises(AfterSchema):
                    subject.schema(4)
            checked.assert_called_once_with(old, new, original, target)
            self.assertEqual(subject.inspect.call_count, 2)
            self.assertEqual(subject.action.call_count, 2)
            self.assertEqual(subject.action.call_args_list[0].args[0]["action"], "stage-migration")
            self.assertEqual(subject.action.call_args_list[1].args[0]["action"], "complete-migration")

    def test_legacy_schema_path_keeps_strict_original_binding_guard(self):
        with self.descriptors() as (old, new, original, target):
            new[3:35] = old[3:35]
            subject = self.conductor(old, new, original, target, current=False)
            with patch.object(schema_view, "advanced", side_effect=AssertionError("current schema helper")), \
                 patch.object(offline_campaign, "epoch_advanced", wraps=offline_campaign.epoch_advanced) as legacy:
                with self.assertRaises(AfterSchema):
                    subject.schema(4)
            legacy.assert_called_once_with(old, new, "schema")
            new[3] ^= 1
            with self.assertRaisesRegex(ValueError, "history-epoch-advanced"):
                self.conductor(old, new, original, target, current=False).schema(4)

    def test_original_recovery_guard_still_refuses_schema_or_scope_changes(self):
        with self.descriptors() as (old, new, _, _):
            recovered = number(old, 59, 2)
            offline_campaign.epoch_advanced(old, recovered, "recovery")
            with self.assertRaisesRegex(ValueError, "history-epoch-advanced"):
                offline_campaign.epoch_advanced(old, number(new, 59, 2), "recovery")
            recovered[3] ^= 1
            with self.assertRaisesRegex(ValueError, "history-epoch-advanced"):
                offline_campaign.epoch_advanced(old, recovered, "recovery")


if __name__ == "__main__":
    unittest.main()

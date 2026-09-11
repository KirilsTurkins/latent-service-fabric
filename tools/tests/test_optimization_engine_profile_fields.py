"""Complete metadata mutations; no compilation or guest execution."""
import unittest

from tools.optimization_backend_revision.engine import profile_fields
from tools.optimization_evidence.common import EvidenceError


# Independent literal expectation from base 2e575479 config/profile.rs plus the
# fixed standalone engine plan. This is an arithmetic fixture, not build proof.
_CONTROL = """
component-model=enabled
component-model-async=enabled
fuel=enabled
epoch-interruption=enabled
memory-accounting=aggregate-linear-memory
ambient-wasi-authority=none
cpu-feature-policy=native-host-detection
dispatch-policy=wasmtime-component-phase-1
target=x86_64-unknown-linux-gnu
cpu=host-baseline
instance-allocation-strategy=on_demand
copy-on-write-images=true
prepared-cache-enabled=true
hostcall-fuel=configured-bounded-transfer-v1
value-codec=canonical-json-v1
maximum-component-bytes=16777216
maximum-memory-bytes=67108864
maximum-fuel=10000000000
fuel-async-yield-interval=10000
maximum-wasm-stack-bytes=524288
async-stack-bytes=2097152
prepared-cache-maximum-entries=8
prepared-cache-maximum-source-bytes=134217728
prepared-cache-maximum-metadata-bytes=67108864
prepared-cache-maximum-compiled-image-bytes=536870912
maximum-artifact-metadata-bytes=1048576
maximum-concurrent-preparations=4
maximum-active-instances=4
maximum-instances-per-store=128
maximum-memories-per-store=16
maximum-tables-per-store=128
maximum-table-elements=10000
invocation-log-maximum-entries=8
invocation-log-maximum-bytes=16384
retained-log-maximum-entries=256
retained-log-maximum-bytes=524288
epoch-ticks=1
epoch-tick-interval-millis=5
pooling-maximum-instances=1
pooling-maximum-component-instance-bytes=1048576
pooling-maximum-core-instance-bytes=1048576
pooling-maximum-core-instances-per-component=4
pooling-maximum-memories-per-component=2
pooling-maximum-tables-per-component=2
pooling-linear-memory-keep-resident-bytes=0
hostcall-fuel-bytes=131072
compiler-workers=2
maximum-preparation-waiters=68
maximum-waiters-per-preparation=68
maximum-ready-preparations=68
maximum-preparation-document-bytes=21233664
value-max-input-bytes=1048576
value-max-output-bytes=1048576
value-max-depth=32
value-max-nodes=16384
value-max-string-bytes=262144
value-max-collection-items=4096
value-max-type-nodes=4096
value-max-type-name-bytes=256
value-max-lifted-bytes=16777216
value-max-decoded-value-bytes=16777216
context-exposure-policy=explicit-allowlists-v1
context-metadata-prefix-count=1
context-metadata-prefix-0=guest.
context-claim-key-count=0
context-baggage-key-count=0
"""
_ADDED = """
engine-layout-policy=wasmtime-47.0.3-bounded-v1
compiler-optimization=speed
memory-reservation-bytes=4294967296
memory-reservation-for-growth-bytes=2147483648
memory-guard-bytes=33554432
memory-may-move=true
guard-before-linear-memory=true
async-stack-zeroing=false
pooling-unused-warm-slots=0
pooling-decommit-batch-size=1
pooling-table-keep-resident-bytes=0
pooling-async-stack-keep-resident-bytes=0
"""
DIGEST = "blake3:" + "1" * 64


def fixture(variant="control", profile="D0"):
    values = dict(line.split("=", 1) for line in _CONTROL.splitlines() if line)
    values["configuration-digest"] = DIGEST
    allocator = "pooling" if profile.startswith("P") else "on-demand"
    optimization = "speed-and-size" if profile.endswith("1") else "speed"
    selected = {"variant": variant, "engine_profile_id": profile, "requested_engine": None}
    if variant == "candidate":
        selected["requested_engine"] = {"allocator": allocator, "optimization": optimization}
        values.update(line.split("=", 1) for line in _ADDED.splitlines() if line)
        values["compiler-optimization"] = optimization
        if allocator == "pooling":
            values.update({"instance-allocation-strategy": "pooling", "pooling-maximum-instances": "4",
                           "memory-reservation-bytes": "67108864", "memory-reservation-for-growth-bytes": "0",
                           "memory-guard-bytes": "0"})
    return values, selected


class EngineProfileFieldsTests(unittest.TestCase):
    def validate(self, config, selected, target="x86_64-unknown-linux-gnu", cpu="host-baseline"):
        return profile_fields.validate(config, selected, target, cpu)

    def test_all_five_profiles_accept_complete_metadata_without_mutating_it(self):
        for variant, name in (("control", "D0"), ("candidate", "D0"), ("candidate", "P0"),
                              ("candidate", "D1"), ("candidate", "P1")):
            value, selected = fixture(variant, name)
            before = value.copy()
            self.assertEqual(self.validate(value, selected), DIGEST)
            self.assertEqual(value, before)
            self.assertEqual(len(value), 67 if variant == "control" else 79)

    def test_every_policy_field_is_required_and_has_its_exact_value(self):
        for variant in ("control", "candidate"):
            value, selected = fixture(variant)
            for field in value:
                with self.subTest(variant=variant, field=field, mutation="missing"):
                    missing = value.copy()
                    del missing[field]
                    with self.assertRaises(EvidenceError):
                        self.validate(missing, selected)
                if field != "configuration-digest":
                    with self.subTest(variant=variant, field=field, mutation="changed"):
                        with self.assertRaises(EvidenceError):
                            self.validate(dict(value, **{field: value[field] + "-changed"}), selected)

    def test_old_control_requires_its_existing_residency_key_and_rejects_new_fields(self):
        value, selected = fixture()
        self.assertEqual(value["pooling-linear-memory-keep-resident-bytes"], "0")
        self.validate(value, selected)
        for field, content in (line.split("=", 1) for line in _ADDED.splitlines() if line):
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                self.validate(dict(value, **{field: content}), selected)
        candidate, plan = fixture("candidate")
        with self.assertRaises(EvidenceError):
            self.validate(candidate, selected)
        with self.assertRaises(EvidenceError):
            self.validate(value, plan)

    def test_pooling_and_optimization_profiles_cannot_cross(self):
        for source in ("D0", "P0", "D1", "P1"):
            value, _ = fixture("candidate", source)
            for target in ("D0", "P0", "D1", "P1"):
                if target != source:
                    _, selected = fixture("candidate", target)
                    with self.subTest(source=source, target=target), self.assertRaises(EvidenceError):
                        self.validate(value, selected)

    def test_selector_target_cpu_extra_fields_and_nonstring_values_are_rejected(self):
        value, selected = fixture()
        for changed in ({"variant": "other"}, {"engine_profile_id": "P0"}, {"engine_profile_id": []},
                        {"requested_engine": {"allocator": "on-demand", "optimization": "speed"}}):
            with self.subTest(changed=changed), self.assertRaises(EvidenceError):
                self.validate(value, dict(selected, **changed))
        with self.assertRaises(EvidenceError):
            self.validate(value, None)
        for key, changed in (("unexpected", "0"), ("epoch-ticks", 1), ("prepared-cache-enabled", True),
                             ("context-claim-key-0", "role"), ("instance-allocation-strategy", "on-demand"),
                             ("maximum-preparation-waiters", "64")):
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                self.validate(dict(value, **{key: changed}), selected)
        for target, cpu in (("aarch64-unknown-linux-gnu", "host-baseline"),
                            ("x86_64-unknown-linux-gnu", "other-cpu")):
            with self.subTest(target=target, cpu=cpu), self.assertRaises(EvidenceError):
                self.validate(value, selected, target, cpu)
        altered = dict(value, target="aarch64-unknown-linux-gnu", cpu="bounded-label")
        self.assertEqual(self.validate(altered, selected, altered["target"], altered["cpu"]), DIGEST)

    def test_digest_is_syntactic_only_and_bad_or_oversized_values_are_rejected(self):
        value, selected = fixture()
        for digest in ("", "sha256:" + "1" * 64, "blake3:" + "F" * 64,
                       "blake3:" + "1" * 63, DIGEST + "\n", None, 123):
            with self.subTest(digest=digest), self.assertRaises(EvidenceError):
                self.validate(dict(value, **{"configuration-digest": digest}), selected)
        another = "blake3:" + "a" * 64
        self.assertEqual(self.validate(dict(value, **{"configuration-digest": another}), selected), another)
        with self.assertRaises(EvidenceError):
            self.validate({str(n): "0" for n in range(129)}, selected)
        with self.assertRaises(EvidenceError):
            self.validate(dict(value, target="x" * 129), selected, "x" * 129)


if __name__ == "__main__":
    unittest.main()

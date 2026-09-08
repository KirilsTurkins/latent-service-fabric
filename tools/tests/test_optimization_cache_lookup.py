"""Actual work equations, fully rehashed event tampering and allocation scope."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.optimization_cache_lookup import allocations, events, model
from tools.optimization_cache_lookup.files import Artifacts
from tools.artifact_identity_runner.files import reference


class EventFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.plan = model.plan("smoke", pattern="seeded-uniform")
        encoded, checksum = model.trace(self.plan)
        self.record = {"probe_process": {"process_id": 100}}
        self.put("plan", self.plan)
        self.put("identity", {"source": "synthetic-pure-parser-fixture"})
        (self.root / "trace.bin").write_bytes(encoded)
        self.record["trace"] = reference(self.root / "trace.bin", self.root)
        task = {"process_id": 100, "thread_id": 101, "start_time_ticks": 55}
        self.ready = {"schema": "latent.optimization.cache-lookup-ready.v1", "event": "ready", "process_id": 100,
                      "plan_sha256": self.record["plan"]["sha256"][7:], "identity_sha256": self.record["identity"]["sha256"][7:],
                      "trace_sha256": hashlib.sha256(encoded).hexdigest(), "thread_identity": task, "observation_hold_millis": 100}
        cache = {name: 0 for name in events.CACHE_FIELDS.split()}
        cache.update(entries=4, maximum_entries=4, source_bytes=8, maximum_source_bytes=8,
                     metadata_bytes=12, maximum_metadata_bytes=12, compiled_image_bytes=16,
                     maximum_compiled_image_bytes=16, maximum_concurrent_preparations=1, hits=16, misses=4)
        self.result = {**self.ready, "schema": "latent.optimization.cache-lookup-result.v1", "event": "measurement-complete",
                       "outcome": "passed", "warmup_hits": 16, "measured_hits": 256, "elapsed_nanos": "300000",
                       "cpu": {"clock": "CLOCK_THREAD_CPUTIME_ID", "resolution_nanos": "1", "before_nanos": "400", "after_nanos": "500"},
                       "coarse_thread_cpu": {side: {"identity": deepcopy(task), "user_ticks": 0, "system_ticks": 0} for side in ("before", "after")},
                       "before": cache, "after": dict(cache, hits=272), "checksum": str(checksum), "expected_checksum": str(checksum),
                       "all_tags_verified": True, "trace_bytes": str(len(encoded))}

    def put(self, name, value):
        path = self.root / (name + ".json")
        path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")
        self.record[name] = reference(path, self.root)

    def parse(self, extra=b""):
        self.put("ready", self.ready)
        self.put("result", self.result)
        log = self.root / "probe.log"
        log.write_bytes(b"\n" + (self.root / "ready.json").read_bytes() + b"\n" + (self.root / "result.json").read_bytes() + extra)
        self.record["log"] = reference(log, self.root)
        rows = [reference(path, self.root) for path in self.root.iterdir()]
        return events.parse(self.record, self.plan, Artifacts(self.root, rows))


class LookupReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lookup-replay-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = EventFixture(self.temporary.name)

    def test_fixed_population_and_independent_known_trace(self):
        self.assertEqual(len(list(model.population("smoke"))), 24)
        self.assertEqual(len(list(model.population("full"))), 168)
        encoded, checksum = model.trace(self.fixture.plan)
        self.assertEqual(checksum, 84065)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), "a30aada5737090522805d5fa42a87fa76b3c85983bc4a71361811508ff7fc3fa")
        hot, value = model.trace(model.plan("smoke", capacity=4096))
        self.assertEqual(hot, b"\xff\x0f" * 256)
        self.assertEqual(value, 4096 * 256 * 257 // 2)

    def test_positive_actual_clock_and_work_contract(self):
        result = self.fixture.parse()
        self.assertEqual(result["after"]["hits"] - result["before"]["hits"], 256)
        self.assertEqual(result["coarse_thread_cpu"]["after"]["user_ticks"], 0)

    def test_rehashed_false_checksum_and_wrong_hit_population_rejected(self):
        self.fixture.result["checksum"] = self.fixture.result["expected_checksum"] = "1"
        with self.assertRaisesRegex(ValueError, "lookup-work-or-output"):
            self.fixture.parse()
        self.fixture.result["checksum"] = self.fixture.result["expected_checksum"] = "84065"
        self.fixture.result["after"]["hits"] = 271
        with self.assertRaisesRegex(ValueError, "lookup-cache-state"):
            self.fixture.parse()

    def test_rehashed_altered_trace_is_not_a_new_accepted_workload(self):
        path = self.fixture.root / "trace.bin"
        encoded = bytearray(path.read_bytes())
        encoded[0] ^= 1
        path.write_bytes(encoded)
        self.fixture.record["trace"] = reference(path, self.fixture.root)
        self.fixture.ready["trace_sha256"] = self.fixture.result["trace_sha256"] = hashlib.sha256(encoded).hexdigest()
        with self.assertRaisesRegex(ValueError, "lookup-trace-does-not-match-plan"):
            self.fixture.parse()

    def test_crossed_task_and_regressing_actual_cpu_rejected(self):
        self.fixture.result["coarse_thread_cpu"]["after"]["identity"]["thread_id"] += 1
        with self.assertRaisesRegex(ValueError, "lookup-crossed-cpu-task"):
            self.fixture.parse()
        self.fixture.result["coarse_thread_cpu"]["after"]["identity"]["thread_id"] -= 1
        self.fixture.result["cpu"]["after_nanos"] = "399"
        with self.assertRaisesRegex(ValueError, "lookup-invalid-thread-cpu"):
            self.fixture.parse()

    def test_rehashed_resident_cost_or_hidden_eviction_rejected(self):
        for name in ("compiled_image_bytes", "evictions", "invalidations"):
            with self.subTest(name=name):
                old = self.fixture.result["after"][name]
                self.fixture.result["after"][name] += 1
                with self.assertRaisesRegex(ValueError, "lookup-cache-state"):
                    self.fixture.parse()
                self.fixture.result["after"][name] = old

    def test_extra_event_and_changed_identity_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "lookup-extra-event"):
            self.fixture.parse(b'{"event":"ready"}\n')
        self.fixture.result["identity_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "lookup-event-input-association"):
            self.fixture.parse()


def recording(ip=1, function=None):
    names = ["latent-wasmtime-cache-lookup", function or model.SYMBOL, "measurement.rs"]
    strings = b"".join(b"s " + format(len(name.encode()), "x").encode() + b" " + name.encode() + b"\n" for name in names)
    return (b"v 10400 3\nX /probe --bounded\nI 1000 10000\n" + strings
            + b"i 100 1 2 3 1\nt " + str(ip).encode() + b" 0\na e 1\nc 0\n+ 0\n- 0\n+ 0\n"
            + b"c 1\n# strings: 3\n# ips: 1\n")


class AllocationAttributionTests(unittest.TestCase):
    def replay(self, data):
        with tempfile.TemporaryDirectory(prefix="lookup-allocation-") as directory:
            path = Path(directory) / "profile.txt"
            path.write_bytes(data)
            return allocations.replay_attribution(path, "latent-wasmtime-cache-lookup")

    def test_actual_named_frames_are_counted_from_allocation_events(self):
        whole, state = self.replay(recording())
        self.assertEqual(whole["allocation_count"], "2")
        self.assertEqual((state.named_count, state.named_bytes, state.unresolved_count), (2, 28, 0))

    def test_zero_instruction_trace_is_unresolved_not_available_zero(self):
        whole, state = self.replay(recording(ip=0))
        self.assertEqual(whole["allocation_count"], "2")
        self.assertEqual(state.named_count, 0)
        self.assertEqual(state.unresolved_count, 2)

    def test_unresolved_probe_function_is_not_available_zero(self):
        _, state = self.replay(recording(function="??"))
        self.assertEqual(state.unresolved_count, 2)

    def test_other_fully_resolved_function_has_no_named_allocation(self):
        _, state = self.replay(recording(function="cache_setup"))
        self.assertEqual((state.named_count, state.unresolved_count), (0, 0))

    def test_folded_named_count_is_independent_of_whole_total(self):
        with tempfile.TemporaryDirectory(prefix="lookup-folded-") as directory:
            path = Path(directory) / "allocations.folded"
            path.write_bytes(("main;" + model.SYMBOL + " 2\nmain;setup 7\n").encode())
            self.assertEqual(allocations.folded_attribution(path), (9, 2))
            path.write_bytes(b"main;setup 9\n")
            self.assertEqual(allocations.folded_attribution(path), (9, 0))


if __name__ == "__main__":
    unittest.main()

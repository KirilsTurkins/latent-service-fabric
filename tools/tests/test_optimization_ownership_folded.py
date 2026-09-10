"""Explicit ownership folded limits; tiny streams exercise the same byte guards."""
import copy
import gzip
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import common, runs
from tools.artifact_identity_runner import files, run
from tools.optimization_backend_revision.ownership import allocations, evidence, model
from tools.optimization_cache_lookup import allocations as lookup
from tools.optimization_evidence.common import canonical

LEGACY = 64 * 1024**2
OWNERSHIP = 128 * 1024**2


def tiny_limit(value):
    # Validate the real public cap, then scale only the I/O guard in tests.
    # This exercises compression and decompression without 100 MiB fixtures.
    return common.folded_limit(value) // 1024**2


class FoldedBoundsTests(unittest.TestCase):
    def test_only_explicit_finite_caps_are_accepted_before_io(self):
        self.assertEqual(common.folded_limit(LEGACY), LEGACY)
        self.assertEqual(common.folded_limit(OWNERSHIP), OWNERSHIP)
        for value in (None, True, 0, -1, LEGACY + 1, OWNERSHIP + 1, 256 * 1024**2 + 1, float(LEGACY), str(OWNERSHIP)):
            for action in (lambda: files.compress_folded(None, None, maximum_bytes=value),
                           lambda: common.folded(None, maximum_bytes=value),
                           lambda: lookup.folded_attribution(None, maximum_bytes=value),
                           lambda: run.profile_reports(None, None, None, None, 0, 0, maximum_folded_bytes=value),
                           lambda: runs.allocation(None, None, None, maximum_folded_bytes=value)):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported-folded-byte-bound"):
                    action()

    def test_larger_stream_is_lossless_and_rejected_by_legacy_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "allocations.folded"
            payload = b"selected 1\n" * 9  # 99 bytes: above scaled 64, below scaled 128.
            original.write_bytes(payload)
            with patch.object(files, "folded_limit", side_effect=tiny_limit):
                with self.assertRaisesRegex(ValueError, "artifact-file-bound"):
                    files.compress_folded(original, root)
                self.assertEqual(original.read_bytes(), payload)
                ref = files.compress_folded(original, root, maximum_bytes=OWNERSHIP)
            compressed = root / ref["path"]
            self.assertFalse(original.exists())
            self.assertEqual(gzip.decompress(compressed.read_bytes()), payload)
            # Real cap selection is independently validated above; scale both
            # replay guards identically to exercise actual gzip expansion.
            for reader, module in ((common.folded, common), (lookup.folded_attribution, lookup)):
                with patch.object(module, "folded_limit", side_effect=lambda value: value // 1024**2):
                    with self.assertRaises(ValueError):
                        reader(compressed)
                    result = reader(compressed, maximum_bytes=OWNERSHIP)
                    self.assertEqual(result, {"rows": "9", "total": "9"} if module is common else (9, 0))

    def test_rehashed_compressed_stream_cannot_exceed_declared_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.folded.gz"
            path.write_bytes(gzip.compress(b"selected 1\n" * 12, mtime=0))
            for reader, module in ((common.folded, common), (lookup.folded_attribution, lookup)):
                with patch.object(module, "folded_limit", side_effect=lambda value: value // 1024**2):
                    with self.assertRaises(ValueError):
                        reader(path, maximum_bytes=OWNERSHIP)

    def test_default_and_explicit_legacy_compression_bytes_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first.folded", root / "second.folded"
            first.write_bytes(b"selected;allocator 3\n")
            second.write_bytes(first.read_bytes())
            a = files.compress_folded(first, root)
            b = files.compress_folded(second, root, maximum_bytes=LEGACY)
            self.assertEqual(a["sha256"], b["sha256"])
            self.assertEqual(a["bytes"], b["bytes"])

    def test_profile_extraction_passes_the_same_bound_to_both_streams(self):
        for chosen in (None, OWNERSHIP):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "heaptrack.zst").write_bytes(b"raw")
                def command(argv, log, *args, **kwargs):
                    log.write_bytes(b"helper output")
                    if "--print-flamegraph" in argv:
                        Path(argv[-1]).write_bytes(b"selected 1\n")
                options = {} if chosen is None else {"maximum_folded_bytes": chosen}
                now = 1_000_000_000
                deadline = now + (60 if chosen is None else 240) * 1_000_000_000
                cutoff = min(deadline, now + 120 * 1_000_000_000)
                with patch.object(run.time, "monotonic_ns", return_value=now), \
                        patch.object(run, "command", side_effect=command) as commands, \
                        patch.object(run, "compress_folded", wraps=files.compress_folded) as compress:
                    run.profile_reports(root / "heaptrack", "printer", "zstd", root, deadline, 1024, **options)
                self.assertEqual([call.args[4] for call in commands.call_args_list],
                                 [deadline, deadline, cutoff, cutoff])
                self.assertEqual([call.kwargs["remaining"] for call in commands.call_args_list], [1024] * 4)
                self.assertEqual([call.kwargs for call in compress.call_args_list],
                                 [{"maximum_bytes": chosen or LEGACY,
                                   "deadline": cutoff, "remaining": 1024}] * 2)

    def test_whole_and_selected_replay_receive_the_declared_limit(self):
        refs = {name: {"path": name + (".folded.gz" if name in ("allocations", "peak") else "")}
                for name in ("raw", "report", "interpreted", "allocations", "peak")}
        artifact_rows = {name: {"path": name} for name in (
            "report.process.json", "interpreted.process.json", "allocations.log", "peak.log",
            "allocations.log.process.json", "peak.log.process.json")}
        artifacts = SimpleNamespace(rows=artifact_rows, path=lambda ref: Path(ref["path"]), json=lambda ref: {})
        record = {"profile_refs": refs, "command": ["heaptrack", "--output", "prefix", "/probe"]}
        suite = {"tools": {name: {"sha256": "unused"} for name in ("heaptrack_print", "zstd")}}
        whole = {"command": "/probe", "allocation_count": "1", "peak_live_bytes": "1"}
        for chosen in (None, OWNERSHIP):
            options = {} if chosen is None else {"maximum_folded_bytes": chosen}
            with patch.object(runs, "helper"), patch.object(runs, "replay", return_value=whole), \
                    patch.object(runs, "folded", return_value={"total": "1"}) as folded:
                self.assertEqual(runs.allocation(record, suite, artifacts, **options), whole)
            self.assertEqual([call.kwargs for call in folded.call_args_list], [{"maximum_bytes": chosen or LEGACY}] * 2)
        statistics = [{"allocation_count": 1}] * 3
        state = SimpleNamespace(folded_labels={"selected"}, statistics=statistics, named_count=1, unresolved_count=0)
        proof = [{"demangled": "constructor", "raw": "raw_constructor"}, {"demangled": "poll", "raw": "raw_poll"}]
        with patch.object(allocations, "proofs", return_value=proof), \
                patch.object(lookup, "replay_attribution", return_value=(whole, state)), \
                patch.object(lookup, "folded_attribution", return_value=(1, 1)) as selected:
            allocations.attribute(record, {}, {}, {}, artifacts, whole)
        selected.assert_called_once_with(Path("allocations.folded.gz"), {"selected"}, maximum_bytes=OWNERSHIP)

    def test_suite_cap_erasure_or_change_rejects_before_build_access(self):
        from tools.tests.test_optimization_ownership_schemas import validator
        schema = validator("ownership-suite").schema["properties"]["plan"]
        import jsonschema
        for profile in ("smoke", "full"):
            plan = model.suite_plan(profile)
            self.assertEqual(plan["maximum_folded_expanded_bytes"], str(OWNERSHIP))
            jsonschema.validate(plan, schema)
            for maximum in (None, str(LEGACY), str(OWNERSHIP + 1), True):
                changed = copy.deepcopy(plan)
                if maximum is None:
                    del changed["maximum_folded_expanded_bytes"]
                else:
                    changed["maximum_folded_expanded_bytes"] = maximum
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(changed, schema)
                value = dict.fromkeys("builds runner_source runner_source_after status reason elapsed_nanos tools symbols runs artifacts".split())
                value.update(schema=model.SCHEMA, profile=profile, plan=changed)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "suite.json"
                    path.write_bytes(canonical(value))
                    with self.assertRaisesRegex(ValueError, "ownership-suite-plan-changed"):
                        evidence.validate_suite(path)


if __name__ == "__main__":
    unittest.main()

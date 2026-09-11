"""Closed codec-only limit extensions leave historical readers strict by default."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import heaptrack, runs
from tools.artifact_identity_runner import files, run
from tools.optimization_backend_revision.ownership import allocations as ownership
from tools.optimization_cache_lookup import allocations as lookup, files as cache_files
from tools.tests.test_artifact_identity_heaptrack import recording


LEGACY_BYTES, CODEC_BYTES = 1024**3, 2 * 1024**3
LEGACY_RECORDS, CODEC_RECORDS = 4_000_000, 12_000_000
validate_total = files.total_limit
validate_records = heaptrack.record_limit


def tiny_total(value):
    return validate_total(value) // (64 * 1024**2)  # 16 / 32 actual bytes.


def tiny_records(value):
    return validate_records(value) // 100_000  # 40 / 120 actual records.


class SharedStorageLimits(unittest.TestCase):
    def test_only_two_exact_integer_totals_are_accepted_before_io(self):
        self.assertEqual(validate_total(LEGACY_BYTES), LEGACY_BYTES)
        self.assertEqual(validate_total(CODEC_BYTES), CODEC_BYTES)
        for value in (None, True, False, 0, -1, LEGACY_BYTES + 1, CODEC_BYTES + 1,
                      3 * 1024**3, float(LEGACY_BYTES), str(CODEC_BYTES)):
            actions = (
                lambda: files.total_bytes(None, maximum_total_bytes=value),
                lambda: files.inventory(None, None, maximum_total_bytes=value),
                lambda: files.warm(None, None, None, maximum_total_bytes=value),
                lambda: cache_files.inventory(None, maximum_total_bytes=value),
                lambda: cache_files.Artifacts(None, None, maximum_total_bytes=value),
                lambda: run.collect(None, None, None, None, None, 0, "", "", maximum_total_bytes=value),
            )
            for action in actions:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported-artifact-total-byte-bound"):
                    action()

    def test_actual_small_files_keep_default_strict_and_explicit_extension_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("a", "b", "c"):
                (root / name).write_bytes(b"123456789")  # Total 27: between scaled caps.
            with patch.object(files, "total_limit", side_effect=tiny_total), \
                    patch.object(cache_files, "total_limit", side_effect=tiny_total):
                for action in (lambda: files.total_bytes(root), lambda: files.inventory(root, root),
                               lambda: cache_files.inventory(root)):
                    with self.assertRaisesRegex(ValueError, "bound"):
                        action()
                self.assertEqual(files.total_bytes(root, maximum_total_bytes=CODEC_BYTES), 27)
                retained = files.inventory(root, root, maximum_total_bytes=CODEC_BYTES)
                rows = cache_files.inventory(root, maximum_total_bytes=CODEC_BYTES)
                self.assertEqual(rows, list(retained.values()))
                with self.assertRaisesRegex(ValueError, "byte-bound"):
                    cache_files.Artifacts(root, rows)
                artifacts = cache_files.Artifacts(root, rows, maximum_total_bytes=CODEC_BYTES)
                self.assertEqual(artifacts.path(rows[0]).read_bytes(), b"123456789")
                self.assertEqual(files.warm(root, retained, root, maximum_total_bytes=CODEC_BYTES)["bytes"], "27")
                with self.assertRaises(ValueError):
                    files.warm(root, retained, root)
                # Rehashing a larger population cannot authorize bytes over its cap.
                (root / "d").write_bytes(b"123456")
                crossed = [files.reference(path, root) for path in sorted(root.iterdir())]
                for action in (lambda: files.total_bytes(root, maximum_total_bytes=CODEC_BYTES),
                               lambda: files.inventory(root, root, maximum_total_bytes=CODEC_BYTES),
                               lambda: cache_files.inventory(root, maximum_total_bytes=CODEC_BYTES),
                               lambda: cache_files.Artifacts(root, crossed, maximum_total_bytes=CODEC_BYTES)):
                    with self.assertRaisesRegex(ValueError, "bound"):
                        action()

    def test_explicit_historical_cap_has_identical_artifacts_and_file_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input").write_bytes(b"small")
            self.assertEqual(files.inventory(root, root), files.inventory(root, root, maximum_total_bytes=LEGACY_BYTES))
            self.assertEqual(cache_files.inventory(root), cache_files.inventory(root, maximum_total_bytes=LEGACY_BYTES))
            self.assertEqual(files.total_bytes(root), files.total_bytes(root, maximum_total_bytes=LEGACY_BYTES))
            with patch.object(files, "MAX_FILE_BYTES", 4), self.assertRaisesRegex(ValueError, "storage-bound"):
                files.total_bytes(root, maximum_total_bytes=CODEC_BYTES)
            row = files.reference(root / "input", root)
            row["bytes"] = str(256 * 1024**2 + 1)
            with self.assertRaisesRegex(ValueError, "byte-bound"):
                cache_files.Artifacts(root, [row], maximum_total_bytes=CODEC_BYTES)

    @unittest.skipUnless(sys.platform == "linux", "owned normal collector imports Linux resource")
    def test_live_collector_uses_selected_remaining_budget_and_closes_on_overflow(self):
        for chosen in (None, CODEC_BYTES):
            maximum = LEGACY_BYTES if chosen is None else chosen
            with self.subTest(chosen=chosen), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary_path = root / "probe"
                binary_path.write_bytes(b"ELF")
                binary = files.reference(binary_path, root)
                closed = []

                class Owner:
                    def __init__(self, command, log, *args, **kwargs):
                        log.write_bytes(b"")
                        self.events, self.polls = [], 0
                        self.selector = SimpleNamespace(get_map=lambda: {})
                        self.receipt = {"exit_code": None}
                    def exited(self):
                        return False
                    def poll(self):
                        self.polls += 1
                        if self.polls > 2:
                            raise AssertionError("live output escaped the selected remaining budget")
                    def close(self):
                        self.receipt["exit_code"] = 0
                        closed.append(self.polls)
                    def resources(self):
                        return {"test": "no child was launched"}

                row = {"mode": "normal", "command": [str(binary_path)], "ready": None, "probe_process": None}
                options = {} if chosen is None else {"maximum_total_bytes": chosen}
                with patch.object(run, "OwnedProcess", Owner), \
                        patch.object(run, "total_bytes", return_value=maximum - 19) as used, \
                        patch.object(run, "directory_bytes", side_effect=(18, 20)) as live, \
                        patch.object(run, "cgroup", return_value={}), \
                        patch.object(run.time, "sleep"), \
                        patch("resource.getrusage", return_value=SimpleNamespace(ru_utime=0, ru_stime=0)):
                    with self.assertRaisesRegex(ValueError, "profile-artifact-total-bound"):
                        run.collect(row, root / "run", binary, None, root, 2**63, "", "", **options)
                used.assert_called_once_with(root, maximum_total_bytes=maximum)
                self.assertEqual(live.call_count, 2)  # 18 fits, then 20 exceeds remaining 19.
                self.assertEqual(closed, [2])
                self.assertEqual(row["process"]["exit_code"], 0)
                self.assertIsNotNone(row["log"])


class SharedRecordLimits(unittest.TestCase):
    def test_only_two_exact_integer_record_counts_are_accepted_before_io(self):
        self.assertEqual(validate_records(LEGACY_RECORDS), LEGACY_RECORDS)
        self.assertEqual(validate_records(CODEC_RECORDS), CODEC_RECORDS)
        for value in (None, True, False, 0, -1, LEGACY_RECORDS + 1, CODEC_RECORDS + 1,
                      20_000_000, float(LEGACY_RECORDS), str(CODEC_RECORDS)):
            actions = (
                lambda: heaptrack.replay(None, maximum_records=value),
                lambda: lookup.replay_attribution(None, None, maximum_records=value),
                lambda: runs.allocation(None, None, None, maximum_records=value),
                lambda: lookup.attribute(None, None, None, None, None, None, maximum_records=value),
                lambda: ownership.attribute(None, None, None, None, None, None, maximum_records=value),
            )
            for action in actions:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported-record-bound"):
                    action()

    def test_whole_and_selected_readers_enforce_same_closed_record_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interpreted.heaptrack"
            path.write_bytes(recording(b"+ 0\n- 0\n" * 25))
            with patch.object(heaptrack, "record_limit", side_effect=tiny_records):
                for reader in (lambda **kw: heaptrack.replay(path, **kw),
                               lambda **kw: lookup.replay_attribution(path, "m", ("f",), **kw),
                               lambda **kw: lookup.replay_attribution(path, "m", (("f",), ()),
                                                                     state_type=ownership.Attribution, **kw)):
                    with self.assertRaisesRegex(ValueError, "bound"):
                        reader()
                    observed = reader(maximum_records=CODEC_RECORDS)
                    raw = observed[0] if isinstance(observed, tuple) else observed
                    self.assertEqual(raw["allocation_count"], "25")
                    self.assertEqual(raw["peak_live_bytes"], "16")
                    self.assertEqual(raw["remaining_live_bytes"], "0")
                _, state = lookup.replay_attribution(path, "m", (("f",), ()),
                    state_type=ownership.Attribution, maximum_records=CODEC_RECORDS)
                self.assertEqual(state.statistics[2]["allocation_count"], 25)
                self.assertEqual(state.statistics[2]["live_bytes"], 0)
                self.assertEqual(state.statistics[2]["peak_live_bytes"], 16)
                path.write_bytes(recording(b"+ 0\n- 0\n" * 100))
                for reader in (lambda: heaptrack.replay(path, maximum_records=CODEC_RECORDS),
                               lambda: lookup.replay_attribution(path, "m", maximum_records=CODEC_RECORDS)):
                    with self.assertRaisesRegex(ValueError, "bound"):
                        reader()

    def test_historical_replay_is_identical_and_other_guards_remain_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interpreted.heaptrack"
            data = recording()
            path.write_bytes(data)
            expected = heaptrack.replay(path)
            self.assertEqual(heaptrack.replay(path, maximum_records=LEGACY_RECORDS), expected)
            self.assertEqual(heaptrack.replay(path, maximum_records=CODEC_RECORDS), expected)
            for name, maximum in (("MAX_BYTES", len(data) - 1), ("MAX_LINE_BYTES", 10), ("MAX_TABLE_ENTRIES", 2)):
                with patch.object(heaptrack, name, maximum), self.assertRaisesRegex(ValueError, "bound"):
                    heaptrack.replay(path, maximum_records=CODEC_RECORDS)

    def test_whole_and_both_attribution_wrappers_forward_explicit_or_default_count(self):
        refs = {name: {"path": name + (".folded.gz" if name in ("allocations", "peak") else "")}
                for name in ("raw", "report", "interpreted", "allocations", "peak")}
        rows = {name: {"path": name} for name in ("report.process.json", "interpreted.process.json",
                "allocations.log", "peak.log", "allocations.log.process.json", "peak.log.process.json")}
        artifacts = SimpleNamespace(rows=rows, path=lambda ref: Path(ref["path"]), json=lambda ref: {})
        record = {"profile_refs": refs, "command": ["heaptrack", "--output", "prefix", "/probe"]}
        suite = {"tools": {name: {"sha256": "unused"} for name in ("heaptrack_print", "zstd")}}
        whole = {"command": "/probe", "allocation_count": "1", "peak_live_bytes": "1"}
        state = SimpleNamespace(folded_labels={"selected"}, statistics=[{"allocation_count": 1}] * 3,
                                named_count=1, named_bytes=1, unresolved_count=0)
        for chosen in (None, CODEC_RECORDS):
            expected = LEGACY_RECORDS if chosen is None else chosen
            options = {} if chosen is None else {"maximum_records": chosen}
            with patch.object(runs, "helper"), patch.object(runs, "replay", return_value=whole) as replay, \
                    patch.object(runs, "folded", return_value={"total": "1"}):
                self.assertEqual(runs.allocation(record, suite, artifacts, **options), whole)
            replay.assert_called_once_with(Path("interpreted"), maximum_records=expected)
            with patch.object(lookup, "symbol_proof", return_value=None), \
                    patch.object(lookup, "replay_attribution", return_value=(whole, state)) as selected, \
                    patch.object(lookup, "folded_attribution", return_value=(1, 1)):
                lookup.attribute(record, {}, {}, {}, artifacts, whole, **options)
            self.assertEqual(selected.call_args.kwargs, {"maximum_records": expected})
            with patch.object(ownership, "proofs", return_value=[None, None]), \
                    patch.object(lookup, "replay_attribution", return_value=(whole, state)) as selected, \
                    patch.object(lookup, "folded_attribution", return_value=(1, 1)):
                ownership.attribute(record, {}, {}, {}, artifacts, whole, **options)
            self.assertEqual(selected.call_args.kwargs,
                             {"state_type": ownership.Attribution, "maximum_records": expected})


if __name__ == "__main__":
    unittest.main()

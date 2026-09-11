"""Explicit large folded export watches; tiny fixtures, no profiler processes."""
from contextlib import contextmanager
import gzip
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import common, runs
from tools.artifact_identity_runner import files, helpers, run
from tools.optimization_cache_lookup import allocations

MIB = 1024**2
MUTATION = 512 * MIB


class ExportLimitTests(unittest.TestCase):
    def test_new_folded_preset_is_explicit_and_strictly_typed_before_io(self):
        for size in (64, 128, 256, 512):
            self.assertEqual(common.folded_limit(size * MIB), size * MIB)
        for value in (None, True, False, 0, -1, MUTATION - 1, MUTATION + 1,
                      float(MUTATION), str(MUTATION)):
            actions = (
                lambda: files.compress_folded(None, None, maximum_bytes=value),
                lambda: common.folded(None, maximum_bytes=value),
                lambda: allocations.folded_attribution(None, maximum_bytes=value),
                lambda: run.profile_reports(None, None, None, None, 0, 0, maximum_folded_bytes=value),
                lambda: runs.allocation(None, None, None, maximum_folded_bytes=value),
            )
            for action in actions:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsupported-folded-byte-bound"):
                    action()

    def test_compression_and_both_readers_preserve_all_bytes_and_old_limits(self):
        actual_limit = common.folded_limit
        tiny = lambda value: actual_limit(value) // MIB
        payload = b"selected 1\n" * 32  # 352 bytes, between scaled 256 and 512.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "allocations.folded"
            original.write_bytes(payload)
            with patch.object(files, "folded_limit", side_effect=tiny):
                for options in ({}, {"maximum_bytes": 128 * MIB}, {"maximum_bytes": 256 * MIB}):
                    with self.assertRaisesRegex(ValueError, "artifact-file-bound"):
                        files.compress_folded(original, root, **options)
                    self.assertEqual(original.read_bytes(), payload)
                ref = files.compress_folded(original, root, maximum_bytes=MUTATION)
            compressed = root / ref["path"]
            self.assertEqual(gzip.decompress(compressed.read_bytes()), payload)
            self.assertFalse(original.exists())
            for module, reader, expected in ((common, common.folded, {"rows": "32", "total": "32"}),
                                             (allocations, allocations.folded_attribution, (32, 0))):
                with patch.object(module, "folded_limit", side_effect=tiny):
                    for options in ({}, {"maximum_bytes": 128 * MIB}, {"maximum_bytes": 256 * MIB}):
                        with self.assertRaises(ValueError):
                            reader(compressed, **options)
                    self.assertEqual(reader(compressed, maximum_bytes=MUTATION), expected)
                    compressed.write_bytes(gzip.compress(b"selected 1\n" * 47, mtime=0))
                    with self.assertRaises(ValueError):
                        reader(compressed, maximum_bytes=MUTATION)
                    compressed.write_bytes(gzip.compress(payload, mtime=0))

    def test_directory_watch_default_and_explicit_upper_boundary(self):
        self.assertEqual(helpers.DirectoryLimits().maximum_file_bytes, 256 * MIB)
        large = helpers.DirectoryLimits(maximum_file_bytes=MUTATION)
        for value in (None, True, False, 0, -1, MUTATION + 1, float(MUTATION), str(MUTATION)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "helper-directory-limits"):
                helpers.DirectoryLimits(maximum_file_bytes=value)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            @contextmanager
            def listing(_path):
                yield [SimpleNamespace(path=str(root / "export.folded"),
                                       stat=lambda **_options: SimpleNamespace(st_mode=stat.S_IFREG, st_size=size))]

            # Mock only stat-reported lengths; no large file is allocated/read.
            with patch.object(helpers.os, "scandir", side_effect=listing):
                size = 256 * MIB
                self.assertEqual(helpers.directory_bytes(root), size)
                size += 1
                with self.assertRaisesRegex(ValueError, "helper-artifact-byte-bound"):
                    helpers.directory_bytes(root)
                self.assertEqual(helpers.directory_bytes(root, large), size)
                size = MUTATION
                self.assertEqual(helpers.directory_bytes(root, large), size)
                size += 1
                with self.assertRaisesRegex(ValueError, "helper-artifact-byte-bound"):
                    helpers.directory_bytes(root, large)

    def test_only_folded_helpers_receive_large_watch_and_remaining_budget_is_unchanged(self):
        for selected in (None, 64 * MIB, 128 * MIB, 256 * MIB, MUTATION):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "heaptrack.zst").write_bytes(b"synthetic raw; no helper runs")

                def command(argv, log, *_args, **_options):
                    log.write_bytes(b"synthetic helper output")
                    if "--print-flamegraph" in argv:
                        Path(argv[-1]).write_bytes(b"selected 1\n")

                options = {} if selected is None else {"maximum_folded_bytes": selected}
                now = 1_000_000_000
                deadline = now + (60 if selected is None else 240) * 1_000_000_000
                cutoff = min(deadline, now + 120 * 1_000_000_000)
                with patch.object(run.time, "monotonic_ns", return_value=now), \
                        patch.object(run, "command", side_effect=command) as commands, \
                        patch.object(run, "compress_folded", wraps=files.compress_folded) as compress:
                    run.profile_reports(root / "heaptrack", "printer", "zstd", root, deadline, 4096, **options)
                calls = commands.call_args_list
                self.assertEqual(len(calls), 4)
                for call in calls[:2]:
                    self.assertNotIn("directory_limits", call.kwargs)
                    self.assertEqual(call.args[4], deadline)
                for call in calls[2:]:
                    self.assertEqual(call.args[4], cutoff)
                    self.assertEqual(call.kwargs["directory_limits"], helpers.DirectoryLimits(
                        maximum_file_bytes=max(256 * MIB, selected or 64 * MIB)))
                for call in calls:
                    self.assertEqual(call.kwargs["remaining"], 4096)
                    self.assertEqual(call.args[2], 120)
                self.assertEqual([call.kwargs for call in compress.call_args_list],
                                 [{"maximum_bytes": selected or 64 * MIB,
                                   "deadline": cutoff, "remaining": 4096}] * 2)

    def test_retained_file_and_total_storage_bounds_are_unchanged(self):
        self.assertEqual(files.MAX_FILE_BYTES, 256 * MIB)
        self.assertEqual(files.MAX_TOTAL_BYTES, 1024 * MIB)
        self.assertEqual(common.MAX_FOLDED_BYTES, 64 * MIB)
        large = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=256 * MIB + 1))
        with patch.object(files, "files", return_value=[large]):
            with self.assertRaisesRegex(ValueError, "artifact-storage-bound"):
                files.total_bytes(Path("unused"))
        ordinary = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=256 * MIB))
        with patch.object(files, "files", return_value=[ordinary] * 4):
            self.assertEqual(files.total_bytes(Path("unused")), 1024 * MIB)
        with patch.object(files, "files", return_value=[ordinary] * 5):
            with self.assertRaisesRegex(ValueError, "artifact-storage-bound"):
                files.total_bytes(Path("unused"))

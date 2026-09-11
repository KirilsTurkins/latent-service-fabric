"""Real tiny gzip streams with deterministic time/disk guards; no subprocesses."""
from contextlib import contextmanager
import gc
import gzip
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner import files, helpers


class CompressionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.path = self.profile / "allocations.folded"
        self.payload = b"caller;allocator 7\n" * 128
        self.path.write_bytes(self.payload)
        self.compressed = self.path.with_suffix(".folded.gz")

    def expected_gzip(self):
        baseline = self.root / "baseline"
        baseline.mkdir()
        source = baseline / "allocations.folded"
        source.write_bytes(self.payload)
        ref = files.compress_folded(source, self.root)
        return (self.root / ref["path"]).read_bytes()

    def assert_retained(self):
        self.assertEqual(self.path.read_bytes(), self.payload)
        self.assertTrue(self.compressed.is_file())

    @contextmanager
    def replay_read(self, action):
        original = gzip.open

        @contextmanager
        def opening(*args, **kwargs):
            with original(*args, **kwargs) as stream:
                class Reader:
                    def read(self, size):
                        result = stream.read(size)
                        action()
                        return result
                yield Reader()
        with patch.object(files.gzip, "open", side_effect=opening):
            yield

    @contextmanager
    def stale_gzip_directory_size(self):
        original = helpers.os.scandir
        destination = self.compressed

        @contextmanager
        def scanning(path):
            with original(path) as children:
                class Entry:
                    def __init__(self, child):
                        self.child, self.path = child, child.path

                    def stat(self, **kwargs):
                        value = self.child.stat(**kwargs)
                        return SimpleNamespace(st_mode=value.st_mode,
                                               st_file_attributes=getattr(value, "st_file_attributes", 0),
                                               st_size=0 if Path(self.path) == destination else value.st_size)
                yield (Entry(child) for child in children)
        with patch.object(helpers.os, "scandir", side_effect=scanning):
            yield

    def test_exact_coexistence_budget_checks_only_the_bounded_profile_directory(self):
        expected = self.expected_gzip()
        (self.profile / "report.log").write_bytes(b"report")
        outside = self.root / "unrelated"
        outside.mkdir()
        for index in range(20):
            (outside / str(index)).write_bytes(b"outside this owned profile directory")
        remaining = len(self.payload) + len(expected) + len(b"report")
        with patch.object(files.time, "monotonic_ns", return_value=10), \
                patch.object(helpers, "directory_bytes", wraps=helpers.directory_bytes) as watched:
            ref = files.compress_folded(self.path, self.root, deadline=11, remaining=remaining)
        self.assertEqual(self.compressed.read_bytes(), expected)
        self.assertEqual(gzip.decompress(expected), self.payload)
        self.assertEqual(ref, files.reference(self.compressed, self.root))
        self.assertFalse(self.path.exists())
        self.assertTrue(watched.call_args_list)
        self.assertEqual({call.args[0] for call in watched.call_args_list}, {self.profile})
        self.assertTrue(all(call.args[1].maximum_files == 16 for call in watched.call_args_list))

    def test_one_byte_short_coexistence_budget_keeps_input_and_partial_gzip(self):
        expected = self.expected_gzip()
        remaining = len(self.payload) + len(expected) - 1
        with self.assertRaisesRegex(ValueError, "folded-compression-total-bound"):
            files.compress_folded(self.path, self.root, remaining=remaining)
        self.assert_retained()
        self.assertGreater(self.compressed.stat().st_size, 0)
        self.assertLess(self.compressed.stat().st_size, len(expected))
        self.assertLessEqual(helpers.directory_bytes(self.profile), remaining)

    def test_stale_open_output_size_still_rejects_before_the_over_budget_write(self):
        expected = self.expected_gzip()
        remaining = len(self.payload) + len(expected) - 1
        unraisable = []
        with self.stale_gzip_directory_size(), patch.object(sys, "unraisablehook", unraisable.append):
            with self.assertRaisesRegex(ValueError, "folded-compression-total-bound"):
                files.compress_folded(self.path, self.root, remaining=remaining)
            gc.collect()
        self.assert_retained()
        self.assertGreater(self.compressed.stat().st_size, 0)
        self.assertLess(self.compressed.stat().st_size, len(expected))
        self.assertLessEqual(helpers.directory_bytes(self.profile), remaining)
        self.assertEqual(unraisable, [])

    def test_directory_minimum_is_not_a_replacement_for_larger_actual_sizes_or_caps(self):
        self.compressed.write_bytes(b"abc")
        with self.stale_gzip_directory_size():
            self.assertEqual(helpers.directory_bytes(self.profile,
                             minimum_file_sizes={self.compressed: 3}), len(self.payload) + 3)
        self.assertEqual(helpers.directory_bytes(self.profile,
                         minimum_file_sizes={self.compressed: 1}), len(self.payload) + 3)
        with self.assertRaisesRegex(ValueError, "helper-artifact-byte-bound"):
            helpers.directory_bytes(self.profile,
                                    minimum_file_sizes={self.compressed: files.MAX_FILE_BYTES + 1})
        with self.assertRaisesRegex(ValueError, "helper-artifact-count-or-type"):
            helpers.directory_bytes(self.profile, minimum_file_sizes={self.profile / "missing": 1})

    def test_retained_compressed_limit_is_checked_before_each_write(self):
        with patch.object(files, "MAX_FILE_BYTES", 16):
            with self.assertRaisesRegex(ValueError, "folded-compressed-file-bound"):
                files.compress_folded(self.path, self.root)
        self.assert_retained()
        self.assertGreater(self.compressed.stat().st_size, 0)
        self.assertLessEqual(self.compressed.stat().st_size, 16)

    def test_expired_deadline_rejects_before_hash_or_output_creation(self):
        with patch.object(files.time, "monotonic_ns", return_value=11), \
                patch.object(files, "fingerprint", wraps=files.fingerprint) as fingerprint:
            with self.assertRaisesRegex(TimeoutError, "folded-compression-deadline"):
                files.compress_folded(self.path, self.root, deadline=11)
        fingerprint.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.payload)
        self.assertFalse(self.compressed.exists())

    def test_initial_hash_cannot_spend_the_deadline_and_then_start_compression(self):
        now = [10]
        original = files.fingerprint

        def fingerprint(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 11
            return result
        with patch.object(files.time, "monotonic_ns", side_effect=lambda: now[0]), \
                patch.object(files, "fingerprint", side_effect=fingerprint):
            with self.assertRaisesRegex(TimeoutError, "folded-compression-deadline"):
                files.compress_folded(self.path, self.root, deadline=11)
        self.assertEqual(self.path.read_bytes(), self.payload)
        self.assertFalse(self.compressed.exists())

    def test_compression_loop_deadline_preserves_partial_output(self):
        now = [10]
        unraisable = []
        original = gzip.GzipFile

        class SlowGzip(original):
            def write(self, data):
                result = super().write(data)
                now[0] = 11
                return result
        with patch.object(files.time, "monotonic_ns", side_effect=lambda: now[0]), \
                patch.object(files.gzip, "GzipFile", SlowGzip), \
                patch.object(sys, "unraisablehook", unraisable.append):
            with self.assertRaisesRegex(TimeoutError, "folded-compression-deadline"):
                files.compress_folded(self.path, self.root, deadline=11)
            gc.collect()
        self.assert_retained()
        self.assertGreater(self.compressed.stat().st_size, 0)
        self.assertEqual(unraisable, [])

    def test_roundtrip_loop_checks_deadline_after_actual_decompression(self):
        now = [10]
        with patch.object(files.time, "monotonic_ns", side_effect=lambda: now[0]), \
                self.replay_read(lambda: now.__setitem__(0, 11)):
            with self.assertRaisesRegex(TimeoutError, "folded-compression-deadline"):
                files.compress_folded(self.path, self.root, deadline=11)
        self.assert_retained()
        self.assertEqual(gzip.decompress(self.compressed.read_bytes()), self.payload)

    def test_roundtrip_loop_checks_coexisting_files_without_discarding_input(self):
        expected = self.expected_gzip()
        remaining = len(self.payload) + len(expected)
        with self.replay_read(lambda: (self.profile / "late.log").write_bytes(b"x")):
            with self.assertRaisesRegex(ValueError, "folded-compression-total-bound"):
                files.compress_folded(self.path, self.root, remaining=remaining)
        self.assert_retained()
        self.assertEqual(gzip.decompress(self.compressed.read_bytes()), self.payload)

    def test_final_reference_hash_cannot_expire_then_delete_original(self):
        now = [10]
        original = files.reference

        def reference(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 11
            return result
        with patch.object(files.time, "monotonic_ns", side_effect=lambda: now[0]), \
                patch.object(files, "reference", side_effect=reference):
            with self.assertRaisesRegex(TimeoutError, "folded-compression-deadline"):
                files.compress_folded(self.path, self.root, deadline=11)
        self.assert_retained()

    def test_source_change_still_fails_the_original_hash_roundtrip_check(self):
        original = files.fingerprint
        changed = b"different bytes at the owned source"

        def fingerprint(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == self.path:
                path.write_bytes(changed)
            return result
        with patch.object(files, "fingerprint", side_effect=fingerprint):
            with self.assertRaisesRegex(ValueError, "folded-compression-mismatch"):
                files.compress_folded(self.path, self.root, remaining=4096)
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(gzip.decompress(self.compressed.read_bytes()), changed)

    def test_guard_arguments_reject_bool_unbounded_and_wrong_types_before_io(self):
        options = [dict(deadline=value) for value in (True, False, -1, 1.0, "1")]
        options += [dict(remaining=value) for value in (True, False, -1, 2 * 1024**3 + 1, 1.0, "1")]
        with patch.object(files, "fingerprint", side_effect=AssertionError("unexpected I/O")):
            for selected in options:
                with self.subTest(selected=selected), self.assertRaisesRegex(ValueError, "folded-compression-.*-bound"):
                    files.compress_folded(self.path, self.root, **selected)

    def test_new_gzip_does_not_relax_the_sixteen_file_watch(self):
        for index in range(15):
            (self.profile / str(index)).touch()
        with self.assertRaisesRegex(ValueError, "helper-artifact-count-or-type"):
            files.compress_folded(self.path, self.root, remaining=4096)
        self.assert_retained()
        self.assertEqual(self.compressed.stat().st_size, 0)

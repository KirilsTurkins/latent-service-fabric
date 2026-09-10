"""One expanded scratch file; tiny real gzip fixtures, no helper processes."""
from contextlib import contextmanager
import gzip
import io
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import common
from tools.artifact_identity_runner import files, helpers, run

MIB = 1024**2
SCRATCH = 512 * MIB
RETAINED = 1024 * MIB


class ScratchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "probe"
        self.profile.mkdir()
        self.source = self.profile / "allocations.folded"
        self.destination = self.source.with_suffix(".folded.gz")
        self.payload = b"selected;actual-stack 1\n" * 64

    def expected_gzip(self):
        output = io.BytesIO()
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as writer:
            writer.write(self.payload)
        return output.getvalue()

    @contextmanager
    def stale_gzip_stat(self):
        original = helpers.os.scandir
        destination = self.destination

        @contextmanager
        def scanning(directory):
            with original(directory) as children:
                class Entry:
                    def __init__(self, entry):
                        self.entry, self.path = entry, entry.path

                    def stat(self, **options):
                        value = self.entry.stat(**options)
                        return SimpleNamespace(st_mode=value.st_mode,
                            st_size=0 if Path(self.path) == destination else value.st_size,
                            st_file_attributes=getattr(value, "st_file_attributes", 0))
                yield (Entry(entry) for entry in children)

        with patch.object(helpers.os, "scandir", side_effect=scanning):
            yield

    def test_scratch_is_a_closed_opt_in_and_rejects_invalid_pairs_before_io(self):
        for maximum in (64, 128, 256, 512):
            self.assertEqual(common.folded_scratch_limit(maximum * MIB, 0), 0)
        self.assertEqual(common.folded_scratch_limit(SCRATCH, SCRATCH), SCRATCH)
        invalid = [(SCRATCH, value) for value in
                   (None, True, False, -1, SCRATCH - 1, SCRATCH + 1, float(SCRATCH), str(SCRATCH))]
        invalid += [(size * MIB, SCRATCH) for size in (64, 128, 256)]
        for maximum, temporary in invalid:
            actions = (
                lambda: common.folded_scratch_limit(maximum, temporary),
                lambda: files.compress_folded(None, None, maximum_bytes=maximum,
                    temporary_folded_bytes=temporary),
                lambda: run.profile_reports(None, None, None, None, 0, 0,
                    maximum_folded_bytes=maximum, temporary_folded_bytes=temporary),
                lambda: run.collect({}, None, None, None, None, 0, None, None,
                    maximum_folded_bytes=maximum, temporary_folded_bytes=temporary),
            )
            for action in actions:
                with self.subTest(maximum=maximum, temporary=temporary), \
                        self.assertRaisesRegex(ValueError, "unsupported-folded-scratch-bound"):
                    action()

    def test_scratch_requires_the_original_finite_retained_budget(self):
        for remaining in (None, True, False, -1, RETAINED + 1, 2 * RETAINED, 1.0, "1"):
            for action in (
                lambda: files.compress_folded(None, None, maximum_bytes=SCRATCH,
                    temporary_folded_bytes=SCRATCH, remaining=remaining),
                lambda: run.profile_reports(None, None, None, None, 0, remaining,
                    maximum_folded_bytes=SCRATCH, temporary_folded_bytes=SCRATCH),
            ):
                with self.subTest(remaining=remaining), \
                        self.assertRaisesRegex(ValueError, "folded-scratch-retained-budget-bound"):
                    action()
        with self.assertRaisesRegex(ValueError, "folded-scratch-retained-budget-bound"):
            run.collect({}, None, None, None, None, 0, None, None,
                maximum_folded_bytes=SCRATCH, temporary_folded_bytes=SCRATCH,
                maximum_total_bytes=2 * RETAINED)
        self.assertEqual(files.MAX_TOTAL_BYTES, RETAINED)
        self.assertEqual(files.MAX_FILE_BYTES, 256 * MIB)
        self.assertEqual(helpers.DirectoryLimits().maximum_file_bytes, 256 * MIB)
        self.assertEqual(common.MAX_FOLDED_BYTES, 64 * MIB)

    def test_only_the_exact_source_is_excluded_and_known_gzip_bytes_still_count(self):
        self.source.write_bytes(self.payload)
        self.destination.write_bytes(b"gzip")
        sibling = self.profile / "other.folded"
        sibling.write_bytes(b"other")
        limits = helpers.DirectoryLimits(maximum_file_bytes=SCRATCH)
        self.assertEqual(helpers.directory_bytes(self.profile, limits), len(self.payload) + 9)
        self.assertEqual(helpers.directory_bytes(self.profile, limits, temporary_file=self.source), 9)
        with self.stale_gzip_stat():
            self.assertEqual(helpers.directory_bytes(self.profile, limits, temporary_file=self.source,
                minimum_file_sizes={self.destination: 4}), 9)
        self.assertEqual(helpers.directory_bytes(self.profile, limits,
            temporary_file=self.profile / "not-created-yet"), len(self.payload) + 9)

    def test_scratch_cap_does_not_raise_any_other_file_cap_or_remove_file_counts(self):
        lengths = {self.source: SCRATCH, self.destination: 256 * MIB}

        @contextmanager
        def scanning(_directory):
            yield [SimpleNamespace(path=str(path), stat=lambda size=size, **_options:
                SimpleNamespace(st_mode=stat.S_IFREG, st_size=size)) for path, size in lengths.items()]

        limits = helpers.DirectoryLimits(maximum_file_bytes=SCRATCH)
        with patch.object(helpers.os, "scandir", side_effect=scanning):
            self.assertEqual(helpers.directory_bytes(self.profile, limits,
                temporary_file=self.source), 256 * MIB)
            lengths[self.destination] += 1
            with self.assertRaisesRegex(ValueError, "helper-artifact-byte-bound"):
                helpers.directory_bytes(self.profile, limits, temporary_file=self.source)
            lengths[self.destination] -= 1
            lengths[self.source] += 1
            with self.assertRaisesRegex(ValueError, "helper-artifact-byte-bound"):
                helpers.directory_bytes(self.profile, limits, temporary_file=self.source)
        self.source.write_bytes(self.payload)
        for index in range(15):
            (self.profile / str(index)).touch()
        with self.assertRaisesRegex(ValueError, "helper-artifact-count-or-type"):
            files.compress_folded(self.source, self.root, maximum_bytes=SCRATCH,
                temporary_folded_bytes=SCRATCH, remaining=4096)
        self.assertEqual(self.source.read_bytes(), self.payload)

    def test_temporary_path_must_be_a_direct_regular_child(self):
        for path in (str(self.source), self.root / "outside", self.profile / "nested" / "child"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "helper-temporary-file-path"):
                helpers.directory_bytes(self.profile, temporary_file=path)
            with self.subTest(command_path=path), self.assertRaisesRegex(ValueError, "helper-temporary-file-path"):
                helpers.command([], self.profile / "unused", 1, self.root, 1,
                    watched=self.profile, temporary_file=path)
        self.source.mkdir()
        with self.assertRaisesRegex(ValueError, "helper-temporary-file-type"):
            helpers.directory_bytes(self.profile, temporary_file=self.source)
        self.source.rmdir()

        @contextmanager
        def link(_directory):
            yield [SimpleNamespace(path=str(self.source), stat=lambda **_options:
                SimpleNamespace(st_mode=stat.S_IFLNK, st_size=0))]

        with patch.object(helpers.os, "scandir", side_effect=link), \
                self.assertRaisesRegex(ValueError, "helper-artifact-count-or-type"):
            helpers.directory_bytes(self.profile, temporary_file=self.source)

    def test_lossless_compression_fits_retained_budget_only_with_explicit_scratch(self):
        self.source.write_bytes(self.payload)
        expected = self.expected_gzip()
        (self.profile / "report.log").write_bytes(b"report")
        remaining = len(expected) + 6
        self.assertLess(remaining, len(self.payload))
        with self.assertRaisesRegex(ValueError, "folded-compression-total-bound"):
            files.compress_folded(self.source, self.root, maximum_bytes=SCRATCH, remaining=remaining)
        self.assertFalse(self.destination.exists())
        with patch.object(files.time, "monotonic_ns", return_value=10):
            ref = files.compress_folded(self.source, self.root, maximum_bytes=SCRATCH,
                temporary_folded_bytes=SCRATCH, remaining=remaining, deadline=11)
        self.assertEqual(self.destination.read_bytes(), expected)
        self.assertEqual(gzip.decompress(expected), self.payload)
        self.assertEqual(ref, files.reference(self.destination, self.root))
        self.assertFalse(self.source.exists())
        self.assertEqual(helpers.directory_bytes(self.profile), remaining)

    def test_one_byte_short_retained_budget_rejects_even_with_stale_gzip_stat(self):
        self.source.write_bytes(self.payload)
        remaining = len(self.expected_gzip()) - 1
        with self.stale_gzip_stat(), self.assertRaisesRegex(ValueError, "folded-compression-total-bound"):
            files.compress_folded(self.source, self.root, maximum_bytes=SCRATCH,
                temporary_folded_bytes=SCRATCH, remaining=remaining)
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.assertGreater(self.destination.stat().st_size, 0)
        self.assertLessEqual(self.destination.stat().st_size, remaining)

    def test_scratch_does_not_renew_deadline_after_source_hash(self):
        self.source.write_bytes(self.payload)
        now = [10]
        original = files.fingerprint

        def fingerprint(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 11
            return result

        with patch.object(files.time, "monotonic_ns", side_effect=lambda: now[0]), \
                patch.object(files, "fingerprint", side_effect=fingerprint), \
                self.assertRaisesRegex(TimeoutError, "folded-compression-deadline"):
            files.compress_folded(self.source, self.root, maximum_bytes=SCRATCH,
                temporary_folded_bytes=SCRATCH, deadline=11, remaining=4096)
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.assertFalse(self.destination.exists())

    def fake_command(self, argv, log, *_args, **_options):
        log.write_bytes(b"synthetic helper output")
        if "--print-flamegraph" in argv:
            Path(argv[-1]).write_bytes(self.payload)

    def test_export_and_compression_share_cutoff_and_only_active_source_has_scratch(self):
        (self.profile / "heaptrack.zst").write_bytes(b"synthetic raw")
        now, deadline, remaining = 1_000_000_000, 241_000_000_000, 4096
        cutoff = now + 120 * 1_000_000_000
        with patch.object(run.time, "monotonic_ns", return_value=now), \
                patch.object(run, "command", side_effect=self.fake_command) as commands, \
                patch.object(run, "compress_folded", wraps=files.compress_folded) as compress, \
                patch.object(run, "directory_bytes", wraps=helpers.directory_bytes) as ordinary:
            refs = run.profile_reports(self.profile / "heaptrack", "printer", "zstd", self.root,
                deadline, remaining, maximum_folded_bytes=SCRATCH, temporary_folded_bytes=SCRATCH)
        self.assertEqual(len(commands.call_args_list), 4)
        for call in commands.call_args_list[:2]:
            self.assertEqual(call.args[4], deadline)
            self.assertNotIn("temporary_file", call.kwargs)
            self.assertNotIn("directory_limits", call.kwargs)
        for call, kind in zip(commands.call_args_list[2:], ("allocations", "peak")):
            self.assertEqual(call.args[4], cutoff)
            self.assertEqual(call.kwargs["temporary_file"], self.profile / (kind + ".folded"))
            self.assertEqual(call.kwargs["directory_limits"].maximum_file_bytes, SCRATCH)
        self.assertTrue(all(call.kwargs["remaining"] == remaining for call in commands.call_args_list))
        self.assertEqual([call.kwargs for call in compress.call_args_list],
            [dict(maximum_bytes=SCRATCH, temporary_folded_bytes=SCRATCH,
                  deadline=cutoff, remaining=remaining)] * 2)
        self.assertEqual(len(ordinary.call_args_list), 2)
        self.assertTrue(all(call.args == (self.profile,) and not call.kwargs
                            for call in ordinary.call_args_list))
        for kind in ("allocations", "peak"):
            self.assertEqual(gzip.decompress((self.root / refs[kind]["path"]).read_bytes()), self.payload)
            self.assertFalse((self.profile / (kind + ".folded")).exists())

    def test_ordinary_post_unlink_check_stops_before_next_export(self):
        (self.profile / "heaptrack.zst").write_bytes(b"synthetic raw")
        with patch.object(run.time, "monotonic_ns", return_value=10), \
                patch.object(run, "command", side_effect=self.fake_command) as commands, \
                patch.object(run, "directory_bytes", return_value=4097), \
                self.assertRaisesRegex(ValueError, "folded-retained-total-bound"):
            run.profile_reports(self.profile / "heaptrack", "printer", "zstd", self.root,
                11, 4096, maximum_folded_bytes=SCRATCH, temporary_folded_bytes=SCRATCH)
        self.assertEqual(len(commands.call_args_list), 3)
        self.assertFalse(self.source.exists())
        self.assertEqual(gzip.decompress(self.destination.read_bytes()), self.payload)
        self.assertFalse((self.profile / "peak.folded").exists())

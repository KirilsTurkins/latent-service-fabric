"""Small interpreted traces exercise independent allocation-event replay."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import heaptrack


HEADER = b"v 10400 3\nX /usr/bin/example --bounded\nI 1000 10000\n"
TABLES = b"s 1 m\ns 1 f\ns 1 p\ni 100 1 2 3 2a\nt 1 0\na 10 1\na 20 1\n"
FOOTER = b"c 2\nR 10\n\n# strings: 3\n# ips: 1\n"


def recording(events=b"+ 0\n+ 0\n- 0\n+ 1\n- 0\n"):
    return HEADER + TABLES + b"c 0\n" + events + FOOTER


class HeaptrackReplayTests(unittest.TestCase):
    def replay(self, contents):
        with tempfile.TemporaryDirectory(prefix="latent-heaptrack-test-") as directory:
            path = Path(directory) / "interpreted.txt"
            path.write_bytes(contents)
            return heaptrack.replay(path)

    def rejects(self, contents, reason):
        with self.assertRaisesRegex(ValueError, "heaptrack-" + reason):
            self.replay(contents)

    def test_shared_allocation_info_counts_live_multiplicity(self):
        self.assertEqual(self.replay(recording()), {
            "heaptrack_version": "1.4.0", "format_version": "3",
            "command": "/usr/bin/example --bounded", "allocation_count": "3",
            "deallocation_count": "2", "allocated_bytes": "64",
            "peak_live_bytes": "48", "remaining_live_bytes": "32",
            "remaining_allocations": "1",
        })

    def test_peak_is_global_live_bytes_not_sum_of_separate_peaks(self):
        result = self.replay(recording(b"+ 0\n- 0\n+ 1\n- 1\n"))
        self.assertEqual(result["allocated_bytes"], "48")
        self.assertEqual(result["peak_live_bytes"], "32")
        self.assertEqual(result["remaining_live_bytes"], "0")
        self.assertEqual(result["remaining_allocations"], "0")

    def test_zero_size_allocations_still_require_matching_frees(self):
        contents = recording(b"a 0 0\n+ 2\n+ 2\n- 2\n")
        result = self.replay(contents)
        self.assertEqual(result["allocation_count"], "2")
        self.assertEqual(result["remaining_allocations"], "1")
        self.assertEqual(result["peak_live_bytes"], "0")
        self.rejects(contents.replace(b"- 2\n", b"- 2\n- 2\n- 2\n"),
                     "free-without-live-allocation")

    def test_missing_free_reference_or_live_owner_is_rejected(self):
        for event, reason in ((b"+ 2\n", "invalid-allocation-reference"),
                              (b"- 2\n", "invalid-allocation-reference"),
                              (b"- 0\n", "free-without-live-allocation"),
                              (b"+ 0\n- 0\n- 0\n", "free-without-live-allocation")):
            with self.subTest(event=event):
                self.rejects(recording(event), reason)

    def test_unsigned_64_bit_counter_overflow_is_rejected(self):
        contents = recording(b"a ffffffffffffffff 0\n+ 2\n")
        self.assertEqual(self.replay(contents)["peak_live_bytes"], str(2**64 - 1))
        self.rejects(contents.replace(b"+ 2\n", b"+ 2\n+ 0\n"), "counter-overflow")
        self.rejects(contents.replace(b"+ 2\n", b"+ 2\n- 2\n+ 2\n"), "counter-overflow")

    def test_all_reference_tables_are_checked(self):
        for original, changed, reason in (
            (b"i 100 1", b"i 100 4", "invalid-ip-reference"),
            (b"2 3 2a", b"4 3 2a", "invalid-frame-reference"),
            (b"t 1 0", b"t 2 0", "invalid-trace-reference"),
            (b"t 1 0", b"t 1 1", "invalid-trace-reference"),
            (b"a 10 1", b"a 10 2", "invalid-allocation-trace"),
        ):
            with self.subTest(changed=changed):
                self.rejects(recording().replace(original, changed), reason)

    def test_supported_instruction_variants_and_raw_string_byte_lengths(self):
        for instruction in (b"i 100 0", b"i 100 1 2", b"i 100 1 2 3 2a 2 3 1"):
            with self.subTest(instruction=instruction):
                self.assertEqual(self.replay(recording().replace(b"i 100 1 2 3 2a", instruction))
                                 ["allocation_count"], "3")
        self.assertEqual(self.replay(recording().replace(b"s 1 m", b"s 2 \xc3\xa9"))
                         ["allocation_count"], "3")
        self.rejects(recording().replace(b"s 1 m", b"s 1 \xc3\xa9"), "invalid-sized-string")

    def test_record_numbers_and_shapes_are_strict(self):
        for event in (b"+ 00\n", b"+ -1\n", b"+ A\n", b"+ 10000000000000000\n",
                      b"+  0\n", b"+ 0 \n", b"+ 0 1\n", b"a 10\n", b"i 100 1 2 3\n"):
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    self.replay(recording(event))

    def test_headers_reject_unknown_version_missing_fields_and_attachment(self):
        for original, replacement, reason in (
            (b"v 10400 3", b"v 10500 3", "unsupported-version"),
            (b"v 10400 3", b"v 10400 2", "unsupported-version"),
            (b"v 10400 3\n", b"", "duplicate-or-missing-command"),
            (b"X /usr/bin/example --bounded\n", b"", "missing-header"),
            (b"I 1000 10000\n", b"", "missing-header"),
            (b"I 1000 10000", b"I 1001 10000", "invalid-system"),
        ):
            with self.subTest(replacement=replacement):
                self.rejects(recording().replace(original, replacement), reason)
        self.rejects(recording(b"A 1\n"), "unsupported-record")
        self.rejects(recording(b"v 10400 3\n"), "late-header")
        self.rejects(recording().replace(HEADER, HEADER + b"X duplicate\n"),
                     "duplicate-or-missing-command")

    def test_timestamps_are_monotonic_and_required(self):
        self.rejects(recording(b"c 10\n"), "backwards-timestamp")
        self.rejects(recording().replace(b"c 0\n", b"R 0\n"), "rss-without-timestamp")
        empty = HEADER + b"# strings: 0\n# ips: 0\n"
        self.rejects(empty, "incomplete-recording")
        self.assertEqual(self.replay(HEADER + b"c 0\n# strings: 0\n# ips: 0\n")
                         ["allocation_count"], "0")

    def test_complete_footer_is_required_and_consistent(self):
        for contents, reason in (
            (recording().split(b"# strings:")[0], "missing-completion-footer"),
            (recording().split(b"# ips:")[0], "missing-completion-footer"),
            (recording().replace(b"# strings: 3", b"# strings: 4"), "footer-count-mismatch"),
            (recording().replace(b"# strings: 3", b"# strings: 03"), "invalid-footer-count"),
            (recording().replace(b"# strings: 3\n# ips: 1", b"# ips: 1\n# strings: 3"),
             "invalid-footer-order"),
            (recording() + b"+ 0\n", "data-after-footer"),
            (recording() + b"# ips: 1\n", "invalid-footer-order"),
            (recording()[:-1], "line-bound-or-truncated"),
        ):
            with self.subTest(reason=reason):
                self.rejects(contents, reason)

    def test_raw_remaining_totals_ignore_declared_leak_suppression(self):
        plain = self.replay(recording())
        suppressed = self.replay(recording(b"S leak:example\n+ 0\n+ 0\n- 0\n+ 1\n- 0\n"))
        self.assertEqual(plain, suppressed)
        self.rejects(recording(b"S unknown:example\n"), "invalid-suppression")

    def test_bytes_lines_records_and_tables_have_independent_bounds(self):
        for name, value, contents, reason in (
            ("MAX_BYTES", len(recording()) - 1, recording(), "byte-bound"),
            ("MAX_LINE_BYTES", 16, recording(), "line-bound-or-truncated"),
            ("MAX_TABLE_ENTRIES", 2, recording(), "table-bound"),
            ("MAX_TABLE_ENTRIES", 3, recording(b"a 0 0\na 0 0\n"), "table-bound"),
        ):
            with self.subTest(name=name):
                with patch.object(heaptrack, name, value):
                    self.rejects(contents, reason)
        with patch.object(heaptrack, "record_limit", return_value=4):
            self.rejects(recording(), "record-bound")

    def test_invalid_record_bytes_and_non_regular_inputs_are_rejected(self):
        self.rejects(recording().replace(b" m\n", b" \0\n"), "invalid-record-byte")
        self.rejects(recording().replace(b"\n", b"\r\n"), "invalid-record-byte")
        self.rejects(recording().replace(b"/usr/bin/example", b"\xff"), "invalid-command")
        with tempfile.TemporaryDirectory(prefix="latent-heaptrack-directory-") as directory:
            with self.assertRaisesRegex(ValueError, "heaptrack-not-regular-file"):
                heaptrack.replay(Path(directory))


if __name__ == "__main__":
    unittest.main()

"""Lossless stack-profile retention and bounded offline decompression."""
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_evidence import common
from tools.artifact_identity_runner.files import compress_folded, fingerprint


class ProfileCompressionTests(unittest.TestCase):
    def test_large_valid_profile_preserves_every_row_and_exact_weight(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "allocations.folded"
            # Rust generic names produced >16 MiB profiles in the real smoke.
            row = b"stack;" + b"generic" * 300 + b" 7\n"
            with original.open("wb") as stream:
                for _ in range(9000):
                    stream.write(row)
            expected = fingerprint(original)
            ref = compress_folded(original, root)
            self.assertFalse(original.exists())
            self.assertEqual(common.folded(root / ref["path"]), {"rows": "9000", "total": "63000"})
            self.assertEqual(ref["sha256"], fingerprint(root / ref["path"])[0])
            self.assertEqual(expected[1], len(row) * 9000)

    def test_compressed_byte_bomb_and_truncated_trailer_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "peak.folded.gz"
            data = gzip.compress(b"stack 1\n" * 1000, mtime=0)
            path.write_bytes(data)
            with patch.object(common, "folded_limit", return_value=128):
                with self.assertRaisesRegex(ValueError, "profile-text-bound"):
                    common.folded(path)
            path.write_bytes(data[:-4])
            with self.assertRaises(EOFError):
                common.folded(path)

    def test_compression_is_deterministic_and_cannot_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "one.folded", root / "two.folded"
            first.write_bytes(b"caller;allocator 123\n")
            second.write_bytes(first.read_bytes())
            a, b = compress_folded(first, root), compress_folded(second, root)
            self.assertEqual(a["sha256"], b["sha256"])
            first.write_bytes(b"replacement 1\n")
            with self.assertRaises(FileExistsError):
                compress_folded(first, root)
            self.assertEqual((root / a["path"]).read_bytes(), (root / b["path"]).read_bytes())

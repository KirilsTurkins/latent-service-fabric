"""Pinned compiler downloads tolerate slow progress without accepting bad bytes."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_dev_guest_tools as builder
from tools.dev_workflow.common import DevError


class DownloadTests(unittest.TestCase):
    def source(self, payload: bytes, maximum: int | None = None) -> dict:
        return {"url": "https://compiler.invalid/pinned-archive",
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "maximum": len(payload) if maximum is None else maximum}

    def test_slow_progress_over_ninety_seconds_retains_exact_pinned_bytes(self):
        clock, requests = [0.0], []
        payload = b"a" * (2 * builder.DOWNLOAD_CHUNK_BYTES + 17)

        class SlowResponse(io.BytesIO):
            def read1(self, maximum):
                requests.append(maximum)
                clock[0] += 31.0
                return super().read1(maximum)

            def read(self, *_args):
                raise AssertionError("download must not fill a buffer across slow reads")

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "compiler.archive"
            with patch.object(builder.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(builder.urllib.request, "urlopen", return_value=SlowResponse(payload)) as opened:
                builder.download(target, self.source(payload))
            self.assertEqual(target.read_bytes(), payload)
            self.assertGreater(clock[0], 90)
            self.assertLess(clock[0], builder.DOWNLOAD_TIMEOUT_SECONDS)
            self.assertEqual(builder.DOWNLOAD_TIMEOUT_SECONDS, 600)
            self.assertEqual(requests, [65536, 65536, 18, 1])
            opened.assert_called_once_with(self.source(payload)["url"], timeout=30)

    def test_over_byte_ceiling_is_rejected_and_partial_file_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "compiler.archive"
            with patch.object(builder.urllib.request, "urlopen", return_value=io.BytesIO(b"excess")), \
                    self.assertRaisesRegex(DevError, "compiler-download-byte-limit"):
                builder.download(target, self.source(b"excess", maximum=3))
            self.assertFalse(target.exists())

    def test_wrong_digest_and_truncated_archive_are_not_retained(self):
        for payload in (b"wrong", b"", b"pin"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "compiler.archive"
                with patch.object(builder.urllib.request, "urlopen", return_value=io.BytesIO(payload)), \
                        self.assertRaisesRegex(DevError, "compiler-upstream-archive-digest"):
                    builder.download(target, self.source(b"pinned"))
                self.assertFalse(target.exists())

    def test_deadline_is_checked_before_read_after_read_and_after_eof(self):
        clock = [0.0]
        for stage in ("open", "body", "eof"):
            class ExpiringResponse(io.BytesIO):
                def read1(self, maximum):
                    data = super().read1(maximum)
                    if stage == "body" or (stage == "eof" and not data):
                        clock[0] = builder.DOWNLOAD_TIMEOUT_SECONDS
                    return data

            response = ExpiringResponse(b"pinned")

            def open_response(*_args, **_kwargs):
                if stage == "open":
                    clock[0] = builder.DOWNLOAD_TIMEOUT_SECONDS
                return response

            clock[0] = 0.0
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "compiler.archive"
                with patch.object(builder.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(builder.urllib.request, "urlopen", side_effect=open_response), \
                        self.assertRaisesRegex(DevError, "compiler-download-deadline"):
                    builder.download(target, self.source(b"pinned"))
                self.assertFalse(target.exists())
                self.assertTrue(response.closed)

    def test_digest_verification_does_not_extend_acceptance_deadline(self):
        clock = [0.0]
        source = self.source(b"pinned")

        def slow_digest(_path):
            clock[0] = builder.DOWNLOAD_TIMEOUT_SECONDS
            return source["sha256"], 6

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "compiler.archive"
            with patch.object(builder.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(builder.urllib.request, "urlopen", return_value=io.BytesIO(b"pinned")), \
                    patch.object(builder, "file_digest", side_effect=slow_digest), \
                    self.assertRaisesRegex(DevError, "compiler-download-deadline"):
                builder.download(target, source)
            self.assertFalse(target.exists())

    def test_transport_failure_never_retries_or_leaves_partial_bytes(self):
        for stage in ("open", "body"):
            class BrokenResponse(io.BytesIO):
                def read1(self, maximum):
                    if self.tell():
                        raise TimeoutError("synthetic transport failure")
                    return super().read1(1)

            response = BrokenResponse(b"pinned")
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "compiler.archive"
                with patch.object(builder.urllib.request, "urlopen", return_value=response,
                                  side_effect=TimeoutError("synthetic") if stage == "open" else None) as opened, \
                        self.assertRaises(TimeoutError):
                    builder.download(target, self.source(b"pinned"))
                opened.assert_called_once()
                self.assertFalse(target.exists())

    def test_existing_file_is_preserved_without_opening_the_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "compiler.archive"
            target.write_bytes(b"already owned")
            with patch.object(builder.urllib.request, "urlopen") as opened, self.assertRaises(FileExistsError):
                builder.download(target, self.source(b"pinned"))
            opened.assert_not_called()
            self.assertEqual(target.read_bytes(), b"already owned")

    def test_cancellation_removes_only_the_file_created_by_this_download(self):
        class CancelledResponse(io.BytesIO):
            def read1(self, maximum):
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "compiler.archive"
            with patch.object(builder.urllib.request, "urlopen", return_value=CancelledResponse()), \
                    self.assertRaises(KeyboardInterrupt):
                builder.download(target, self.source(b"pinned"))
            self.assertFalse(target.exists())


class CacheTests(unittest.TestCase):
    def source(self, payload):
        return {"url": "https://compiler.invalid/pinned-archive",
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(), "maximum": len(payload)}

    def test_cold_download_and_warm_cache_preserve_exact_bytes_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(b"pinned compiler bytes")
            with patch.object(builder.urllib.request, "urlopen", return_value=io.BytesIO(b"pinned compiler bytes")) as opened:
                builder.download(root / "cold.archive", source, cache=root / "cache")
            opened.assert_called_once_with(source["url"], timeout=30)
            with patch.object(builder.urllib.request, "urlopen") as opened:
                builder.download(root / "warm.archive", source, cache=root / "cache")
            opened.assert_not_called()
            self.assertEqual((root / "cold.archive").read_bytes(), (root / "warm.archive").read_bytes())

    def test_restored_wrong_or_oversized_bytes_fail_closed_without_retry(self):
        for payload, code in ((b"wrong!", "compiler-upstream-archive-digest"),
                              (b"far too many bytes", "compiler-download-byte-limit")):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                cache = root / "cache"
                cache.mkdir()
                source = self.source(b"pinned")
                entry = cache / (source["sha256"][7:] + ".archive")
                entry.write_bytes(payload)
                with patch.object(builder.urllib.request, "urlopen") as opened, self.assertRaisesRegex(DevError, code):
                    builder.download(root / "candidate.archive", source, cache=cache)
                opened.assert_not_called()
                self.assertFalse((root / "candidate.archive").exists())
                self.assertEqual(entry.read_bytes(), payload)

    def test_failed_upstream_bytes_are_never_published_to_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(builder.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong!")), \
                    self.assertRaisesRegex(DevError, "compiler-upstream-archive-digest"):
                builder.download(root / "candidate.archive", self.source(b"pinned"), cache=root / "cache")
            self.assertFalse((root / "candidate.archive").exists())
            self.assertEqual(list((root / "cache").iterdir()), [])

    def test_cache_verification_cannot_extend_original_deadline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cache.mkdir()
            source = self.source(b"pinned")
            (cache / (source["sha256"][7:] + ".archive")).write_bytes(b"pinned")
            clock = [0.0]
            def digest(_path):
                clock[0] = builder.DOWNLOAD_TIMEOUT_SECONDS
                return source["sha256"], 6
            with patch.object(builder.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(builder, "file_digest", side_effect=digest), \
                    patch.object(builder.urllib.request, "urlopen") as opened, \
                    self.assertRaisesRegex(DevError, "compiler-download-deadline"):
                builder.download(root / "candidate.archive", source, cache=cache)
            opened.assert_not_called()
            self.assertFalse((root / "candidate.archive").exists())


if __name__ == "__main__":
    unittest.main()

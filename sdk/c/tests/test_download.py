from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import urllib.error
import urllib.request


SDK = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("c_sdk_build", SDK / "tools/build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class Response:
    def __init__(self, payload, url=None, status=200):
        self.payload = payload
        self.url = url or "https://release-assets.githubusercontent.com/pinned"
        self.status = status
        self.requested = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def geturl(self):
        return self.url

    def read(self, amount):
        self.requested = amount
        return self.payload[:amount]


class CDependencyDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.payload = b"controlled original release asset"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.enterContext(patch.object(BUILD, "NGHTTP2_SHA256", self.digest))
        self.enterContext(patch.object(BUILD, "NGHTTP2_ASSET_BYTES", len(self.payload)))
        self.item = {"url": BUILD.NGHTTP2_URL, "sha256": self.digest}

    def failure(self, code=504):
        return urllib.error.HTTPError(BUILD.NGHTTP2_URL, code, "error", {}, None)

    def test_lock_and_public_asset_are_fixed_to_the_reviewed_release(self):
        lock = json.loads((SDK / "dependencies.lock.json").read_bytes())["nghttp2"]
        self.assertEqual(lock["url"], BUILD.NGHTTP2_URL)
        self.assertEqual(lock["sha256"], "aa317e2cf9dca6afa0aed68f8fad6ff303ec6982e25a78c75c0b65e2b9b3ded5")
        self.assertEqual(BUILD.NGHTTP2_ASSET, "https://api.github.com/repos/nghttp2/nghttp2/releases/assets/494019933")

    def test_success_and_cache_keep_the_original_hash_gate(self):
        response = Response(self.payload)
        with patch.object(BUILD.urllib.request, "urlopen", return_value=response) as first, \
                patch.object(BUILD.urllib.request, "build_opener") as fallback:
            path = BUILD.download(self.directory, "nghttp2.download", self.item)
            self.assertEqual(path.read_bytes(), self.payload)
            self.assertEqual(response.requested, BUILD.MAX_DOWNLOAD_BYTES + 1)
            self.assertEqual(first.call_args.kwargs["timeout"], 30)
            fallback.assert_not_called()
            first.reset_mock()
            self.assertEqual(BUILD.download(self.directory, "nghttp2.download", self.item), path)
            first.assert_not_called()
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "cached dependency integrity failure"):
                BUILD.download(self.directory, "nghttp2.download", self.item)
            first.assert_not_called()

    def test_504_uses_only_anonymous_exact_asset_and_original_digest(self):
        response = Response(self.payload)
        opener = SimpleNamespace(open=unittest.mock.Mock(return_value=response))
        with patch.dict(os.environ, {"GH_TOKEN": "sentinel-not-for-build"}), \
                patch.object(BUILD.urllib.request, "urlopen", side_effect=self.failure()), \
                patch.object(BUILD.urllib.request, "build_opener", return_value=opener):
            path = BUILD.download(self.directory, "nghttp2.download", self.item)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, BUILD.NGHTTP2_ASSET)
        self.assertEqual(request.get_header("Accept"), "application/octet-stream")
        self.assertFalse(any(key.lower() == "authorization" for key, _ in request.header_items()))
        self.assertNotIn("sentinel-not-for-build", repr(request.header_items()))
        self.assertGreater(opener.open.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(opener.open.call_args.kwargs["timeout"], 30)
        self.assertEqual(path.read_bytes(), self.payload)

    def test_wrong_direct_download_is_not_retried_or_cached(self):
        with patch.object(BUILD.urllib.request, "urlopen", return_value=Response(b"changed")), \
                patch.object(BUILD.urllib.request, "build_opener") as fallback:
            with self.assertRaisesRegex(RuntimeError, "dependency integrity failure"):
                BUILD.download(self.directory, "nghttp2.download", self.item)
            fallback.assert_not_called()
        self.assertFalse((self.directory / "nghttp2.download").exists())

    def test_other_errors_and_nonmatching_locks_never_use_the_fallback(self):
        for failure in (self.failure(403), self.failure(404), self.failure(502),
                        urllib.error.URLError("dns failure")):
            with self.subTest(failure=type(failure).__name__, reason=str(failure)), \
                    patch.object(BUILD.urllib.request, "urlopen", side_effect=failure), \
                    patch.object(BUILD.urllib.request, "build_opener") as fallback:
                with self.assertRaises(type(failure)):
                    BUILD.download(self.directory, "nghttp2.download", self.item)
                fallback.assert_not_called()
        for name, item in (("protoc.download", self.item),
                           ("nghttp2.download", dict(self.item, url="https://example.com/asset")),
                           ("nghttp2.download", dict(self.item, sha256="0" * 64))):
            with self.subTest(name=name, item=item), \
                    patch.object(BUILD.urllib.request, "urlopen", side_effect=self.failure()), \
                    patch.object(BUILD.urllib.request, "build_opener") as fallback:
                with self.assertRaises(urllib.error.HTTPError):
                    BUILD.download(self.directory, name, item)
                fallback.assert_not_called()

    def test_timeout_passes_only_remaining_timeout_to_fallback_request(self):
        opener = SimpleNamespace(open=unittest.mock.Mock(return_value=Response(self.payload)))
        with patch.object(BUILD.urllib.request, "urlopen", side_effect=urllib.error.URLError(TimeoutError())), \
                patch.object(BUILD.urllib.request, "build_opener", return_value=opener), \
                patch.object(BUILD.time, "monotonic", side_effect=(100.0, 119.0)):
            BUILD.download(self.directory, "nghttp2.download", self.item)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 11.0)
        (self.directory / "nghttp2.download").unlink()
        with patch.object(BUILD.urllib.request, "urlopen", side_effect=TimeoutError()), \
                patch.object(BUILD.urllib.request, "build_opener") as fallback, \
                patch.object(BUILD.time, "monotonic", side_effect=(100.0, 130.0)):
            with self.assertRaises(TimeoutError):
                BUILD.download(self.directory, "nghttp2.download", self.item)
            fallback.assert_not_called()

    def test_changed_or_truncated_asset_never_creates_a_cache_entry(self):
        for payload in (b"short", b"x" * len(self.payload)):
            with self.subTest(payload=payload), \
                    patch.object(BUILD.urllib.request, "urlopen", side_effect=self.failure()), \
                    patch.object(BUILD.urllib.request, "build_opener",
                        return_value=SimpleNamespace(open=unittest.mock.Mock(return_value=Response(payload)))):
                with self.assertRaisesRegex(RuntimeError, "dependency integrity failure"):
                    BUILD.download(self.directory, "nghttp2.download", self.item)
                self.assertFalse((self.directory / "nghttp2.download").exists())

    def test_oversized_fallback_is_rejected_by_the_existing_byte_bound(self):
        payload = b"12345"
        with patch.object(BUILD, "MAX_DOWNLOAD_BYTES", 4), \
                patch.object(BUILD, "NGHTTP2_ASSET_BYTES", 5), \
                patch.object(BUILD, "NGHTTP2_SHA256", hashlib.sha256(payload).hexdigest()), \
                patch.object(BUILD.urllib.request, "urlopen", side_effect=self.failure()), \
                patch.object(BUILD.urllib.request, "build_opener",
                    return_value=SimpleNamespace(open=unittest.mock.Mock(return_value=Response(payload)))):
            with self.assertRaisesRegex(RuntimeError, "dependency integrity failure"):
                BUILD.download(self.directory, "nghttp2.download", dict(self.item, sha256=BUILD.NGHTTP2_SHA256))
        self.assertFalse((self.directory / "nghttp2.download").exists())

    def test_redirect_and_final_response_are_restricted(self):
        handler = BUILD._AssetRedirect()
        request = urllib.request.Request(BUILD.NGHTTP2_ASSET, headers={"Accept": "application/octet-stream"})
        allowed = handler.redirect_request(request, None, 302, "found", {},
            "https://release-assets.githubusercontent.com/exact")
        self.assertEqual(allowed.full_url, "https://release-assets.githubusercontent.com/exact")
        for url in ("http://release-assets.githubusercontent.com/a", "https://example.com/a",
                    "https://release-assets.githubusercontent.com.evil/a",
                    "https://user@release-assets.githubusercontent.com/a",
                    "https://release-assets.githubusercontent.com:444/a"):
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "unapproved dependency asset redirect"):
                handler.redirect_request(request, None, 302, "found", {}, url)
        response = Response(self.payload, url="https://example.com/asset")
        with patch.object(BUILD.urllib.request, "urlopen", side_effect=self.failure()), \
                patch.object(BUILD.urllib.request, "build_opener",
                    return_value=SimpleNamespace(open=unittest.mock.Mock(return_value=response))):
            with self.assertRaisesRegex(RuntimeError, "unapproved dependency asset response"):
                BUILD.download(self.directory, "nghttp2.download", self.item)
        self.assertFalse((self.directory / "nghttp2.download").exists())


if __name__ == "__main__":
    unittest.main()

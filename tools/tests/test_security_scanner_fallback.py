"""Causal controls for the fixed, fail-closed scanner asset fallback."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import os
import sys
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

import yaml

from tools import security_install as installer
from tools.security_common import ROOT, SecurityError, child_environment, run


class Response:
    def __init__(self, chunks, url="https://release-assets.githubusercontent.com/asset"):
        self.chunks = list(chunks)
        self.url = url
        self.status = 200
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def read1(self, _):
        if not self.chunks:
            return b""
        result = self.chunks.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ScannerFallbackTests(unittest.TestCase):
    token = "synthetic" + "-credential"

    def test_exact_cargo_audit_504_uses_pinned_api_and_bad_archive_fails_closed(self):
        failure = urllib.error.HTTPError(installer.CARGO_AUDIT_LINUX_URL, 504, "gateway", {}, io.BytesIO())
        opener = Mock(open=Mock(return_value=Response([b"fake"])))
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer, "platform_key", return_value="linux-x64"), \
             patch.object(installer.urllib.request, "urlopen", side_effect=failure), \
             patch.object(installer.urllib.request, "build_opener", return_value=opener), \
             patch.object(installer, "CARGO_AUDIT_LINUX_ASSET_BYTES", 4):
            with self.assertRaisesRegex(SecurityError, "download-digest-mismatch"):
                installer.install("cargo-audit", Path(temporary))
            self.assertEqual(list(Path(temporary).iterdir()), [])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, installer.CARGO_AUDIT_LINUX_ASSET)
        self.assertEqual(request.unredirected_hdrs.get("Authorization"), "Bearer " + self.token)
        self.assertNotIn("Authorization", request.headers)
        self.assertTrue(failure.fp.closed)

    def test_cargo_audit_wrong_url_missing_token_and_other_http_fail_without_api(self):
        for url, token, code in ((installer.CARGO_AUDIT_LINUX_URL, "", 504),
                                 (installer.CARGO_AUDIT_LINUX_URL, self.token, 404),
                                 (installer.CARGO_AUDIT_LINUX_URL + "-other", self.token, 504)):
            failure = urllib.error.HTTPError(url, code, "gateway", {}, io.BytesIO())
            with self.subTest(url=url, token_present=bool(token), code=code), \
                 patch.dict(os.environ, {"GH_TOKEN": token}), \
                 patch.object(installer.urllib.request, "urlopen", side_effect=failure), \
                 patch.object(installer.urllib.request, "build_opener") as api:
                with self.assertRaises(urllib.error.HTTPError):
                    installer.download(url)
                api.assert_not_called()

    def test_original_success_never_uses_api_or_token(self):
        direct = Response([b"original"], "https://github.com/asset")
        with patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer.urllib.request, "urlopen", return_value=direct), \
             patch.object(installer.urllib.request, "build_opener") as api:
            self.assertEqual(installer.download(installer.ZIZMOR_LINUX_URL), b"original")
        self.assertTrue(direct.closed)
        api.assert_not_called()

    def test_open_timeout_uses_only_fixed_api_with_unredirected_auth(self):
        response = Response([b"safe"])
        opener = Mock(open=Mock(return_value=response))
        with patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer.urllib.request, "urlopen", side_effect=TimeoutError), \
             patch.object(installer.urllib.request, "build_opener", return_value=opener), \
             patch.object(installer, "ZIZMOR_LINUX_ASSET_BYTES", 4):
            self.assertEqual(installer.download(installer.ZIZMOR_LINUX_URL), b"safe")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, installer.ZIZMOR_LINUX_ASSET)
        self.assertEqual(request.unredirected_hdrs.get("Authorization"), "Bearer " + self.token)
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(request.headers.get("Accept"), "application/octet-stream")
        self.assertTrue(response.closed)

    def test_read_timeout_closes_partial_response_and_discards_its_bytes(self):
        direct = Response([b"partial", TimeoutError()], "https://github.com/asset")
        fallback = Response([b"safe"])
        opener = Mock(open=Mock(return_value=fallback))
        with patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer.urllib.request, "urlopen", return_value=direct), \
             patch.object(installer.urllib.request, "build_opener", return_value=opener), \
             patch.object(installer, "ZIZMOR_LINUX_ASSET_BYTES", 4):
            self.assertEqual(installer.download(installer.ZIZMOR_LINUX_URL), b"safe")
        self.assertTrue(direct.closed)
        self.assertTrue(fallback.closed)
        opener.open.assert_called_once()

    def test_gateway_timeout_closes_original_and_wrapped_timeout_also_retries(self):
        for failure in (urllib.error.HTTPError(installer.ZIZMOR_LINUX_URL, 504, "gateway", {}, io.BytesIO()),
                        urllib.error.URLError(TimeoutError())):
            with self.subTest(kind=type(failure).__name__):
                opener = Mock(open=Mock(return_value=Response([b"safe"])))
                with patch.dict(os.environ, {"GH_TOKEN": self.token}), \
                     patch.object(installer.urllib.request, "urlopen", side_effect=failure), \
                     patch.object(installer.urllib.request, "build_opener", return_value=opener), \
                     patch.object(installer, "ZIZMOR_LINUX_ASSET_BYTES", 4):
                    self.assertEqual(installer.download(installer.ZIZMOR_LINUX_URL), b"safe")
                if isinstance(failure, urllib.error.HTTPError):
                    self.assertTrue(failure.fp.closed)
                opener.open.assert_called_once()

    def test_other_errors_other_tools_and_missing_token_fail_without_api(self):
        failures = [urllib.error.HTTPError(installer.ZIZMOR_LINUX_URL, n, "failure", {}, io.BytesIO())
                    for n in (403, 404, 503)]
        failures += [urllib.error.URLError(ConnectionResetError()), SecurityError("fixed-failure")]
        for failure in failures:
            with self.subTest(kind=type(failure).__name__, code=getattr(failure, "code", None)), \
                 patch.dict(os.environ, {"GH_TOKEN": self.token}), \
                 patch.object(installer.urllib.request, "urlopen", side_effect=failure), \
                 patch.object(installer.urllib.request, "build_opener") as api:
                with self.assertRaises(type(failure)):
                    installer.download(installer.ZIZMOR_LINUX_URL)
                api.assert_not_called()
        for url, token in ((installer.ZIZMOR_LINUX_URL, ""),
                           ("https://github.com/gitleaks/gitleaks/releases/download/example/asset", self.token)):
            with self.subTest(url=url, token_present=bool(token)), \
                 patch.dict(os.environ, {"GH_TOKEN": token}), \
                 patch.object(installer.urllib.request, "urlopen", side_effect=TimeoutError), \
                 patch.object(installer.urllib.request, "build_opener") as api:
                with self.assertRaises(TimeoutError):
                    installer.download(url)
                api.assert_not_called()

    def test_fallback_short_oversized_and_fallback_timeout_fail_closed(self):
        for chunks, limit, expected in (([b"bad"], 96, "download-size-mismatch"),
                                        ([b"toolarge"], 4, "download-size-limit")):
            opener = Mock(open=Mock(return_value=Response(chunks)))
            with self.subTest(expected=expected), patch.dict(os.environ, {"GH_TOKEN": self.token}), \
                 patch.object(installer.urllib.request, "urlopen", side_effect=TimeoutError), \
                 patch.object(installer.urllib.request, "build_opener", return_value=opener), \
                 patch.object(installer, "ZIZMOR_LINUX_ASSET_BYTES", 4), \
                 patch.object(installer, "MAX_DOWNLOAD_BYTES", limit):
                with self.assertRaisesRegex(SecurityError, expected):
                    installer.download(installer.ZIZMOR_LINUX_URL)
                opener.open.assert_called_once()
        opener = Mock(open=Mock(side_effect=TimeoutError))
        with patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer.urllib.request, "urlopen", side_effect=TimeoutError), \
             patch.object(installer.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(TimeoutError):
                installer.download(installer.ZIZMOR_LINUX_URL)
        opener.open.assert_called_once()

    def test_shared_time_limit_and_integrity_failure_never_retry(self):
        response = Response([b"late"], "https://github.com/asset")
        with patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer.urllib.request, "urlopen", return_value=response), \
             patch.object(installer.urllib.request, "build_opener") as api, \
             patch.object(installer.time, "monotonic", side_effect=[1, 122]):
            with self.assertRaisesRegex(SecurityError, "download-time-limit"):
                installer.download(installer.ZIZMOR_LINUX_URL)
            api.assert_not_called()
        self.assertTrue(response.closed)
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer, "platform_key", return_value="linux-x64"), \
             patch.object(installer.urllib.request, "urlopen", side_effect=TimeoutError), \
             patch.object(installer.urllib.request, "build_opener", return_value=Mock(open=Mock(return_value=Response([b"fake"])))), \
             patch.object(installer, "ZIZMOR_LINUX_ASSET_BYTES", 4):
            with self.assertRaisesRegex(SecurityError, "download-digest-mismatch"):
                installer.install("zizmor", Path(temporary))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_matching_archive_with_changed_binary_is_refused_before_install(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            content = b"unreviewed executable"
            entry = tarfile.TarInfo("zizmor" + (".exe" if os.name == "nt" else ""))
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
        payload = stream.getvalue()
        policy = copy.deepcopy(installer.tool_lock())
        policy["tools"]["zizmor"]["assets"]["linux-x64"]["sha256"] = hashlib.sha256(payload).hexdigest()
        opener = Mock(open=Mock(return_value=Response([payload])))
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, {"GH_TOKEN": self.token}), \
             patch.object(installer, "platform_key", return_value="linux-x64"), \
             patch.object(installer, "tool_lock", return_value=policy), \
             patch.object(installer.urllib.request, "urlopen", side_effect=TimeoutError), \
             patch.object(installer.urllib.request, "build_opener", return_value=opener), \
             patch.object(installer, "ZIZMOR_LINUX_ASSET_BYTES", len(payload)):
            with self.assertRaisesRegex(SecurityError, "archive-binary-digest-mismatch"):
                installer.install("zizmor", Path(temporary))
            self.assertEqual(list(Path(temporary).iterdir()), [])
        opener.open.assert_called_once()

    def test_redirect_never_receives_credential_and_untrusted_destinations_are_refused(self):
        initial = urllib.request.Request(installer.ZIZMOR_LINUX_ASSET)
        initial.add_unredirected_header("Authorization", "Bearer " + self.token)
        handler = installer._AssetRedirect()
        redirected = handler.redirect_request(initial, None, 302, "found", {},
                                               "https://release-assets.githubusercontent.com/a?sig=example")
        self.assertFalse(any(k.lower() == "authorization" for k, _ in redirected.header_items()))
        injected = urllib.request.Request("https://release-assets.githubusercontent.com/a",
                                          headers={"Authorization": "unexpected"})
        with patch.object(urllib.request.HTTPRedirectHandler, "redirect_request", return_value=injected):
            with self.assertRaisesRegex(SecurityError, "asset-redirect-credential"):
                handler.redirect_request(initial, None, 302, "found", {},
                                         "https://release-assets.githubusercontent.com/a")
        for target in ("http://release-assets.githubusercontent.com/a", "https://example.invalid/a",
                       "https://user@release-assets.githubusercontent.com/a",
                       "https://release-assets.githubusercontent.com:444/a"):
            with self.subTest(target=target), self.assertRaisesRegex(SecurityError, "unreviewed-asset-redirect"):
                handler.redirect_request(initial, None, 302, "found", {}, target)

    def test_environment_and_failure_output_do_not_expose_token(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"GH_TOKEN": self.token}):
            self.assertNotIn("GH_TOKEN", child_environment(Path(temporary)))
            _, output = run([sys.executable, "-c", "import os; print('GH_TOKEN' in os.environ)"],
                            Path(temporary), timeout=5)
            self.assertEqual(output.strip(), b"False")
        captured = io.StringIO()
        with patch.object(installer, "install", side_effect=ValueError(self.token)), \
             patch.object(installer.sys, "argv", ["install", "--tool", "zizmor", "--destination", "."]), \
             contextlib.redirect_stderr(captured):
            self.assertEqual(installer.main(), 1)
        self.assertNotIn(self.token, captured.getvalue())
        self.assertIn("invalid-or-unavailable-tool", captured.getvalue())

    def test_workflow_scope_excludes_pull_requests_and_other_refs(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/security-baseline.yml").read_text(encoding="utf8"))
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        selected = []
        for job, name, tool in (("static", "Install digest-pinned offline workflow scanner", "zizmor"),
                                ("self-test", "Install reviewed zizmor canary scanner", "zizmor"),
                                ("self-test", "Install reviewed cargo-audit canary scanner", "cargo-audit")):
            matches = [s for s in workflow["jobs"][job]["steps"] if s.get("name") == name]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["env"], {"GH_TOKEN": "${{ github.event_name == 'push' && github.ref == 'refs/heads/development' && github.token || '' }}"})
            self.assertIn("--tool " + tool, matches[0]["run"])
            selected.extend(matches)
        canary = next(s for s in workflow["jobs"]["self-test"]["steps"]
                      if s.get("name") == "Install reviewed gitleaks canary scanner")
        self.assertIn("--tool gitleaks", canary["run"])
        self.assertNotIn("env", canary)
        self.assertNotIn("GH_TOKEN", workflow.get("env", {}))
        for definition in workflow["jobs"].values():
            self.assertNotIn("GH_TOKEN", definition.get("env", {}))
            for step in definition.get("steps", []):
                if not any(step is item for item in selected):
                    self.assertNotIn("GH_TOKEN", step.get("env", {}))

        rustsec = yaml.safe_load((ROOT / ".github/workflows/security-rustsec.yml").read_text(encoding="utf8"))
        self.assertEqual(rustsec["permissions"], {"contents": "read"})
        steps = rustsec["jobs"]["audit"]["steps"]
        cargo = next(s for s in steps if s.get("name") == "Install digest-pinned cargo-audit outside the input checkout")
        self.assertEqual(cargo["env"], {"GH_TOKEN": "${{ github.event_name == 'push' && github.ref == 'refs/heads/development' && github.token || '' }}"})
        self.assertIn("--tool cargo-audit", cargo["run"])
        self.assertNotIn("GH_TOKEN", rustsec.get("env", {}))
        self.assertNotIn("GH_TOKEN", rustsec["jobs"]["audit"].get("env", {}))
        for step in steps:
            if step is not cargo:
                self.assertNotIn("GH_TOKEN", step.get("env", {}))


if __name__ == "__main__":
    unittest.main()

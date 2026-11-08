"""Guest recipe isolation and bounded generator installation; no compiler/load."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from jsonschema import Draft202012Validator
from tools import install_guest_bindgen as install
from tools.build_guest_capsules import wit_bindgen_version
from tools.build_snapshot import validate_workspace
from tools.tests.test_build_provenance_schemas import samples, DIGEST

ROOT = Path(__file__).resolve().parents[2]


def guest(language):
    value = samples()["build-observation"]
    value["buildType"] = f"https://latent.dev/build/{language}-guest/v1"
    value["source"].update(revision=DIGEST[7:], capture="explicit-input-files")
    value["dependencyCompleteness"] = "declared-inputs-incomplete"
    value["materials"].append({"name": "wit-bindgen", "digest": DIGEST, "size": 1})
    if language == "rust":
        value["parameters"]["cargoExample"] = "guest-http"
    else:
        value["parameters"] = {"compiler": "zig-cc", "fixture": "blob",
                               "target": "wasm32-wasi", "optimization": "O2"}
        value["materials"] = [m for m in value["materials"]
                              if m["name"] not in {"cargo", "rustc", "dependency-lock"}]
        value["materials"].append({"name": "zig", "digest": DIGEST, "size": 1})
    return value


class GuestProfileSchemas(unittest.TestCase):
    def test_java_recipe_requires_its_closed_compiler_inputs_and_separate_type(self):
        value = guest("rust")
        value["buildType"] = "https://latent.dev/build/java-capsule/v1"
        value["parameters"] = {"compiler": "teavm-c", "entryPoint": "dev.latent.app.Capsule",
            "target": "wasm32-wasip1", "bindings": "lsf-java-wit-v1", "optimization": "O2", "javaHeapBytes": 4194304}
        value["materials"] = [item for item in value["materials"] if item["name"] not in {"cargo", "rustc"}]
        for name in ("java", "gradle", "clang", "compiler-closure", "generated-bindings", "contracts-tool", "packager", "package-inputs"):
            value["materials"].append({"name": name, "digest": DIGEST, "size": 1})
        self.validate(value)
        for material in value["materials"]:
            changed = copy.deepcopy(value)
            changed["materials"] = [item for item in changed["materials"] if item["name"] != material["name"]]
            self.validate(changed, valid=False)
        for key in value["parameters"]:
            changed = copy.deepcopy(value)
            changed["parameters"][key] = "unreviewed"
            self.validate(changed, valid=False)
        changed = copy.deepcopy(value)
        changed["buildType"] = "https://latent.dev/build/c-guest/v1"
        self.validate(changed, valid=False)

    def test_echo_snapshot_can_still_capture_every_workspace_member(self):
        validate_workspace(ROOT)

    def validate(self, value, *, valid=True):
        for name in ("build-observation", "package-provenance-statement"):
            document = value
            if name == "package-provenance-statement":
                document = samples()[name]
                document["predicate"]["observation"] = value
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            validator = Draft202012Validator(schema)
            with self.subTest(schema=name):
                self.assertEqual(validator.is_valid(document), valid,
                                 list(validator.iter_errors(document)))

    def test_guest_and_legacy_profiles_are_separate(self):
        self.validate(samples()["build-observation"])
        for language in ("rust", "c"):
            value = guest(language)
            self.validate(value)
            changed = copy.deepcopy(value)
            changed["buildType"] = "https://latent.dev/build/echo-capsule/v1"
            self.validate(changed, valid=False)
            changed = copy.deepcopy(value)
            changed["parameters"] = guest("c" if language == "rust" else "rust")["parameters"]
            self.validate(changed, valid=False)
            for name in [m["name"] for m in value["materials"]]:
                changed = copy.deepcopy(value)
                changed["materials"] = [m for m in changed["materials"] if m["name"] != name]
                self.validate(changed, valid=False)
            for field, replacement in (("hermetic", True), ("dependencyCompleteness", "complete")):
                self.validate({**value, field: replacement}, valid=False)
            for key in value["parameters"]:
                changed = copy.deepcopy(value)
                del changed["parameters"][key]
                self.validate(changed, valid=False)
            changed = copy.deepcopy(value)
            changed["parameters"]["unreviewedOption"] = True
            self.validate(changed, valid=False)


class GeneratorArchive(unittest.TestCase):
    def test_pinned_generator_version_matches_toolchain_and_lock(self):
        self.assertEqual(install.VERSION, wit_bindgen_version())
        locked = json.loads((ROOT / "tools/guest_bindings.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(f"wit-bindgen {install.VERSION}", locked["generator"])

    def archive(self, kinds):
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w:gz") as archive:
            for kind in kinds:
                info = tarfile.TarInfo("ignored-parent/wit-bindgen")
                info.type = kind
                info.size = 4 if kind == tarfile.REGTYPE else 0
                archive.addfile(info, io.BytesIO(b"tool") if info.size else None)
        return result.getvalue()

    def test_verified_regular_binary_only(self):
        data = self.archive([tarfile.REGTYPE])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            install.binary(data)
        with patch.object(install, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()):
            self.assertEqual(install.binary(data), b"tool")

    def test_links_missing_duplicate_and_oversized_binary_fail(self):
        for kinds in ([], [tarfile.SYMTYPE], [tarfile.REGTYPE, tarfile.REGTYPE]):
            data = self.archive(kinds)
            with patch.object(install, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(ValueError):
                    install.binary(data)
        data = self.archive([tarfile.REGTYPE])
        with patch.object(install, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()), \
                patch.object(install, "MAX_BINARY", 3), self.assertRaises(ValueError):
            install.binary(data)

    def test_primary_download_succeeds_without_fallback(self):
        with patch.object(install.urllib.request, 'urlopen', return_value=io.BytesIO(b'primary')) as fetch:
            self.assertEqual(install.download_archive(), b'primary')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], install.URL)

    def test_gateway_timeout_uses_only_the_exact_asset_and_original_validation(self):
        archive = self.archive([tarfile.REGTYPE])
        failure = urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, None)
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(install.urllib.request, 'urlopen', side_effect=[failure, io.BytesIO(archive)]) as fetch, \
             patch.object(install.time, 'monotonic', side_effect=[0, 0, 80, 80, 80]), \
             patch.object(install.platform, 'system', return_value='Linux'), \
             patch.object(install.platform, 'machine', return_value='x86_64'), \
             patch.object(install, 'ARCHIVE_SHA256', hashlib.sha256(archive).hexdigest()), \
             patch.object(sys, 'argv', ['install_guest_bindgen.py', str(Path(temp)/'out')]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            install.main()
            self.assertEqual((Path(temp)/'out/wit-bindgen').read_bytes(), b'tool')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args[0], install.URL)
        asset = fetch.call_args_list[1].args[0]
        self.assertEqual(asset.full_url, install.ASSET_URL)
        self.assertEqual(asset.get_header('Accept'), 'application/octet-stream')
        self.assertIsNone(asset.get_header('Authorization'))
        self.assertEqual(fetch.call_args_list[1].kwargs['timeout'], 10)

    def test_other_http_and_transport_errors_are_not_retried(self):
        errors = [urllib.error.HTTPError(install.URL, code, 'failure', {}, None)
                  for code in (400, 403, 404, 429, 500, 502, 503)]
        errors.append(urllib.error.URLError('unavailable'))
        for error in errors:
            with self.subTest(error=error), patch.object(install.urllib.request, 'urlopen', side_effect=error) as fetch:
                with self.assertRaises(type(error)):
                    install.download_archive()
                self.assertEqual(fetch.call_count, 1)

    def test_gateway_response_is_closed_before_opening_asset(self):
        body = io.BytesIO(b'gateway failure')
        failure = urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, body)

        def open_response(request, *, timeout):
            self.assertGreater(timeout, 0)
            if request == install.URL:
                self.assertFalse(body.closed)
                raise failure
            self.assertEqual(request.full_url, install.ASSET_URL)
            self.assertTrue(body.closed)
            return io.BytesIO(b'asset')

        with patch.object(install.urllib.request, 'urlopen', side_effect=open_response) as fetch, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(install.download_archive(), b'asset')
        self.assertTrue(body.closed)
        self.assertEqual(fetch.call_count, 2)

    def test_primary_open_timeout_uses_the_pinned_asset(self):
        fallback = io.BytesIO(b'asset')
        with patch.object(install.urllib.request, 'urlopen', side_effect=[TimeoutError('open timed out'), fallback]) as fetch, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(install.download_archive(), b'asset')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[1].args[0].full_url, install.ASSET_URL)
        self.assertTrue(fallback.closed)

    def test_partial_read_timeout_closes_and_discards_primary_before_fallback(self):
        class PartialThenTimeout(io.BytesIO):
            def __init__(self):
                super().__init__(b'partial')
                self.calls = 0
            def read(self, size=-1):
                self.calls += 1
                if self.calls > 1:
                    raise TimeoutError('read timed out')
                return super().read(size)

        primary, fallback = PartialThenTimeout(), io.BytesIO(b'asset')
        def open_response(request, *, timeout):
            self.assertGreater(timeout, 0)
            if request == install.URL:
                return primary
            self.assertEqual(request.full_url, install.ASSET_URL)
            self.assertTrue(primary.closed)
            return fallback
        with patch.object(install.urllib.request, 'urlopen', side_effect=open_response) as fetch, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(install.download_archive(), b'asset')
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(primary.closed and fallback.closed)

    def test_fallback_read_timeout_is_not_retried(self):
        class ReadTimeout(io.BytesIO):
            def read(self, size=-1):
                raise TimeoutError('fallback read timed out')
        fallback = ReadTimeout()
        with patch.object(install.urllib.request, 'urlopen', side_effect=[TimeoutError('primary timed out'), fallback]) as fetch, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(TimeoutError, 'fallback read timed out'):
                install.download_archive()
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(fallback.closed)

    def test_fallback_failure_is_not_retried(self):
        errors = [urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, None),
                  urllib.error.HTTPError(install.ASSET_URL, 503, 'unavailable', {}, None)]
        with patch.object(install.urllib.request, 'urlopen', side_effect=errors) as fetch, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(urllib.error.HTTPError) as failure:
                install.download_archive()
        self.assertEqual(failure.exception.code, 503)
        self.assertEqual(fetch.call_count, 2)

    def test_download_size_and_shared_deadline_cover_both_attempts(self):
        for fallback in (False, True):
            responses = [io.BytesIO(b'four')]
            if fallback:
                responses.insert(0, urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, None))
            with self.subTest(fallback=fallback), patch.object(install, 'MAX_ARCHIVE', 3), \
                 patch.object(install.urllib.request, 'urlopen', side_effect=responses) as fetch, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'download bound exceeded'):
                    install.download_archive()
                self.assertEqual(fetch.call_count, 2 if fallback else 1)
        failure = urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, None)
        with patch.object(install.urllib.request, 'urlopen', side_effect=failure) as fetch, \
             patch.object(install.time, 'monotonic', side_effect=[0, 0, 91]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'download bound exceeded'):
                install.download_archive()
        self.assertEqual(fetch.call_count, 1)

    def test_invalid_download_never_installs_or_retries(self):
        for fallback in (False, True):
            responses = [io.BytesIO(b'tampered')]
            if fallback:
                responses.insert(0, urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, None))
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as temp, \
                 patch.object(install.urllib.request, 'urlopen', side_effect=responses) as fetch, \
                 patch.object(install.platform, 'system', return_value='Linux'), \
                 patch.object(install.platform, 'machine', return_value='x86_64'), \
                 patch.object(sys, 'argv', ['install_guest_bindgen.py', str(Path(temp)/'out')]), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'archive identity mismatch'):
                    install.main()
                self.assertFalse((Path(temp)/'out').exists())
                self.assertEqual(fetch.call_count, 2 if fallback else 1)

        archive = self.archive([tarfile.SYMTYPE])
        responses = [urllib.error.HTTPError(install.URL, 504, 'gateway timeout', {}, None), io.BytesIO(archive)]
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(install.urllib.request, 'urlopen', side_effect=responses), \
             patch.object(install.platform, 'system', return_value='Linux'), \
             patch.object(install.platform, 'machine', return_value='x86_64'), \
             patch.object(install, 'ARCHIVE_SHA256', hashlib.sha256(archive).hexdigest()), \
             patch.object(sys, 'argv', ['install_guest_bindgen.py', str(Path(temp)/'out')]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'not a bounded regular file'):
                install.main()
            self.assertFalse((Path(temp)/'out').exists())


if __name__ == "__main__":
    unittest.main()

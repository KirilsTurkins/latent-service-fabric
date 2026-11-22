"""Locked dependency failures identify the input without admitting bad bytes."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch, call

from tools.tests.test_java_toolchain import build


class DependencyDiagnosticsTests(unittest.TestCase):
    def test_http_failure_names_exact_coordinate_before_cache_or_generation(self):
        for platform in ("Linux", "Windows"):
            for status, attempts in ((404, 1), (403, 1), (503, 3)):
                with self.subTest(platform=platform, status=status), tempfile.TemporaryDirectory() as directory:
                    sdk = Path(directory)
                    artifact = {"path": "example/transport/1/transport-1.jar", "platform": "any",
                                "size": 3, "sha256": hashlib.sha256(b"jar").hexdigest()}
                    url = "https://repo.test/maven2/" + artifact["path"]
                    lock = json.dumps({"maven": "https://repo.test/maven2/", "artifacts": [artifact]})
                    (sdk / "dependencies.lock.json").write_text(lock)
                    errors = [urllib.error.HTTPError(url, status, "fixture", {}, None) for _ in range(attempts)]
                    with patch.object(build, "SDK", sdk), patch.object(build, "BUILD", sdk / "build"), \
                            patch.object(build.platform, "system", return_value=platform), \
                            patch.object(build.platform, "machine", return_value="x86_64"), \
                            patch.object(build.urllib.request, "urlopen", side_effect=errors) as open_, \
                            patch.object(build.time, "sleep") as sleep, patch.object(build, "run") as run:
                        with self.assertRaises(ValueError) as failure:
                            build.prepare()
                    self.assertEqual(str(failure.exception),
                                     f"locked dependency download failed: {artifact['path']} (HTTP {status})")
                    self.assertIs(failure.exception.__cause__, errors[-1])
                    self.assertEqual(open_.call_args_list, [call(url, timeout=30)] * attempts)
                    self.assertEqual(sleep.call_args_list, [call(1), call(2)] if attempts == 3 else [])
                    run.assert_not_called()
                    self.assertEqual(list((sdk / "build/deps").iterdir()), [])
                    self.assertFalse((sdk / "build/generated").exists())
                    self.assertEqual((sdk / "dependencies.lock.json").read_text(), lock)

    def test_completed_dependency_survives_later_failure_without_publishing_missing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            first = {"path": "example/first/1/first-1.jar", "platform": "any", "size": 3,
                     "sha256": hashlib.sha256(b"jar").hexdigest()}
            second = dict(first, path="example/second/1/second-1.jar")
            (sdk / "dependencies.lock.json").write_text(json.dumps({
                "maven": "https://repo.test/", "artifacts": [first, second]}))
            missing = urllib.error.HTTPError("https://repo.test/" + second["path"], 404, "missing", {}, None)
            with patch.object(build, "SDK", sdk), patch.object(build, "BUILD", sdk / "build"), \
                    patch.object(build.platform, "system", return_value="Linux"), \
                    patch.object(build.platform, "machine", return_value="x86_64"), \
                    patch.object(build.urllib.request, "urlopen", side_effect=[io.BytesIO(b"jar"), missing]) as open_, \
                    patch.object(build.time, "sleep") as sleep, patch.object(build, "run") as run:
                with self.assertRaisesRegex(ValueError, "second/1/second-1.jar"):
                    build.prepare()
            self.assertEqual((sdk / "build/deps/first-1.jar").read_bytes(), b"jar")
            self.assertFalse((sdk / "build/deps/second-1.jar").exists())
            self.assertEqual(open_.call_count, 2)
            sleep.assert_not_called()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

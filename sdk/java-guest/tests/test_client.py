"""Source binding and native ownership controls; not component compatibility evidence."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import java_http_client as client
from tools.java_capsule_project import ROOT, create, validate
from tools.rust_capsule_project import canonical, snapshot


class HttpClient(unittest.TestCase):
    def test_explicit_profile_is_captured_and_bound_to_all_build_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "outside", "greeting")
            files = snapshot(project)
            declaration = json.loads(files["capsule-project.json"])
            declaration["httpClient"] = {"profile": client.PROFILE_ID}
            files["capsule-project.json"] = canonical(declaration)
            checked, lock, _pins = validate(files)
            self.assertEqual(checked["httpClient"], {"profile": client.PROFILE_ID})
            self.assertIn("sdk/java-guest/client/dev/latent/guest/client/Connection.java", lock["sdk"])
            first = client.profile(ROOT / "sdk/java-guest", b"recipe", b"source", b"component")
            for recipe, source, component in ((b"new", b"source", b"component"),
                                              (b"recipe", b"new", b"component"),
                                              (b"recipe", b"source", b"new")):
                self.assertNotEqual(first, client.profile(ROOT / "sdk/java-guest", recipe, source, component))
            self.assertEqual(json.loads(first)["qualification"], "pending")
            declaration["httpClient"]["profile"] = "unknown-profile"
            files["capsule-project.json"] = canonical(declaration)
            with self.assertRaisesRegex(ValueError, "unknown Java standard HTTP profile"):
                validate(files)

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "native JDK controls")
    def test_native_state_errors_and_owned_handles_never_replay_or_fake_eof(self):
        sdk = ROOT / "sdk/java-guest"
        sources = list((sdk / "client/dev").rglob("*.java"))
        sources += list((sdk / "tests/client").glob("*.java"))
        sources += [sdk / "runtime/dev/latent/guest" / name for name in ("Option.java", "Result.java", "Unit.java", "Unsigned64.java")]
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", temporary, *map(str, sources)],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(["java", "-cp", temporary, "dev.latent.guest.client.Ownership"],
                                    check=True, capture_output=True, text=True, timeout=15)
            self.assertIn("NATIVE_MODEL_CONTROLS=15; COMPONENT_QUALIFICATION=pending", result.stdout)


    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "native JDK controls")
    def test_native_response_headers_coalesce_casing_in_wire_order_and_stay_owned(self):
        sdk = ROOT / "sdk/java-guest"
        sources = list((sdk / "client/dev").rglob("*.java"))
        sources += list((sdk / "tests/client").glob("*.java"))
        sources += [sdk / "runtime/dev/latent/guest" / name for name in ("Option.java", "Result.java", "Unit.java", "Unsigned64.java")]
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", temporary, *map(str, sources)],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(["java", "-cp", temporary, "dev.latent.guest.client.HeaderFields"],
                                    check=True, capture_output=True, text=True, timeout=15)
            self.assertIn("HEADER_MODEL_CONTROLS=4; COMPONENT_QUALIFICATION=pending", result.stdout)


    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "native JDK controls")
    def test_nullable_response_message_preserves_status_failure_owner_and_timeout_boundaries(self):
        sdk = ROOT / "sdk/java-guest"
        sources = list((sdk / "client/dev").rglob("*.java"))
        sources += list((sdk / "tests/client").glob("*.java"))
        sources += [sdk / "runtime/dev/latent/guest" / name for name in
                    ("Option.java", "Result.java", "Unit.java", "Unsigned64.java")]
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", temporary, *map(str, sources)],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(["java", "-cp", temporary, "dev.latent.guest.client.ResponseMessages"],
                                    check=True, capture_output=True, text=True, timeout=15)
            self.assertIn("RESPONSE_MESSAGE_MODEL_CONTROLS=6; COMPONENT_QUALIFICATION=pending", result.stdout)


    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "native JDK controls")
    def test_https_type_identity_preserves_plain_http_and_refuses_tls_before_effects(self):
        sdk = ROOT / "sdk/java-guest"
        sources = list((sdk / "client/dev").rglob("*.java"))
        sources += list((sdk / "tests/client").glob("*.java"))
        sources += [sdk / "runtime/dev/latent/guest" / name for name in
                    ("Option.java", "Result.java", "Unit.java", "Unsigned64.java")]
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", temporary, *map(str, sources)],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(["java", "-cp", temporary, "dev.latent.guest.client.HttpsType"],
                                    check=True, capture_output=True, text=True, timeout=15)
            self.assertIn("HTTPS_TYPE_MODEL_CONTROLS=5; COMPONENT_QUALIFICATION=pending; TLS_QUALIFICATION=unsupported",
                          result.stdout)


if __name__ == "__main__":
    unittest.main()

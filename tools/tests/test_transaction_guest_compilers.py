"""Authored compiler receipt boundaries, without claiming guest execution."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.compile_transaction_guests import check_surface, compile_guests
from tools.transaction_guest_variants import HTTP


def contract():
    state = {"types": {"transaction": {"resource": "latent:state/key-value@0.2.0/transaction"}},
             "functions": {"get": {"kind": "async-freestanding", "params": ["borrow-transaction"], "result": "option-value"}}}
    intents = {"types": copy.deepcopy(state["types"]),
               "functions": {"stage": {"kind": "async-freestanding", "params": ["borrow-transaction"], "result": "result-sequence"}}}
    return {"imports": {"latent:state/key-value@0.2.0": state, "latent:intents/staging@0.1.0": intents},
            "exports": {"api": {"update": "async-business-result", "query": "async-fresh-value", "scan": "async-page"}}}


class TransactionGuestCompilerTests(unittest.TestCase):
    def test_post_stage_diagnostic_mode_is_java_only_exclusive_and_retains_its_failed_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "uncreated"
            for language in ("rust", "c", "go", "dotnet", "typescript", "future"):
                with self.subTest(language=language), self.assertRaisesRegex(ValueError, "exclusive explicit Java compiler"):
                    compile_guests(language, output, java_post_stage_diagnostic=True)
                self.assertFalse(output.exists())
            for value in (1, 0, None, "true"):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "exclusive explicit Java compiler"):
                    compile_guests("java", output, java_post_stage_diagnostic=value)
                self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError, "exclusive explicit Java compiler"):
                compile_guests("java", output, java_post_stage_diagnostic=True, java_schema_put_once=True)
            self.assertFalse(output.exists())
            with patch("tools.compile_transaction_guests.authored_project", side_effect=ValueError("original-diagnostic-capture-failed")):
                with self.assertRaisesRegex(ValueError, "original-diagnostic-capture-failed"):
                    compile_guests("java", output, java_post_stage_diagnostic=True)
            self.assertEqual({path.name for path in output.iterdir()}, {"put-once-diagnostics"})
            report = json.loads((output / "put-once-diagnostics/report.json").read_bytes())
            self.assertEqual(report["variant"], "put-once-diagnostics")
            self.assertFalse(report["compiled"])
            self.assertFalse(report["signedNodeExecutionQualified"])
            self.assertFalse(report["admissionRejectionQualified"])
            self.assertEqual(report["reason"], "original-diagnostic-capture-failed")

    def test_authored_surface_keeps_declared_results_and_canonical_async_owners(self):
        expected = contract()
        check_surface(expected, copy.deepcopy(expected), "aggregate")
        for change in ("missing-intents", "sync-get", "forged-owner", "new-export"):
            actual = copy.deepcopy(expected)
            if change == "missing-intents":
                actual["imports"].pop("latent:intents/staging@0.1.0")
            elif change == "sync-get":
                actual["imports"]["latent:state/key-value@0.2.0"]["functions"]["get"]["kind"] = "freestanding"
            elif change == "forged-owner":
                actual["imports"]["latent:intents/staging@0.1.0"]["types"]["transaction"] = "caller-string"
            else:
                actual["exports"]["commit"] = "guest-early-commit"
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_surface(expected, actual, "aggregate")

    def test_forbidden_fixture_requires_an_actual_declared_async_http_import(self):
        expected = contract()
        expected["imports"][HTTP] = {"types": {}, "functions": {"send": {"kind": "async-freestanding", "result": "typed-http-result"}}}
        check_surface(expected, copy.deepcopy(expected), "forbidden-http")
        for change in ("removed", "sync", "other-authority", "positive", "future"):
            actual = copy.deepcopy(expected)
            variant = "forbidden-http"
            if change == "removed":
                actual["imports"].pop(HTTP)
            elif change == "sync":
                actual["imports"][HTTP]["functions"]["send"]["kind"] = "freestanding"
            elif change == "other-authority":
                actual["imports"]["wasi:sockets/tcp@0.2.0"] = {"types": {}, "functions": {}}
            else:
                variant = "aggregate" if change == "positive" else "future"
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_surface(expected, actual, variant)

    def test_failed_capture_retains_failure_and_cannot_claim_compilation_or_signed_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "receipt"
            with patch("tools.compile_transaction_guests.authored_project", side_effect=ValueError("controlled-source-failure")):
                with self.assertRaisesRegex(ValueError, "controlled-source-failure"):
                    compile_guests("rust", output)
            report = json.loads((output / "aggregate/report.json").read_bytes())
            self.assertEqual(report["status"], "failed")
            self.assertFalse(report["compiled"])
            self.assertFalse(report["signedNodeExecutionQualified"])
            self.assertFalse(report["admissionRejectionQualified"])
            self.assertEqual(report["reason"], "controlled-source-failure")
            self.assertFalse((output / "forbidden-http").exists())

    def test_three_java_schema_captures_keep_real_put_once_inputs_and_original_read_tokens(self):
        from tools.compile_transaction_guests import authored_project
        from tools.java_transaction_schema import DEFINITIONS
        from tools.rust_capsule_project import digest
        from tools.transaction_guest_project import HTTP_BODY, put_once_requirements

        with tempfile.TemporaryDirectory() as temporary:
            for variant in ("legacy-v1", "compatible-v2", "writer-v2"):
                with self.subTest(variant=variant):
                    work = authored_project("java", "put-once-" + variant, Path(temporary) / variant)
                    source = (work / "src/dev/latent/app/Capsule.java").read_bytes()
                    owner = json.loads((work / "capsule-project.json").read_bytes())
                    binding = (work / "transaction-binding.json").read_bytes()
                    requirements = json.loads((work / "deferred-http-requirements.json").read_bytes())
                    schema = json.loads((work / "application-schema-inputs.json").read_bytes())
                    lock = json.loads((work / "sdk-lock.json").read_bytes())
                    self.assertEqual(requirements, put_once_requirements(owner, binding))
                    self.assertEqual(lock["template"]["sourceDigest"], digest(source))
                    self.assertEqual(schema["variant"], variant)
                    self.assertEqual(schema["effect"], "put-once")
                    self.assertEqual(schema["writers"], [DEFINITIONS["v2" if variant == "writer-v2" else "v1"]])
                    self.assertFalse(schema["componentCompiled"])
                    self.assertFalse(schema["stateExecutionQualified"])
                    self.assertEqual(owner["limits"]["effectCount"], 1)
                    self.assertEqual(owner["limits"]["outboundRequests"], 0)
                    self.assertEqual(owner["limits"]["childCalls"], 0)
                    self.assertIn(b'new Intent("qualified-http", "put-once", effectPayload).stage(command)', source)
                    self.assertNotIn(b"LatentHttpClient.send", source)
                    self.assertEqual(len(HTTP_BODY), 27)
                    wit = (work / "wit/world.wit").read_text()
                    self.assertIn("view-version: list<u8>", wit)
                    self.assertIn("key-version: option<list<u8>>", wit)

    def test_java_schema_mode_rejects_wrong_compiler_or_implicit_boolean_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "uncreated"
            for language in ("rust", "c", "go", "dotnet", "typescript", "future"):
                with self.subTest(language=language), self.assertRaisesRegex(ValueError, "explicit Java compiler"):
                    compile_guests(language, output, java_schema_put_once=True)
                self.assertFalse(output.exists())
            for value in (1, 0, None, "true"):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "explicit Java compiler"):
                    compile_guests("java", output, java_schema_put_once=value)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

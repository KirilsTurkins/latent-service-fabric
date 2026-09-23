"""Closed source and identity boundaries for standalone C authoring."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import c_capsule_project as project
from tools.c_capsule_build import build
from tools.c_guest.bindings import aliases
from tools.rust_capsule_node import RecordingClient
from tools.phase2_operator_process import Client, WorkflowError


class CAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="c-authoring-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = project.create(Path(cls.temporary.name) / "project", "greeting")
        cls.files = project.snapshot(cls.root)

    def test_all_templates_capture_editable_source_and_authoritative_contracts(self):
        for template in project.TEMPLATES:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temporary:
                root = project.create(Path(temporary) / "project", template)
                files = project.snapshot(root)
                value, lock, pins = project.validate(files)
                self.assertEqual(value["world"], f"examples:{template}/service@1.0.0")
                self.assertEqual(value["limits"]["outboundRequests"], int(template == "http-status"))
                self.assertEqual(lock["template"]["sourceDigest"], project.digest(files["src/main.c"]))
                self.assertEqual(pins["sdk"]["zig"], "0.16.0")
                files["src/main.c"] += b"\n/* application change */\n"
                project.validate(files)

    def test_fresh_output_does_not_overwrite_existing_project(self):
        with self.assertRaisesRegex(ValueError, "fresh"):
            project.create(self.root, "shipping")
        self.assertEqual(project.snapshot(self.root), self.files)

    def test_sdk_header_and_toolchain_drift_are_rejected(self):
        for name in ("sdk/c-guest/include/lsf/ownership.h", "tools/toolchain.toml", "wit/platform/http-v2/package.wit"):
            files = dict(self.files)
            files["vendor/lsf/" + name] += b"\n"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "vendored SDK changed"):
                project.validate(files)

    def test_identity_budget_and_lock_formats_are_closed(self):
        for name, mutate in (
            ("capsule-project.json", lambda value: value.update(formatVersion=True)),
            ("capsule-project.json", lambda value: value.update(extra=1)),
            ("capsule-project.json", lambda value: value.update(name="../escape")),
            ("capsule-project.json", lambda value: value["limits"].update(cpuFuel=True)),
            ("capsule-project.json", lambda value: value["limits"].update(memoryBytes=2**64)),
            ("capsule-project.json", lambda value: value["limits"].update(wallTimeLimitMillis=None)),
            ("sdk-lock.json", lambda value: value.update(language="rust")),
        ):
            files = dict(self.files)
            value = json.loads(files[name])
            mutate(value)
            files[name] = json.dumps(value).encode()
            with self.subTest(name=name), self.assertRaises(ValueError):
                project.validate(files)

    def test_source_overlap_is_rejected_before_any_compiler_runs(self):
        for output in (self.root, self.root.parent, self.root / "output"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "build output"):
                build(self.root, output, Path("missing"), Path("missing"), "https://example.invalid/source")

    def test_c_namespace_aliases_never_invent_or_hide_ambiguous_bindings(self):
        value = aliases("latent_http_0_2_0_client_send latent_http_0_3_0_streaming_open")
        self.assertIn("#define latent_http_client_send latent_http_0_2_0_client_send", value)
        self.assertNotIn("#define latent_http_client_delete", value)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            aliases("latent_http_0_2_0_client_send latent_http_client_send")

    def test_invalid_names_and_templates_leave_no_partial_project(self):
        for name in ("../escape", "Name", "a--b", "x" * 65):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "project"
                with self.assertRaises(ValueError):
                    project.create(output, "greeting", name)
                self.assertFalse(output.exists())


class ControlDiagnosticsTests(unittest.TestCase):
    def test_paginated_evidence_never_retries_or_changes_the_failed_mutation(self):
        requests = []
        def invoke(client, *arguments, **_kwargs):
            requests.append(arguments)
            client.calls += 1
            if arguments[:2] == ("deployment", "apply"):
                return {"category": "platform-failure", "outcomeKnown": False, "data": {}}
            token = "next" if arguments[0] == "audit" and "--page-token" not in arguments else None
            return {"category": "success", "data": {"nextPageToken": token}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = RecordingClient("unused", root, None, 0, evidence=root / "evidence")
            with patch.object(Client, "call", invoke), self.assertRaisesRegex(WorkflowError, "authoring-control-1-4"):
                client.call("deployment", "apply", "public.json", "--operation-id", "test-operation")
            evidence = json.loads((root / "evidence/unexpected-control-diagnostics.json").read_text())
            self.assertEqual(sum(args[:2] == ("deployment", "apply") for args in requests), 1)
            self.assertEqual(len(evidence["audit"]), 2)
            self.assertTrue(evidence["auditComplete"])
            self.assertEqual(evidence["failedCall"], 1)
            self.assertIn("--page-token", requests[-1])

    def test_cyclic_audit_cursor_stops_without_hiding_the_original_failure(self):
        def invoke(client, *arguments, **_kwargs):
            client.calls += 1
            return {"category": "platform-failure" if client.calls == 1 else "success",
                    "data": {"nextPageToken": "cycle"}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = RecordingClient("unused", root, None, 0, evidence=root / "evidence")
            with patch.object(Client, "call", invoke), self.assertRaisesRegex(WorkflowError, "authoring-control-1-4"):
                client.call("node", "get", "test")
            evidence = json.loads((root / "evidence/unexpected-control-diagnostics.json").read_text())
            self.assertFalse(evidence["auditComplete"])
            self.assertEqual(evidence["auditFailure"], "WorkflowError")
            self.assertEqual(client.calls, 3)


if __name__ == "__main__":
    unittest.main()

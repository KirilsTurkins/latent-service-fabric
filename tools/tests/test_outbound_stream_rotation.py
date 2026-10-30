"""Protected rotation candidate controls; node replies are explicit process doubles."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import outbound_stream_operator as stream
from tools.dev_workflow import paths
from tools.dev_workflow.common import DevError, encode
from tools.tests import test_outbound_stream_operator as configuration_fixture


class StreamRotation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).absolute()
        self.root.chmod(0o700)
        fixture = configuration_fixture.StreamConfiguration()
        fixture.setUp()
        self.settings = fixture.configure(development_profile=True)
        self.rotation = {"formatVersion": 1,
            "provider": {"id": "streams", "tenant": "examples", "service": "stream-host"},
            "expectedEpoch": 1, "newEpoch": 2,
            "limits": {"maximumTransferBytes": 32768, "idleTimeoutMillis": 500, "absoluteTimeoutMillis": 4000}}
        self.base, self.record, self.output, self.node = (self.root / name for name in
            ("base.json", "rotation.json", "candidate.json", "latentd"))
        paths.write_new(self.base, encode(self.settings))
        paths.write_new(self.record, encode(self.rotation))
        paths.write_new(self.node, b"PUBLIC-ROTATION-SOURCE-CONTROL-IDENTITY")

    def rotate(self, record=None, **arguments):
        return stream.rotate_configuration(self.settings, self.rotation if record is None else record, **arguments)

    def prepare(self, **arguments):
        return stream.prepare_rotation_configuration(self.base, self.record, self.output, self.node, **arguments)

    def test_only_two_reload_fields_change_and_original_credentials_bindings_and_inputs_stay_exact(self):
        original = copy.deepcopy(self.settings)
        before = encode(self.settings), encode(self.rotation)
        result = self.rotate(development_profile=True)
        selected = result["providers"]["outboundStreams"]
        self.assertEqual(selected["identity"]["epoch"], 2)
        self.assertEqual(selected["configuration"]["limits"], self.rotation["limits"])
        selected["identity"]["epoch"] = original["providers"]["outboundStreams"]["identity"]["epoch"]
        selected["configuration"]["limits"] = original["providers"]["outboundStreams"]["configuration"]["limits"]
        self.assertEqual(encode(result), encode(original))
        self.assertEqual(before, (encode(self.settings), encode(self.rotation)))

    def test_exact_provider_and_supplied_base_epoch_cannot_be_substituted(self):
        for field in ("id", "tenant", "service"):
            record = copy.deepcopy(self.rotation)
            record["provider"][field] = "foreign"
            with self.assertRaisesRegex(DevError, "rotation-provider-mismatch"):
                self.rotate(record, development_profile=True)
        record = {**self.rotation, "expectedEpoch": 2}
        with self.assertRaisesRegex(DevError, "rotation-base-epoch-mismatch"):
            self.rotate(record, development_profile=True)
        self.settings["providers"].pop("outboundStreams")
        with self.assertRaisesRegex(DevError, "rotation-installation-required"):
            self.rotate(development_profile=True)

    def test_epochs_require_strict_positive_u64_and_monotonic_new_value(self):
        for field in ("expectedEpoch", "newEpoch"):
            for value in (True, 1.0, 0, -1, 18446744073709551616, "2"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(DevError):
                        self.rotate({**self.rotation, field: value}, development_profile=True)
        with self.assertRaisesRegex(DevError, "rotation-epoch-not-newer"):
            self.rotate({**self.rotation, "newEpoch": 1}, development_profile=True)
        self.settings["providers"]["outboundStreams"]["identity"]["epoch"] = 18446744073709551614
        result = self.rotate({**self.rotation, "expectedEpoch": 18446744073709551614,
                             "newEpoch": 18446744073709551615}, development_profile=True)
        self.assertEqual(result["providers"]["outboundStreams"]["identity"]["epoch"], 18446744073709551615)

    def test_closed_record_and_original_limit_deadline_bounds_cannot_change_other_fields(self):
        variants = [{**self.rotation, "credential": "PRIVATE-DO-NOT-ECHO"},
                    {**self.rotation, "destinations": []}, {**self.rotation, "formatVersion": 1.0}]
        for key, value in (("maximumTransferBytes", 1048577), ("idleTimeoutMillis", 2001),
                           ("absoluteTimeoutMillis", 10001), ("idleTimeoutMillis", 500.0),
                           ("maximumTransferBytes", True), ("absoluteTimeoutMillis", 499)):
            variants.append({**self.rotation, "limits": {**self.rotation["limits"], key: value}})
        for record in variants:
            with self.assertRaises(DevError) as failure:
                self.rotate(record, development_profile=True)
            self.assertNotIn("PRIVATE-DO-NOT-ECHO", str(failure.exception))

    def test_checked_private_candidate_uses_selected_binary_once_without_exposing_process_output(self):
        before = self.base.read_bytes(), self.record.read_bytes()
        response = subprocess.CompletedProcess([], 0, b"PRIVATE-NODE-OUTPUT", b"PRIVATE-NODE-ERROR")
        with patch("tools.dev_workflow.process.run", return_value=response) as run:
            result = self.prepare(development_profile=True)
        run.assert_called_once_with([str(self.node), "check-config", "--config", str(self.output)],
                                    self.root, timeout=30, maximum=65536)
        self.assertEqual(json.loads(self.output.read_bytes()), self.rotate(development_profile=True))
        self.assertEqual(before, (self.base.read_bytes(), self.record.read_bytes()))
        self.assertEqual(result["outcome"], "prepared-rotation-configuration-check-accepted")
        self.assertEqual(result["nodeBinary"]["sha256"], stream.digest(self.node.read_bytes()))
        self.assertFalse(result["executionPermission"])
        self.assertEqual(result["providerReadiness"], "not-observed")
        self.assertNotIn("PRIVATE-", json.dumps(result))
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_refusal_or_unknown_check_retains_candidate_without_fallback_or_live_input_replacement(self):
        before = self.base.read_bytes(), self.record.read_bytes()
        response = subprocess.CompletedProcess([], 2, b"", b"PRIVATE-NODE-ERROR")
        with patch("tools.dev_workflow.process.run", return_value=response) as run:
            with self.assertRaisesRegex(DevError, "node-check-rejected-prepared-file-retained"):
                self.prepare(development_profile=True)
        self.assertEqual(run.call_count, 1)
        prepared = self.output.read_bytes()
        with patch("tools.dev_workflow.process.run") as run:
            with self.assertRaisesRegex(DevError, "output-not-new"):
                self.prepare(development_profile=True)
        run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), prepared)
        self.output.unlink()
        with patch("tools.dev_workflow.process.run", side_effect=DevError("owned-process-failed", uncertain=True)) as run:
            with self.assertRaises(DevError) as failure:
                self.prepare(development_profile=True)
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.output.read_bytes(), prepared)
        self.assertEqual(before, (self.base.read_bytes(), self.record.read_bytes()))

    def test_protected_rotation_input_and_explicit_opt_in_are_required_before_any_candidate_or_process(self):
        with patch("tools.dev_workflow.process.run") as run:
            with self.assertRaisesRegex(DevError, "development-profile-required"):
                self.prepare()
            alias = self.root / "linked-record.json"
            os.link(self.record, alias)
            try:
                with self.assertRaisesRegex(DevError, "single-link-regular-file-required"):
                    self.prepare(development_profile=True)
            finally:
                alias.unlink()
            self.record.write_bytes(encode({**self.rotation, "expectedEpoch": 2}))
            with self.assertRaisesRegex(DevError, "rotation-base-epoch-mismatch"):
                self.prepare(development_profile=True)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_public_cli_dispatches_rotation_and_rejects_initial_installation_arguments(self):
        arguments = ["prepare-rotation", "--node", str(self.node), "--base-config", str(self.base),
                     "--rotation-record", str(self.record), "--output", str(self.output), "--development-profile"]
        output, error = io.StringIO(), io.StringIO()
        with patch("tools.dev_workflow.process.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            with redirect_stdout(output), redirect_stderr(error):
                code = stream.main(arguments)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(error.getvalue(), "")
        self.assertEqual(json.loads(output.getvalue())["command"], "prepare-rotation")
        with patch("tools.dev_workflow.process.run") as run:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = stream.main(arguments + ["--installation-record", str(self.record)])
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_rotation_schema_is_the_canonical_resource_in_the_existing_helper_package(self):
        from tools import build_dev_frontend as frontend
        archive_path = self.root / "helper.pyz"
        frontend.helper(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            for name in ("node-providers.schema.json", "outbound-stream-provider.schema.json",
                         "outbound-stream-rotation.schema.json"):
                self.assertEqual(archive.read("tools/dev_workflow/data/schemas/" + name),
                                 (frontend.ROOT / "schemas" / name).read_bytes())
            self.assertEqual(archive.read("tools/outbound_stream_operator.py"),
                             (frontend.ROOT / "tools/outbound_stream_operator.py").read_bytes())


if __name__ == "__main__":
    unittest.main()

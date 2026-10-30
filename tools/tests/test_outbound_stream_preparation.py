"""Protected preparation source controls; subprocess replies are explicit doubles."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import tempfile
import unittest
from unittest.mock import patch

from tools import outbound_stream_operator as stream
from tools.dev_workflow import paths
from tools.dev_workflow.common import DevError, encode
from tools.tests import test_outbound_stream_operator as configuration_fixture


class StreamPreparation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).absolute()
        self.root.chmod(0o700)
        # Reuse the existing complete configuration fixture, not its test cases.
        fixture = configuration_fixture.StreamConfiguration()
        fixture.setUp()
        self.settings = copy.deepcopy(fixture.settings)
        self.record = {"installation": fixture.installation, "bindings": fixture.bindings}
        self.base, self.installation, self.output = (self.root / name for name in
                                                    ("base.json", "installation.json", "prepared.json"))
        paths.write_new(self.base, encode(self.settings))
        paths.write_new(self.installation, encode(self.record))
        self.node = self.root / "latentd"
        paths.write_new(self.node, b"PUBLIC-SOURCE-CONTROL-NODE-IDENTITY")

    def prepare(self, **arguments):
        return stream.prepare_configuration(self.base, self.installation, self.output,
                                            self.node, **arguments)

    def test_preparation_preserves_protected_inputs_and_invokes_only_check_config_once(self):
        self.settings["providers"]["http"] = {
            "identity": {"id": "http", "tenant": "examples", "service": "http-host", "epoch": 7},
            "configuration": {"formatVersion": 1, "publicRoots": False, "extraRoots": [],
                "destinations": [{"origin": {"scheme": "http", "host": "127.0.0.1", "port": 32124},
                    "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
                    "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
                    "allowedRequestHeaders": [], "redirectDestinations": []}],
                "limits": {"maximumRequestBodyBytes": 1, "maximumResponseBodyBytes": 1,
                    "maximumEncodedResponseBytes": 1, "maximumHeaderBytes": 1024,
                    "maximumHeaders": 1, "maximumRedirects": 0}}}
        self.settings["providers"]["bindings"] = [{"name": "existing-http", "tenant": "examples",
            "consumerService": "examples/mail", "providerService": "http-host",
            "contract": "latent:http/client@0.2.0", "providerBinding": "existing-http-installed"}]
        self.base.write_bytes(encode(self.settings))
        before = self.base.read_bytes(), self.installation.read_bytes()
        response = subprocess.CompletedProcess([], 0, b"PRIVATE-NODE-OUTPUT", b"PRIVATE-NODE-ERROR")
        with patch("tools.dev_workflow.process.run", return_value=response) as run:
            result = self.prepare(development_profile=True)
        run.assert_called_once_with([str(self.node), "check-config", "--config", str(self.output)],
                                    self.root, timeout=30, maximum=65536)
        self.assertEqual(before, (self.base.read_bytes(), self.installation.read_bytes()))
        prepared = json.loads(self.output.read_bytes())
        self.assertEqual(prepared["credentials"], self.settings["credentials"])
        self.assertEqual(prepared["providers"]["http"], self.settings["providers"]["http"])
        self.assertEqual(prepared["providers"]["bindings"][:-1], self.settings["providers"]["bindings"])
        self.assertEqual(prepared["capabilityPolicies"], self.settings["capabilityPolicies"])
        self.assertEqual(prepared["providers"]["outboundStreams"], self.record["installation"])
        self.assertEqual(result["nodeBinary"], {"sha256": stream.digest(self.node.read_bytes()),
                                                "size": self.node.stat().st_size})
        self.assertFalse(result["executionPermission"])
        self.assertEqual(result["providerReadiness"], "not-observed")
        self.assertNotIn("PRIVATE-", json.dumps(result))
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_existing_output_and_missing_opt_in_refuse_before_subprocess_or_write(self):
        with patch("tools.dev_workflow.process.run") as run:
            with self.assertRaisesRegex(DevError, "development-profile-required"):
                self.prepare()
            self.assertFalse(self.output.exists())
            paths.write_new(self.output, b"ORIGINAL-OWNER-INPUT")
            with self.assertRaisesRegex(DevError, "output-not-new"):
                self.prepare(development_profile=True)
        run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"ORIGINAL-OWNER-INPUT")

    def test_rejected_real_node_check_retains_input_without_fallback_or_output_disclosure(self):
        response = subprocess.CompletedProcess([], 1, b"PRIVATE-NODE-DETAILS", b"PRIVATE-SECRET")
        with patch("tools.dev_workflow.process.run", return_value=response) as run:
            with self.assertRaisesRegex(DevError, "node-check-rejected-prepared-file-retained") as failure:
                self.prepare(development_profile=True)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(self.output.is_file())
        self.assertNotIn("PRIVATE", str(failure.exception))

    def test_changed_prepared_input_and_interrupted_check_never_become_accepted(self):
        def changed(*_args, **_kwargs):
            self.output.write_bytes(b"REPLACED")
            return subprocess.CompletedProcess([], 0, b"", b"")
        with patch("tools.dev_workflow.process.run", side_effect=changed):
            with self.assertRaisesRegex(DevError, "prepared-configuration-changed"):
                self.prepare(development_profile=True)
        self.output.unlink()
        with patch("tools.dev_workflow.process.run", side_effect=DevError("owned-process-command-deadline")) as run:
            with self.assertRaisesRegex(DevError, "owned-process-command-deadline"):
                self.prepare(development_profile=True)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(self.output.is_file())
        self.output.unlink()
        def replaced_node(*_args, **_kwargs):
            self.node.write_bytes(b"DIFFERENT-NODE")
            return subprocess.CompletedProcess([], 0, b"", b"")
        with patch("tools.dev_workflow.process.run", side_effect=replaced_node):
            with self.assertRaisesRegex(DevError, "node-binary-changed"):
                self.prepare(development_profile=True)

    def test_linked_and_malformed_private_inputs_fail_before_output_creation(self):
        linked = self.root / "linked.json"
        os.link(self.base, linked)
        with patch("tools.dev_workflow.process.run") as run:
            with self.assertRaisesRegex(DevError, "single-link-regular"):
                self.prepare(development_profile=True)
            linked.unlink()
            for field in ("budgetProfile", "audit", "capabilityPolicies", "providers"):
                selected = {**self.settings, field: "PRIVATE-MALFORMED-INPUT"}
                self.base.write_bytes(encode(selected))
                with self.assertRaises(DevError) as failure:
                    self.prepare(development_profile=True)
                self.assertNotIn("PRIVATE", str(failure.exception))
            self.assertFalse(self.output.exists())
        run.assert_not_called()

    def test_cli_prepare_requires_separate_explicit_arguments_and_redacts_process_output(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = ["prepare", "--node", str(self.node), "--base-config", str(self.base),
                     "--installation-record", str(self.installation), "--output", str(self.output),
                     "--development-profile"]
        response = subprocess.CompletedProcess([], 0, b"PRIVATE-CREDENTIAL", b"PRIVATE-PATH")
        with patch("tools.dev_workflow.process.run", return_value=response), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(stream.main(arguments), 0)
            self.assertEqual(stream.main(arguments + ["--client-config", str(self.base)]), 1)
        self.assertNotIn("PRIVATE", stdout.getvalue() + stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["result"]["providerReadiness"], "not-observed")
        self.assertEqual(json.loads(stderr.getvalue())["code"], "stream-operator-command-arguments")


    def frontend_source_archive(self, archive):
        from tools import build_dev_frontend as frontend
        frontend.helper(archive)
        if os.name == "nt":
            # helper.pyz is deliberately Linux-only. This archive is a source
            # fixture for the frozen frontend, whose normal Windows import
            # analysis already includes the maintained Windows path owner.
            with zipfile.ZipFile(archive, "a") as packaged:
                packaged.writestr("tools/dev_workflow/windows.py",
                                  (frontend.ROOT / "tools/dev_workflow/windows.py").read_bytes())

    def test_packaged_frontend_route_uses_canonical_schemas_outside_checkout_without_state(self):
        from tools import build_dev_frontend as frontend
        archive = self.root / "helper.pyz"
        self.frontend_source_archive(archive)
        with zipfile.ZipFile(archive) as packaged:
            for name in ("node-providers.schema.json", "outbound-stream-provider.schema.json"):
                self.assertEqual(packaged.read("tools/dev_workflow/data/schemas/" + name),
                                 (frontend.ROOT / "schemas" / name).read_bytes())
        # The selected process response is an explicit double; this observes
        # packaged routing/schema/protected-I/O, not a real latentd installation.
        code = ("import sys,subprocess; sys.path.insert(0,sys.argv.pop(1)); "
                "from tools.dev_workflow import process; "
                "process.run=lambda command,cwd,**kw: subprocess.CompletedProcess(command,0,b'PRIVATE',b'PRIVATE'); "
                "from tools.dev_workflow.cli import main; raise SystemExit(main(sys.argv[1:]))")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(archive),
            "stream-operator", "prepare", "--node", str(self.node), "--base-config", str(self.base),
            "--installation-record", str(self.installation), "--output", str(self.output), "--development-profile"],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(frontend.ROOT)},
            capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"PRIVATE", result.stdout)
        self.assertEqual(json.loads(result.stdout)["result"]["providerReadiness"], "not-observed")
        self.assertEqual(set(self.root.iterdir()), {self.base, self.installation, self.node, self.output, archive})

    def test_missing_packaged_schema_refuses_without_checkout_fallback_or_process_dispatch(self):
        from tools import build_dev_frontend as frontend
        original, altered = self.root / "original.pyz", self.root / "missing.pyz"
        self.frontend_source_archive(original)
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(altered, "w") as target:
            for name in source.namelist():
                if name != "tools/dev_workflow/data/schemas/outbound-stream-provider.schema.json":
                    target.writestr(name, source.read(name))
        code = ("import sys; sys.path.insert(0,sys.argv.pop(1)); "
                "from tools.dev_workflow import process; "
                "process.run=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('unexpected-dispatch')); "
                "from tools.dev_workflow.cli import main; raise SystemExit(main(sys.argv[1:]))")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(altered),
            "stream-operator", "prepare", "--node", str(self.node), "--base-config", str(self.base),
            "--installation-record", str(self.installation), "--output", str(self.output), "--development-profile"],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(frontend.ROOT)},
            capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)["code"], "stream-operator-schema-not-packaged")
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()

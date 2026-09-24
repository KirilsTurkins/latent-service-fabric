"""Outside-checkout source captures are not NativeAOT execution evidence."""
import json
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from tools import build_process, qualify_rust_capsules, wait_capsule_audit_idle as audit_idle
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create, validate
from tools.dotnet_guest.compiler import packages
from tools.build_dotnet_guest_capsules import NAMES, project
from tools.rust_capsule_project import TEMPLATES, snapshot
from tools.tests.test_build_process import _alive


class DotnetAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-dotnet-authoring-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def files(self):
        return snapshot(create(self.root / "project", "greeting"))

    def test_all_templates_capture_actual_source_and_pinned_sdk(self):
        for name in TEMPLATES:
            files = snapshot(create(self.root / name, name))
            config, lock, _pins = validate(files)
            self.assertEqual(config["world"], f"examples:{name}/service@1.0.0")
            self.assertIn(b"class ApiExportsImpl", files["src/Main.cs"])
            self.assertIn(b"latent:clock/monotonic@0.1.0", files["wit/world.wit"])
            self.assertEqual(lock["language"], "dotnet")
            self.assertEqual(json.loads(files["global.json"])["sdk"]["version"], "10.0.100")

    def test_application_source_and_authoritative_wit_remain_editable(self):
        files = self.files()
        files["src/Main.cs"] += b"\n// an application change\n"
        files["wit/world.wit"] += b"\n// a contract change\n"
        validate(files)

    def test_sdk_capture_cannot_drift(self):
        files = self.files()
        files["vendor/lsf/sdk/dotnet-guest/ownership/Owner.cs"] += b"// drift\n"
        with self.assertRaisesRegex(ValueError, "vendored SDK changed"):
            validate(files)

    def test_application_cannot_inject_msbuild_or_package_overrides(self):
        original = self.files()
        for name in ["src/Directory.Build.props", "nuget.config", "packages.lock.json", "src/evil.csproj"]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "overrides"):
                validate({**original, name: b"<Project/>"})

    def test_compiler_configuration_is_closed(self):
        files = self.files()
        for name in ["Capsule.csproj", "global.json"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate({**files, name: files[name] + b" "})

    def test_names_and_existing_directories_are_rejected(self):
        for name in ["../escape", "", "Upper", "x;cmd", "x" * 65]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                create(self.root / "invalid", "greeting", name)
        create(self.root / "existing", "greeting")
        with self.assertRaises((ValueError, FileExistsError)):
            create(self.root / "existing", "greeting")

    def test_budgets_reject_overflow_boolean_and_zero_required_dimensions(self):
        files = self.files()
        original = json.loads(files["capsule-project.json"])
        for value in [-1, 2**64, True, 0]:
            config = {**original, "limits": {**original["limits"], "cpuFuel": value}}
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({**files, "capsule-project.json": json.dumps(config).encode()})

    def test_all_real_sdk_sources_use_the_same_capture_path(self):
        for name in NAMES:
            config, _, _ = validate(snapshot(project(self.root / name, name)))
            self.assertEqual(config["tenant"], None if name in {"service", "callee"} else "tests")
            self.assertEqual(config["limits"]["cpuFuel"], 10_000_000_000)
            self.assertEqual(config["limits"]["memoryBytes"], (256 if name == "service" else 128) * 1024 * 1024)

    def test_nuget_uses_verified_content_identity_not_raw_signed_zip_hash(self):
        directory = self.root / "packages/test/1.0.0"
        directory.mkdir(parents=True)
        archive = directory / "test.1.0.0.nupkg"
        archive.write_bytes(b"synthetic archive; no compiler authority")
        lock = {"dependencies": {"net10.0": {"Test": {"resolved": "1.0.0", "contentHash": "verified-content"}}}}
        seen = []
        def verified(path):
            seen.append(path)
            return "verified-content"
        self.assertEqual(packages(lock, self.root / "packages", verified), {"nuget/test/1.0.0": directory})
        self.assertEqual(seen, [archive])
        with self.assertRaisesRegex(ValueError, "content hash differs"):
            packages(lock, self.root / "packages", lambda _: "different")

    def test_public_contract_rejection_precedes_compiler_work(self):
        source = create(self.root / "unsupported", "greeting")
        output = self.root / "output"
        tool = self.root / "contracts-tool"
        tool.write_bytes(b"synthetic tool identity; never executed")
        with patch("tools.dotnet_guest.build.Commands") as commands, \
                patch("tools.dotnet_guest.build.Compiler") as compiler:
            commands.return_value.records = []
            commands.return_value.run.side_effect = ValueError("unsupported-public-resource")
            with self.assertRaisesRegex(ValueError, "unsupported-public-resource"):
                build(source, output, tool, tool,
                      "https://github.com/KirilsTurkins/latent-service-fabric",
                      tools=self.root / "compiler")
            compiler.assert_not_called()
            self.assertEqual(commands.return_value.run.call_args.args[0], "contracts")
        receipt = json.loads((output / "BUILD-FAILED.json").read_text())
        self.assertEqual(receipt["stage"], "contracts")
        self.assertFalse((output / "component.wasm").exists())
        self.assertFalse((output / "BUILD-COMPLETE.json").exists())


class AuditDrainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-audit-drain-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "client.json"
        self.config.write_text("{}")
        self.cli = Path(sys.executable)

    def response(self, **counters):
        return {"schemaVersion": "latent.cli.result.v1", "command": "capability list",
                "category": "success", "outcomeKnown": True, "requestDispatched": True, "error": None,
                "data": {"nextPageToken": None, "nodeUsage": {"scope": "node", "unavailable": [],
                    "counters": {**dict.fromkeys((*audit_idle.COUNTERS, *audit_idle.STATES), "0"), **counters}}}}

    def raw(self, **counters):
        return json.dumps(self.response(**counters)).encode()

    def read(self, **counters):
        return subprocess.CompletedProcess([], 0, self.raw(**counters), b"")

    def wait(self, **kwargs):
        return audit_idle.wait(self.cli, self.config, "my-greeting", **kwargs)

    def assert_read_only(self, argv, options):
        self.assertEqual(argv[:6], [str(self.cli.resolve()), "--config", str(self.config.resolve()),
                                  "--output", "json", "--rpc-timeout-ms"])
        self.assertTrue(0 < int(argv[6]) <= 750)
        self.assertEqual(argv[7:], ["capability", "list", "--deployment", "my-greeting", "--include-node-usage"])
        self.assertEqual(options["cwd"], self.config.parent)
        self.assertEqual(options["max_output_bytes"], 65536)
        self.assertTrue(0 < options["timeout_seconds"] <= 1)

    def test_busy_to_idle_observations_are_only_bounded_read_only_calls(self):
        with patch.object(audit_idle, "run_bounded", side_effect=[
                self.read(audit_reserved_records="2", audit_queued_bytes="32768"),
                self.read(audit_queued_bytes="16384"), self.read()]) as run:
            result = self.wait()
        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["observations"], 3)
        self.assertEqual(result["counters"], dict.fromkeys((*audit_idle.COUNTERS, *audit_idle.STATES), 0))
        for call in run.call_args_list:
            self.assert_read_only(call.args[0], call.kwargs)

    def test_every_owner_counter_must_be_present_and_zero_before_idle(self):
        for name in audit_idle.COUNTERS:
            with self.subTest(counter=name), patch.object(audit_idle, "run_bounded", side_effect=[
                    self.read(**{name: "1"}), self.read()]) as run:
                self.assertEqual(self.wait()["observations"], 2)
                self.assertEqual(run.call_count, 2)
        for name in (*audit_idle.COUNTERS, *audit_idle.STATES):
            value = self.response()
            del value["data"]["nodeUsage"]["counters"][name]
            with self.subTest(missing=name), self.assertRaisesRegex(audit_idle.AuditDrainError, "missing-counter"):
                audit_idle.counters(json.dumps(value).encode())

    def test_missing_audit_owner_closed_and_recovery_states_fail_closed(self):
        for name in audit_idle.STATES:
            with self.subTest(state=name), self.assertRaises(audit_idle.AuditDrainError):
                audit_idle.counters(self.raw(**{name: "1"}))
        for unavailable in [None, "", ["audit-owner-not-configured"], ["unrecognized"], [0]]:
            value = self.response()
            value["data"]["nodeUsage"]["unavailable"] = unavailable
            with self.subTest(unavailable=unavailable), self.assertRaisesRegex(audit_idle.AuditDrainError, "unavailable"):
                audit_idle.counters(json.dumps(value).encode())
        value = self.response()
        value["data"]["nodeUsage"]["unavailable"] = sorted(audit_idle.UNRELATED_UNAVAILABLE)
        self.assertEqual(audit_idle.counters(json.dumps(value).encode()),
                         dict.fromkeys((*audit_idle.COUNTERS, *audit_idle.STATES), 0))

    def test_counter_values_reject_malformed_numbers_and_unsigned_overflow(self):
        for value in [True, 0, -1, 0.5, "-1", "+1", "01", " 0", "1.0", str(2**64), "1" * 40, None]:
            with self.subTest(value=value), self.assertRaises(audit_idle.AuditDrainError):
                audit_idle.counters(self.raw(audit_queued_bytes=value))
        self.assertEqual(audit_idle.counters(self.raw(audit_queued_bytes=str(2**64 - 1)))["audit_queued_bytes"],
                         2**64 - 1)

    def test_malformed_paginated_ambiguous_and_unbounded_responses_are_rejected(self):
        invalid = [b"{", b"\xff", b"[]", b"{\"key\":0,\"key\":0}", b"NaN", b"0.0",
                   b" " * (audit_idle.MAX_OUTPUT_BYTES + 1)]
        for field, value in [("outcomeKnown", False), ("requestDispatched", False),
                             ("category", "platform-failure"), ("command", "deployment delete")]:
            response = self.response()
            response[field] = value
            invalid.append(json.dumps(response).encode())
        for field, value in [("nodeUsage", None), ("nextPageToken", "more")]:
            response = self.response()
            response["data"][field] = value
            invalid.append(json.dumps(response).encode())
        for raw in invalid:
            with self.subTest(shape=raw[:24]), self.assertRaises(audit_idle.AuditDrainError):
                audit_idle.counters(raw)

    def test_invalid_bounds_and_identifiers_do_not_spawn(self):
        with patch.object(audit_idle, "run_bounded") as run:
            for value in [0, -1, True, float("nan"), float("inf"), 6, 10**1000]:
                with self.assertRaises(audit_idle.AuditDrainError):
                    self.wait(timeout_seconds=value)
            for name in ["", "../secret", "--delete", "x" * 65]:
                with self.assertRaises(audit_idle.AuditDrainError):
                    audit_idle.wait(self.cli, self.config, name)
            run.assert_not_called()

    def test_observation_limit_and_deadline_stop_without_effect_retries(self):
        with patch.object(audit_idle, "run_bounded", return_value=self.read(audit_queued_bytes="1")) as run, \
                patch.object(audit_idle.time, "monotonic", return_value=0), \
                patch.object(audit_idle.time, "sleep"):
            with self.assertRaisesRegex(audit_idle.AuditDrainError, "observation-limit"):
                self.wait()
            self.assertEqual(run.call_count, 32)
        for ticks, calls in [([0, 6], 0), ([0, 0, 6], 1), ([0, 0, 0, 6], 1)]:
            with patch.object(audit_idle, "run_bounded", return_value=self.read()) as run, \
                    patch.object(audit_idle.time, "monotonic", side_effect=ticks):
                with self.assertRaisesRegex(audit_idle.AuditDrainError, "deadline"):
                    self.wait()
                self.assertEqual(run.call_count, calls)

    def test_failed_read_stops_once_and_cli_failure_discards_private_response(self):
        with patch.object(audit_idle, "run_bounded", side_effect=build_process.BuildProcessError("command-exit")) as run:
            with self.assertRaisesRegex(build_process.BuildProcessError, "command-exit"):
                self.wait()
            self.assertEqual(run.call_count, 1)
        with patch.object(audit_idle, "run_bounded", return_value=subprocess.CompletedProcess([], 0, b"PRIVATE", b"")), \
                patch("sys.stdout", new_callable=io.StringIO) as output, \
                patch("sys.stderr", new_callable=io.StringIO) as error:
            status = audit_idle.main(["--cli", str(self.cli), "--config", str(self.config), "--deployment", "my-greeting"])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(error.getvalue(), "Audit drain failed: audit-observation-invalid-json\n")

    def test_real_process_deadline_and_output_overflow_retire_owned_process(self):
        factory = build_process._new_owner
        for code, timeout, reason in [("import time; time.sleep(30)", 0.2, "command-deadline"),
                                      ("import os; os.write(1,b'x'*65537)", 5, "command-output-limit")]:
            owners = []
            def owner():
                value = factory()
                owners.append(value)
                return value
            def execute(argv, **options):
                self.assert_read_only(argv, options)
                return build_process.run_bounded([sys.executable, "-c", code], **options)
            started = time.monotonic()
            with self.subTest(reason=reason), patch.object(build_process, "_new_owner", owner), \
                    patch.object(audit_idle, "run_bounded", side_effect=execute) as run:
                with self.assertRaisesRegex(build_process.BuildProcessError, "^" + reason + "$"):
                    self.wait(timeout_seconds=timeout)
                self.assertEqual(run.call_count, 1)
            self.assertLess(time.monotonic() - started, timeout + 6)
            self.assertEqual(len(owners), 1)
            self.assertIsNotNone(owners[0].process.returncode)
            self.assertFalse(_alive(owners[0].process.pid))

    def test_helper_and_dependencies_are_captured_and_guide_deletes_only_once(self):
        with patch.object(qualify_rust_capsules, "source_identity", return_value={}), \
                patch.object(qualify_rust_capsules, "directory_identity", return_value={}), \
                patch.object(qualify_rust_capsules, "file_identity", return_value={}):
            helpers = qualify_rust_capsules.inputs("dotnet")["helpers"]
        self.assertTrue({"wait_capsule_audit_idle.py", "build_process.py", "build_process_linux.py",
                         "build_process_windows.py", "build_process_signals.py"}.issubset(helpers))
        source = (qualify_rust_capsules.ROOT / "docs/component-development/dotnet-authoring.md").read_text()
        blocks = re.findall(r"^```bash\n(.*?)^```$", source, re.M | re.S)
        self.assertEqual(len(blocks), 6)
        self.assertEqual(source.count("dotnet_cli deployment delete"), 1)
        self.assertLess(blocks[-1].index("tools/wait_capsule_audit_idle.py"), blocks[-1].index("dotnet_cli deployment delete"))


if __name__ == "__main__":
    unittest.main()

"""Source-bound build trust, one-shot operation recovery and qualification gates."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_workflow import assets, backend, bundle, common, effects, journal, paths, portable, project, qualification, scenarios, state, wsl


def descriptor():
    return {"schemaVersion": "latent.dev.project.v1", "name": "sample", "tenant": "examples", "service": "examples/sample",
            "language": "rust", "template": {"ownerIssue": 544, "revision": "a" * 40, "sha256": "sha256:" + "b" * 64},
            "hostAbi": common.HOST_ABI, "inputRoots": ["src"], "exclude": [],
            "build": {"argv": ["cargo", "build", "--locked"], "workingDirectory": "src", "outputRoot": "output",
                      "tools": [{"name": "cargo", "path": "bin/cargo", "version": "1.97.1", "sha256": "sha256:" + "c" * 64}],
                      "target": "wasm-component", "hostTargets": ["linux-x86_64"], "timeoutSeconds": 300, "maximumOutputBytes": 4096},
            "artifacts": {"component": "output/capsule.wasm", "capsule": "output/capsule.json", "contracts": "output/contracts.json",
                          "deployment": "output/deployment.json", "packageSource": "output/package-source.json",
                          "packageRoot": "output/package"}, "scenarios": ["src/tests.json"]}


class Projects(unittest.TestCase):
    def test_six_owner_mapping_and_compiler_host_boundary(self):
        for language, owner in project.LANGUAGES.items():
            value = descriptor()
            value.update(language=language)
            value["template"]["ownerIssue"] = owner
            project.validate(value)
            value["build"]["hostTargets"] = ["linux-aarch64"]
            with self.assertRaisesRegex(common.DevError, "unsupported"):
                project.validate(value)

    def test_recipe_and_tool_changes_invalidate_trust(self):
        value = descriptor()
        before = project.trust_identity(value)
        value["build"]["argv"].append("--release")
        self.assertNotEqual(before, project.trust_identity(value))
        before = project.trust_identity(value)
        value["build"]["tools"][0]["sha256"] = "sha256:" + "d" * 64
        self.assertNotEqual(before, project.trust_identity(value))

    def test_descriptor_rejects_unknown_fields_abi_and_output_loops(self):
        values = [dict(descriptor(), unknown=True), dict(descriptor(), hostAbi="older")]
        loop = descriptor()
        loop["build"]["outputRoot"] = "src/output"
        values.append(loop)
        for value in values:
            with self.assertRaises(common.DevError):
                project.validate(value)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.journal = journal.Journal(self.root, "node-a", "tenant-a")

    def test_lost_response_restart_looks_up_original_id_without_replay(self):
        calls = []
        def lost(operation):
            calls.append(operation)
            raise OSError("response lost after commit")
        with self.assertRaises(OSError):
            self.journal.execute("deployment", {"expectedGeneration": "1", "expectedStateVersion": "2"}, lost)
        restarted = journal.Journal(self.root, "node-a", "tenant-a")
        with self.assertRaisesRegex(common.DevError, "recover-original"):
            restarted.execute("deployment", {}, lost)
        lookups = []
        def lookup(kind, operation):
            lookups.append((kind, operation))
            return {"category": "success", "outcomeKnown": True, "data": {
                "disposition": "DEPLOYMENT_OPERATION_LOOKUP_DISPOSITION_FOUND", "receipt": {
                    "operationId": operation, "tenant": "tenant-a", "expectedGeneration": "1", "expectedStateVersion": "2"}}}
        restarted.recover(lookup)
        self.assertEqual(calls, [lookups[0][1]])
        self.assertIsNone(restarted.read()["pending"])

    def test_unknown_expired_wrong_tenant_and_conflicts_never_release_intent(self):
        intent = self.journal.begin("release", {"expectedGeneration": "0"})
        for data in ({"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_UNKNOWN", "receipt": None},
                     {"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_UNCERTAIN", "receipt": None},
                     {"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND", "receipt": {
                         "operationId": intent["id"], "tenant": "other", "expectedGeneration": "0"}},
                     {"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND", "receipt": {
                         "operationId": intent["id"], "tenant": "tenant-a", "expectedGeneration": "9"}}):
            with self.assertRaises(common.DevError):
                self.journal.recover(lambda *_: {"outcomeKnown": True, "category": "success", "data": data})
            self.assertEqual(self.journal.read()["pending"], intent)

    def test_bounded_history_and_no_cross_workspace_identity(self):
        for _ in range(40):
            self.journal.execute("invoke", {}, lambda _: {"category": "success", "outcomeKnown": True, "data": {}})
        self.assertEqual(len(self.journal.read()["history"]), journal.MAX_HISTORY)
        with self.assertRaisesRegex(common.DevError, "owner-mismatch"):
            journal.Journal(self.root, "different-node", "tenant-a").read()

    def test_large_invocation_result_does_not_overflow_durable_history(self):
        result = {"category": "success", "outcomeKnown": True, "data": {"payload": "x" * 200000}}
        self.assertEqual(self.journal.execute("invoke", {}, lambda _: result), result)
        self.assertLess((self.root / "operations.json").stat().st_size, 2048)

    def test_crash_after_local_publication_write_recovers_original_without_republish(self):
        controller = journal.Journal(self.root, "node-a", "tenant-a",
            settle=lambda operation, result: effects.settle(self.root, operation, result))
        intent = {"source": "sha256:" + "a" * 64, "componentDigest": "sha256:" + "b" * 64, "expectedGeneration": "0"}
        calls, receipts = [], []
        def publish(operation):
            calls.append(operation)
            receipt = {"operationId": operation, "tenant": "tenant-a", "expectedGeneration": "0",
                "componentDigest": intent["componentDigest"], "publication": {"id": "test-publication", "tenant": "tenant-a"},
                "disposition": "RELEASE_OPERATION_DISPOSITION_COMMITTED"}
            receipts.append(receipt)
            return {"category": "success", "outcomeKnown": True, "data": {"operation": receipt}}
        original = state.atomic
        def crash(root, name, value):
            if name == "operations.json" and value["pending"] is None:
                raise OSError("controller interrupted before final journal write")
            original(root, name, value)
        with patch.object(state, "atomic", crash), self.assertRaises(OSError):
            controller.execute("release", intent, publish)
        saved = state.load(self.root, "last-publication.json")
        self.assertEqual(saved["operation"], calls[0])
        controller.recover(lambda kind, operation: {"category": "success", "outcomeKnown": True,
            "data": {"lookup": "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND", "receipt": receipts[0]}})
        self.assertEqual(len(calls), 1)
        self.assertEqual(state.load(self.root, "last-publication.json"), saved)
        self.assertIsNone(controller.read()["pending"])

    def test_recovered_deployment_cannot_change_selected_publication_or_generation(self):
        controller = journal.Journal(self.root, "node-a", "tenant-a",
            settle=lambda operation, result: effects.settle(self.root, operation, result))
        intent = {"source": "sha256:" + "a" * 64, "componentDigest": "sha256:" + "b" * 64,
            "deployment": "sample", "publication": "selected", "expectedGeneration": "1", "expectedStateVersion": "2"}
        operation = controller.begin("deployment", intent)
        receipt = {"operationId": operation["id"], "tenant": "tenant-a", "expectedGeneration": "1",
            "expectedStateVersion": "2", "componentDigest": intent["componentDigest"], "deploymentId": "sample",
            "publication": {"id": "other", "tenant": "tenant-a"}, "objectGeneration": "2"}
        result = {"category": "success", "outcomeKnown": True, "data": {
            "disposition": "DEPLOYMENT_OPERATION_LOOKUP_DISPOSITION_FOUND", "receipt": receipt,
            "durability": "DEPLOYMENT_DURABILITY_CONFIRMED"}}
        with self.assertRaises(common.DevError):
            controller.recover(lambda *_: result)
        self.assertIsNotNone(controller.read()["pending"])
        receipt["publication"]["id"] = "selected"
        controller.recover(lambda *_: result)
        self.assertEqual(state.load(self.root, "last-deployment.json")["generation"], "2")


class Transports(unittest.TestCase):
    def test_ssh_identity_options_and_constant_command(self):
        config = {"kind": "ssh", "helperSha256": "sha256:" + "a" * 64, "host": "node.example", "port": 22,
                  "user": "developer", "ssh": str(Path("ssh").absolute()),
                  "identityFile": str(Path("explicit key").absolute()), "knownHosts": str(Path("known hosts").absolute())}
        command = backend.command(config)
        for required in ("StrictHostKeyChecking=yes", "BatchMode=yes", "IdentitiesOnly=yes", "ForwardAgent=no", "ProxyCommand=none"):
            self.assertIn(required, command)
        import shlex
        remote = shlex.split(command[-1])
        self.assertEqual(remote[:3], ["/usr/local/bin/python3.13", "-I", "-c"])
        self.assertEqual(remote[-3:], ["/opt/latent-dev/helper.pyz", config["helperSha256"], "rpc"])
        self.assertIn("hashlib.file_digest", remote[3])
        with self.assertRaises(common.DevError):
            backend.command({**config, "host": "node;do-bad-things"})

    def test_helper_digest_is_checked_before_hello(self):
        import subprocess
        config = {"kind": "linux", "python": str(Path("python").absolute()), "helper": str(Path("helper.pyz").absolute()),
                  "helperSha256": "sha256:" + "c" * 64}
        with patch.object(backend, "command", return_value=["wsl-test"]), patch.object(backend.process, "run",
              return_value=subprocess.CompletedProcess([], 126, b"", b"")) as run:
            with self.assertRaisesRegex(common.DevError, "identity-mismatch"):
                backend.Backend(config, "test", Path.cwd()).call("hello", {})
            self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(sys.platform == "linux", "Linux verified descriptor execution")
    def test_actual_helper_digest_and_parent_checks_precede_execution(self):
        import zipfile
        from tools.dev_workflow import process
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "helper.pyz"
            with zipfile.ZipFile(executable, "w") as archive:
                archive.writestr("tools/__init__.py", "")
                archive.writestr("tools/dev_workflow/__init__.py", "")
                archive.writestr("tools/dev_workflow/helper.py",
                                 "def main():\n import proof,sys; print(proof.answer); print(sys.argv[0])\n return 0\n")
                archive.writestr("proof.py", "answer='executed-verified-bytes'")
            identity = common.digest(executable.read_bytes())
            argv = backend.guest_command(sys.executable, str(executable), identity, "rpc")
            completed = process.run(argv, root)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout.decode().splitlines(), ["executed-verified-bytes", str(executable)])
            with executable.open("ab") as stream:
                stream.write(b"changed")
            rejected = process.run(argv, root)
            self.assertEqual(rejected.returncode, 126)
            self.assertEqual(rejected.stdout, b"")
            identity = common.digest(executable.read_bytes())
            unsafe = root / "alias"
            unsafe.symlink_to(root, target_is_directory=True)
            rejected = process.run(backend.guest_command(sys.executable, str(unsafe / executable.name), identity, "rpc"), root)
            self.assertEqual(rejected.returncode, 126)
            self.assertEqual(rejected.stdout, b"")


class OfflineInputs(unittest.TestCase):
    def test_manifest_rejects_oversized_aliases_and_paths(self):
        for names in (("release/A", "release/a"), ("trust/../escape",), ("unrelated/input",)):
            files = [{"path": name, "size": 1, "sha256": common.digest(b"a"), "executable": False} for name in names]
            value = {"schemaVersion": "latent.dev.inputs.v1", "files": files}
            value["identity"] = common.digest(common.encode(value))
            with self.assertRaises(common.DevError):
                assets.manifest(value)

    @unittest.skipUnless(sys.platform == "linux", "Linux private input transfer")
    def test_transfer_replays_only_identical_bytes_and_rechecks_completed_cache(self):
        import base64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = b"first-second"
            value = {"schemaVersion": "latent.dev.inputs.v1", "files": [{"path": "trust/gh", "size": len(raw),
                "sha256": common.digest(raw), "executable": True}]}
            value["identity"] = common.digest(common.encode(value))
            assets.receive(root, "asset-begin", value)
            first = {"identity": value["identity"], "path": "trust/gh", "offset": 0,
                     "bytes": base64.b64encode(raw[:6]).decode()}
            assets.receive(root, "asset-chunk", first)
            self.assertEqual(assets.receive(root, "asset-chunk", first)["offset"], 6)
            with self.assertRaisesRegex(common.DevError, "conflicting-replay"):
                assets.receive(root, "asset-chunk", {**first, "bytes": base64.b64encode(b"wrong!").decode()})
            with self.assertRaisesRegex(common.DevError, "chunk-gap"):
                assets.receive(root, "asset-chunk", {**first, "offset": 7, "bytes": "YQ=="})
            with self.assertRaisesRegex(common.DevError, "content-mismatch"):
                assets.receive(root, "asset-finish", {"identity": value["identity"]})
            assets.receive(root, "asset-chunk", {**first, "offset": 6, "bytes": base64.b64encode(raw[6:]).decode()})
            result = assets.receive(root, "asset-finish", {"identity": value["identity"]})
            path = Path(result["directory"]) / "trust/gh"
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(common.DevError, "content-mismatch"):
                assets.receive(root, "asset-finish", {"identity": value["identity"]})


class WslOwnership(unittest.TestCase):
    def test_recovery_observes_original_registration_and_user_nonce_without_reimport(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            distribution = "LSF-Dev-" + "a" * 16
            identity = {"workspace": "test-a", "user": "lsfd-" + "b" * 12,
                        "helperSha256": "sha256:" + "c" * 64, "nonce": "d" * 32}
            record = {"schemaVersion": "latent.dev.wsl.v1", "distribution": distribution,
                "directory": str(root / distribution), "helperSha256": identity["helperSha256"],
                "state": "provisioning", "registration": None,
                "workspaces": {"test-a": {"owner": identity, "state": "creating"}}}
            state.atomic(root, "wsl.json", record)
            registration = {distribution: {"path": str(root / distribution), "version": 2, "registration": "original"}}
            with patch.object(wsl, "registrations", return_value=registration), patch.object(wsl, "_user_call",
                return_value={"user": identity["user"], "state": "ready"}) as user_call, patch.object(wsl.process, "run") as external:
                result = wsl.recover(root, distribution)
                self.assertEqual(result["state"], "provisioned")
                self.assertEqual(user_call.call_args.args[2:], ("user-status", identity))
                external.assert_not_called()
                config = {"kind": "wsl2", "distribution": distribution, "user": identity["user"], "helperSha256": identity["helperSha256"]}
                wsl.verify_workspace(root, "test-a", config)
                registration[distribution]["registration"] = "replacement"
                with self.assertRaisesRegex(common.DevError, "registration-replaced"):
                    wsl.verify_workspace(root, "test-a", config)
                with self.assertRaises(common.DevError):
                    wsl.purge(root, "docker-desktop")
                external.assert_not_called()


class EditorDiagnostics(unittest.TestCase):
    def test_crlf_unicode_locations_match_host_files_and_ignore_outside_inputs(self):
        from tools.dev_workflow import diagnostics, editor
        import re
        with tempfile.TemporaryDirectory(prefix="lsf spaces-") as temporary:
            root = Path(temporary)
            working = root / "src"
            inputs = {"src/Grüße.rs", "src/business.cs"}
            rust = {"reason": "compiler-message", "message": {"level": "error", "message": "wrong type\nsecond line",
                "code": {"code": "E0308"}, "spans": [{"file_name": "Grüße.rs", "line_start": 12, "column_start": 3, "is_primary": True}]}}
            output = ("\x1b[31mbusiness.cs(7,2): error CS1002: expected semicolon\x1b[0m\r\n"
                      "../../secret.rs:1:1: error: unrelated\r\n" + json.dumps(rust, ensure_ascii=False) + "\r\n").encode()
            records = diagnostics.collect(b"", output, root, working, inputs)
            self.assertEqual([(record["path"], record["line"], record["column"]) for record in records],
                             [("src/business.cs", 7, 2), ("src/Grüße.rs", 12, 3)])
            for record, line in zip(records, diagnostics.editor_lines(diagnostics.for_host(records, root))):
                match = re.fullmatch(editor.PATTERN, line)
                self.assertIsNotNone(match)
                self.assertEqual(match[1], str(root / record["path"]))
                self.assertNotIn("\x1b", line)
                self.assertNotIn("\r", line)

    def test_process_tasks_do_not_start_automatically_or_replace_editor_configuration(self):
        from tools.dev_workflow import editor
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = root / "frontend with spaces.exe"
            paths.write_new(frontend, b"fixture-never-executed")
            value = editor.configuration(frontend, root, "test-a", "/home/guest/tools with spaces;literal")
            for task in value["tasks"]:
                self.assertEqual(task["type"], "process")
                self.assertEqual(task["command"], str(frontend))
                self.assertEqual(task["runOptions"]["runOn"], "default")
                self.assertNotIn("dependsOn", task)
            self.assertIn("/home/guest/tools with spaces;literal", next(task for task in value["tasks"] if task["label"] == "LSF: build")["args"])
            editor.generate(root, frontend, root, "test-a", None)
            before = (root / ".vscode/tasks.json").read_bytes()
            with self.assertRaisesRegex(common.DevError, "existing-editor-tasks-preserved"):
                editor.generate(root, frontend, root, "test-a", None)
            self.assertEqual((root / ".vscode/tasks.json").read_bytes(), before)

    def test_real_failed_compiler_preserves_last_build_and_maps_diagnostics(self):
        from tools.dev_workflow import build, snapshot
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            controller, source = directory / "controller", directory / "source"
            paths.new_directory(controller)
            paths.new_directory(source)
            paths.new_directory(source / "src")
            paths.write_new(source / "src/fail.py", b"import sys\nprint('fail.py:7:2: error E100: controlled failure', file=sys.stderr)\nsys.exit(1)\n")
            selected = descriptor()
            executable = Path(sys.executable).resolve()
            selected["build"].update(argv=["python", "-I", "fail.py"], hostTargets=["windows-x86_64", "linux-x86_64"],
                tools=[{"name": "python", "path": executable.name, "version": "3.13.5",
                        "sha256": paths.digest_file(executable.parent, executable.name, 268435456)[0]}])
            record, _content = snapshot.observe(source, ["src"])
            paths.write_new(source / "snapshot.json", common.encode(record))
            accepted = {"sourceDirectory": "previous-accepted", "receipt": {"source": "previous"}}
            state.atomic(controller, "last-build.json", accepted)
            with self.assertRaises(common.DevError) as failure:
                build.execute(controller, source, selected, executable.parent,
                              trusted=project.trust_identity(selected), cli=executable)
            self.assertEqual(failure.exception.code, "guest-build-failed-last-deployment-retained")
            self.assertEqual(failure.exception.diagnostics[0]["path"], "src/fail.py")
            self.assertEqual(failure.exception.diagnostics[0]["line"], 7)
            self.assertEqual(state.load(controller, "last-build.json"), accepted)


class ScenarioReports(unittest.TestCase):
    def test_portable_fixture_identity_and_kind_are_checked_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = common.encode({"entropy": "AQID"})
            paths.write_new(root / "fixture.json", raw)
            fixture = {"id": "entropy", "kind": "test-adapter", "identity": common.digest(raw), "configuration": "fixture.json"}
            self.assertEqual(portable.fixture_inputs(root, [fixture]), {"entropy": "AQID"})
            with self.assertRaisesRegex(common.DevError, "fixture-identity"):
                portable.fixture_inputs(root, [{**fixture, "identity": "sha256:" + "0" * 64}])
            with self.assertRaisesRegex(common.DevError, "fixture-kind"):
                portable.fixture_inputs(root, [{**fixture, "kind": "controlled-peer"}])
            with self.assertRaisesRegex(common.DevError, "duplicate-portable"):
                portable.fixture_inputs(root, [fixture, fixture])
            self.assertIsNone(portable.fixture_inputs(root, [{"id": "external", "kind": "real-provider", "identity": "external"}]))

    def test_portable_required_linux_checks_fail_without_invoking(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths.write_new(root / "input.json", b'["18446744073709551615"]')
            document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [{
                "id": "retained-deployment", "service": "examples/echo", "contract": "examples:echo/api@0.1.0",
                "function": "echo", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success"}, "requires": ["restart"], "timeoutMillis": 1000, "required": True, "fixtures": []}]}
            calls = []
            report = scenarios.run(document, root, "portable", [], lambda *_: calls.append(1), {}, supported={"restart"})
            self.assertFalse(report["passed"])
            self.assertFalse(calls)
            self.assertIn(b'<failure message="unsupported"', scenarios.junit(report))

    def test_missing_qualification_never_passes(self):
        with self.assertRaisesRegex(common.DevError, "receipts-missing"):
            qualification.validate({"schemaVersion": "latent.dev.qualification.v1", "scope": "windows-only",
                "sourceCommit": "a" * 40, "receipts": [], "failedAttempts": [], "newcomerReview": "executed-and-reviewed"})

    def test_arbitrary_candidate_policy_is_not_runtime_release_approval(self):
        policy = {"schemaVersion": "latent.native-publisher-policy.v1", "repository": "KirilsTurkins/latent-service-fabric",
                  "workflow": bundle.WORKFLOW, "sourceRef": "refs/heads/feat/example", "sourceCommit": "a" * 40,
                  "version": "0.1.0-alpha.4", "purpose": "candidate"}
        with self.assertRaises(common.DevError):
            bundle.policy(policy, "0.1.0-alpha.4", allow_candidate=False)
        bundle.policy(policy, "0.1.0-alpha.4", allow_candidate=True)
        for replacement in ({"purpose": "release"}, {"sourceCommit": "development"}, {"workflow": "unreviewed.yml"}):
            with self.assertRaises(common.DevError):
                bundle.policy({**policy, **replacement}, "0.1.0-alpha.4", allow_candidate=True)


if __name__ == "__main__":
    unittest.main()

"""Source-bound build trust, one-shot operation recovery and qualification gates."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_workflow import backend, bundle, common, journal, paths, project, qualification, scenarios


def descriptor():
    return {"schemaVersion": "latent.dev.project.v1", "name": "sample", "tenant": "examples", "service": "examples/sample",
            "language": "rust", "template": {"ownerIssue": 544, "revision": "a" * 40, "sha256": "sha256:" + "b" * 64},
            "hostAbi": common.HOST_ABI, "inputRoots": ["src"], "exclude": [],
            "build": {"argv": ["cargo", "build", "--locked"], "workingDirectory": "src", "outputRoot": "output",
                      "tools": [{"name": "cargo", "path": "bin/cargo", "version": "1.97.1", "sha256": "sha256:" + "c" * 64}],
                      "target": "wasm-component", "hostTargets": ["linux-x86_64"], "timeoutSeconds": 300, "maximumOutputBytes": 4096},
            "artifacts": {"component": "output/capsule.wasm", "capsule": "output/capsule.json", "contracts": "output/contracts.json",
                          "deployment": "output/deployment.json"}, "scenarios": ["src/tests.json"]}


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


class Transports(unittest.TestCase):
    def test_ssh_identity_options_and_constant_command(self):
        config = {"kind": "ssh", "helperSha256": "sha256:" + "a" * 64, "host": "node.example", "port": 22,
                  "user": "developer", "ssh": str(Path("ssh").absolute()),
                  "identityFile": str(Path("explicit key").absolute()), "knownHosts": str(Path("known hosts").absolute())}
        command = backend.command(config)
        for required in ("StrictHostKeyChecking=yes", "BatchMode=yes", "IdentitiesOnly=yes", "ForwardAgent=no", "ProxyCommand=none"):
            self.assertIn(required, command)
        self.assertEqual(command[-1], "/usr/bin/python3 -I /opt/latent-dev/helper.pyz rpc")
        with self.assertRaises(common.DevError):
            backend.command({**config, "host": "node;do-bad-things"})

    def test_helper_digest_is_checked_before_hello(self):
        import subprocess
        config = {"kind": "wsl2", "distribution": "LSF-Dev-" + "a" * 16, "user": "lsfd-" + "b" * 12,
                  "helperSha256": "sha256:" + "c" * 64}
        with patch.object(backend, "command", return_value=["wsl-test"]), patch.object(backend.process, "run",
              return_value=subprocess.CompletedProcess([], 0, b"wrong digest", b"")) as run:
            with self.assertRaisesRegex(common.DevError, "identity-mismatch"):
                backend.Backend(config, "test", Path.cwd()).call("hello", {})
            self.assertEqual(run.call_count, 1)


class ScenarioReports(unittest.TestCase):
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

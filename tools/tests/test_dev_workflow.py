"""Security and ownership regressions for the standalone development controller."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_workflow import common, paths, process, protocol, snapshot, state


class Documents(unittest.TestCase):
    def test_duplicate_and_unknown_fields_are_rejected(self):
        with self.assertRaisesRegex(common.DevError, "duplicate"):
            common.decode(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(common.DevError, "unknown"):
            common.members({"a": 1, "execute": "bad"}, {"a"})

    def test_protocol_target_abi_and_response_association(self):
        hello = {**protocol.hello(), "os": "linux", "architecture": "x86_64"}
        protocol.negotiate(hello)
        for changed in ({"hostAbi": "old"}, {"architecture": "aarch64"}, {"features": []}, {"python": "3.12.3"}):
            with self.assertRaises(common.DevError):
                protocol.negotiate({**hello, **changed})
        request = protocol.request("status", "workspace", {})
        response = protocol.response(request, {"state": "stopped"})
        self.assertEqual(protocol.result(response, request), {"state": "stopped"})
        with self.assertRaises(common.DevError):
            protocol.result(response, {**request, "requestId": "0" * 32})

    def test_unknown_remote_outcome_is_not_success(self):
        request = protocol.request("up", "workspace", {})
        with self.assertRaises(common.DevError) as result:
            protocol.result(protocol.response(request, {}, code="transport-lost", uncertain=True), request)
        self.assertTrue(result.exception.uncertain)


class SourceSnapshots(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def write(self, name, raw=b"source\r\n"):
        (self.root / name).parent.mkdir(exist_ok=True, parents=True)
        (self.root / name).write_bytes(raw)

    def test_exact_bytes_unicode_spaces_exclusions_and_deletions(self):
        self.write("src/hello caf\u00e9.txt")
        self.write("src/.env", b"must-not-transfer")
        self.write("src/.git/config", b"must-not-transfer")
        self.write("src/output/file", b"generated")
        self.write("src/deleted.txt")
        first, content = snapshot.observe(self.root, ["src"], ("src/output",))
        self.assertEqual(set(content), {"src/hello caf\u00e9.txt", "src/deleted.txt"})
        self.assertEqual(content["src/hello caf\u00e9.txt"], b"source\r\n")
        (self.root / "src/deleted.txt").unlink()
        second, content = snapshot.observe(self.root, ["src"], ("src/output",))
        self.assertNotEqual(first["identity"], second["identity"])
        target = self.root / "snapshot"
        snapshot.materialize(target, second, content)
        self.assertEqual((target / "src/hello caf\u00e9.txt").read_bytes(), b"source\r\n")
        self.assertFalse((target / "src/deleted.txt").exists())

    def test_traversal_windows_devices_and_aliases(self):
        for name in ("../secret", "/abs", "C:/secret", "a\\b", "a//b", "a.", "NUL.txt", "x:y", "COM1"):
            with self.subTest(name=name), self.assertRaises(common.DevError):
                paths.relative(name)
        self.assertEqual(paths.alias("caf\u00e9"), paths.alias("cafe\u0301"))

    def test_unicode_collision_rejected(self):
        self.write("src/caf\u00e9")
        self.write("src/cafe\u0301")
        with self.assertRaisesRegex(common.DevError, "collision"):
            snapshot.observe(self.root, ["src"])

    def test_links_and_hardlinks_rejected(self):
        self.write("input")
        os.link(self.root / "input", self.root / "hardlink")
        with self.assertRaises(common.DevError):
            snapshot.observe(self.root, ["input"])

    def test_changed_transfer_is_not_coherent(self):
        self.write("input")
        original = paths.read
        count = 0
        def changing(*args, **kwargs):
            nonlocal count
            count += 1
            result = original(*args, **kwargs)
            if count == 1:
                self.write("input", b"new revision")
            return result
        with patch.object(paths, "read", changing), self.assertRaisesRegex(common.DevError, "changed"):
            snapshot.observe(self.root, ["input"])

    def test_tampered_snapshot_is_rejected_before_writes(self):
        self.write("input")
        record, content = snapshot.observe(self.root, ["input"])
        target = self.root / "snapshot"
        with self.assertRaises(common.DevError):
            snapshot.materialize(target, record, {"input": b"wrong"})
        self.assertFalse(target.exists())

    def test_private_state_and_competing_controller(self):
        paths.private_root(self.root)
        workspace = state.workspace(self.root, "first", create=True)
        with state.lock(workspace):
            with self.assertRaises((OSError, common.DevError)):
                with state.lock(workspace):
                    self.fail("competing lock acquired")
        state.atomic(workspace, "result.json", {"state": "stopped"})
        self.assertEqual(state.load(workspace, "result.json"), {"state": "stopped"})

    @unittest.skipUnless(os.name == "nt", "Windows DACL enforcement")
    def test_private_state_rejects_access_for_unrelated_users(self):
        paths.private_root(self.root)
        icacls = Path(os.environ["SystemRoot"]) / "System32/icacls.exe"
        result = process.run([str(icacls), str(self.root), "/grant", "*S-1-1-0:(OI)(CI)R"], self.root)
        self.assertEqual(result.returncode, 0)
        with self.assertRaisesRegex(common.DevError, "acl-too-broad"):
            paths.private_root(self.root)


class OwnedCommands(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Linux guest namespace ownership")
    def test_restart_confirms_reaping_without_claiming_clean_shutdown(self):
        from tools.dev_workflow import service
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths.new_directory(root / "runtime")
            previous = {"bootId": "previous", "pidNamespace": "old", "initStartTicks": "1"}
            state.atomic(root, "lifecycle.json", {"state": "ready", "guestInstance": previous})
            with patch.object(service, "guest_instance", return_value=previous):
                with self.assertRaisesRegex(common.DevError, "cleanup-unknown"):
                    service.disconnected(root)
            result = service.disconnected(root)
            self.assertEqual(result["state"], "stopped")
            self.assertTrue(result["reaped"])
            self.assertFalse(result["cleanShutdown"])
            self.assertEqual(service.disconnected(root), result)

    def test_stdin_and_nonzero_result_reap(self):
        result = process.run([sys.executable, "-I", "-c",
                              "import sys; print(sys.stdin.read()); sys.exit(3)"], Path.cwd(), stdin=b"private input")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.strip(), b"private input")

    def test_output_flood_and_deadline_are_finite(self):
        for command, options in (("print('x'*65536)", {"maximum": 1024}),
                                 ("import time; time.sleep(30)", {"timeout": 0.2})):
            with self.assertRaises(common.DevError):
                process.run([sys.executable, "-I", "-c", command], Path.cwd(), **options)

    def test_no_ambient_credentials(self):
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "secret", "GH_TOKEN": "secret",
                                     "SSH_AUTH_SOCK": "socket", "PYTHONPATH": "injection"}):
            self.assertTrue({"AWS_SECRET_ACCESS_KEY", "GH_TOKEN", "SSH_AUTH_SOCK", "PYTHONPATH"}
                            .isdisjoint(process.environment()))

    @unittest.skipUnless(sys.platform == "linux", "Linux supervisor pipe ownership")
    def test_live_node_output_drains_flood_redacts_before_retention_and_requires_complete_status(self):
        from tools.dev_workflow.node_output import NodeOutput
        command = "import sys; print('x'*20000); print('private-token'); print('y'*500000); print('{\\\"schemaVersion\\\":\\\"latent.standalone.status.v1\\\",\\\"event\\\":\\\"stopped\\\",\\\"clean\\\":true}'); sys.stdout.flush()"
        child = subprocess.Popen([sys.executable, "-I", "-c", command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            output = NodeOutput(child, ["private-token"])
            self.assertEqual(child.wait(timeout=10), 0)
            output.finish()
            self.assertTrue(output.clean_stop)
            self.assertNotIn("private-token", output.logs())
            self.assertLessEqual(len(output.logs().encode()), common.MAX_LOG)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()


class ForegroundOwnership(unittest.TestCase):
    def test_idle_foreground_releases_command_lock_and_obeys_down(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from tools.dev_workflow import cli, foreground
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            class Connection:
                def call(self, operation, arguments, **options):
                    if operation == "up":
                        if options != {"timeout": common.MAX_START_SECONDS + 15}:
                            raise AssertionError("foreground startup must preserve the transport cleanup allowance")
                    calls.append(operation)
                    if operation == "status":
                        with state.lock(root):
                            pass
                    return {"state": "ready" if operation == "up" else "stopped", "reaped": True}
            args = SimpleNamespace(workspace="test", watch=False)
            with patch.object(foreground, "lease", return_value=nullcontext(lambda: None)), patch.object(cli, "emit"):
                result = cli.foreground_up(args, root, Connection())
            self.assertEqual(result["state"], "stopped")
            self.assertEqual(calls, ["up", "status", "down"])
            with state.lock(root, "foreground.lock"):
                pass


class DevcontainerOwnership(unittest.TestCase):
    def fixture(self, root):
        from tools.dev_workflow import devcontainer
        cache = root / ("a" * 64)
        cache.mkdir(mode=0o700)
        entries = []
        for name in ("bin/latent-dev", "bin/latent-portable-test-host", "bin/_internal/library.so", "helper.pyz",
                     "python-inventory.json", "build-provenance.json", "licenses/terms.txt", "sbom.spdx.json"):
            path = cache / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ("public test bytes: " + name).encode()
            path.write_bytes(raw)
            entries.append({"path": name, "sha256": common.digest(raw), "size": len(raw), "executable": name.startswith("bin/")})
        selected = {"schemaVersion": "latent.dev.bundle.v1", "version": "0.1.0-alpha.4", "sourceCommit": "b" * 40,
            "target": "linux-x86_64", "hostAbi": common.HOST_ABI, "protocol": common.PROTOCOL,
            "archive": {"name": "fixture.zip", "sha256": "sha256:" + cache.name, "size": 1}, "files": entries,
            "licenses": ["licenses/terms.txt"], "sbom": "sbom.spdx.json"}
        (cache / "verified-bundle.json").write_bytes(common.encode(selected))
        project = root / "project with spaces"
        project.mkdir(mode=0o700)
        return devcontainer, cache, project

    def test_container_generation_requires_consent_and_preserves_existing_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, cache, project = self.fixture(Path(temporary))
            with self.assertRaisesRegex(common.DevError, "consent-required"):
                module.generate(project, cache, consent=False)
            self.assertFalse((project / ".devcontainer").exists())
            (project / ".devcontainer").mkdir()
            selected = project / ".devcontainer/devcontainer.json"
            selected.write_bytes(b"existing user configuration")
            with self.assertRaisesRegex(common.DevError, "existing-devcontainer-preserved"):
                module.generate(project, cache, consent=True)
            self.assertEqual(selected.read_bytes(), b"existing user configuration")

    def test_container_generation_copies_only_verified_bytes_and_executes_no_commands(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            module, cache, project = self.fixture(Path(temporary))
            (cache / ".env").write_bytes(b"private-unlisted-fixture")
            with patch.object(subprocess, "run", side_effect=AssertionError("generation must not execute a command")):
                result = module.generate(project, cache, consent=True)
            directory = project / ".devcontainer"
            config = json.loads((directory / "devcontainer.json").read_bytes())
            self.assertEqual(result["state"], "prepared")
            self.assertFalse(result["automaticExecution"])
            self.assertFalse((directory / "verified/.env").exists())
            self.assertEqual((directory / "verified/bin/_internal/library.so").read_bytes(),
                             (cache / "bin/_internal/library.so").read_bytes())
            self.assertNotIn("--privileged", config["runArgs"])
            self.assertIn("--cap-drop=ALL", config["runArgs"])
            self.assertFalse(any("socket" in mount or "source=/," in mount for mount in config["mounts"]))
            self.assertFalse(any(key.endswith("Command") for key in config))
            self.assertEqual(config["userEnvProbe"], "none")
            self.assertEqual(config["containerEnv"]["SSH_AUTH_SOCK"], "/dev/null")
            self.assertEqual(config["forwardPorts"], [])
            self.assertEqual((directory / ".gitignore").read_bytes(), b"/*\n!/.gitignore\n")

    def test_generated_tools_and_container_ownership_never_enter_guest_source_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, cache, project = self.fixture(Path(temporary))
            module.generate(project, cache, consent=True)
            (project / "src").mkdir()
            (project / "src/main.txt").write_bytes(b"capsule source\r\n")
            record, content = snapshot.observe(project, ["src", ".devcontainer"])
            self.assertEqual([entry["path"] for entry in record["files"]], ["src/main.txt"])
            self.assertEqual(content, {"src/main.txt": b"capsule source\r\n"})

    def test_container_generation_rejects_tampering_before_writing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, cache, project = self.fixture(Path(temporary))
            (cache / "bin/latent-dev").write_bytes(b"untrusted executable")
            with self.assertRaisesRegex(common.DevError, "verified-bundle-cache-changed"):
                module.generate(project, cache, consent=True)
            self.assertFalse((project / ".devcontainer").exists())

    def test_changed_cache_during_copy_retains_incomplete_owner_without_runnable_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            module, cache, project = self.fixture(Path(temporary))
            verify = module.bundle.verify_cache
            def changed(*args, **kwargs):
                verify(*args, **kwargs)
                (cache / "bin/latent-dev").write_bytes(b"changed after first verification")
            with patch.object(module.bundle, "verify_cache", side_effect=changed):
                with self.assertRaisesRegex(common.DevError, "devcontainer-bundle-changed"):
                    module.generate(project, cache, consent=True)
            self.assertEqual(state.load(project / ".devcontainer", "ownership.json")["state"], "preparing")
            self.assertFalse((project / ".devcontainer/devcontainer.json").exists())
            self.assertFalse((project / ".devcontainer/Dockerfile").exists())


if __name__ == "__main__":
    unittest.main()

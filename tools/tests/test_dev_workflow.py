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
        for changed in ({"hostAbi": "old"}, {"architecture": "aarch64"}, {"features": []}):
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


if __name__ == "__main__":
    unittest.main()

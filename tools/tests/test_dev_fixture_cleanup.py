"""Explicit purge removes private fixture outputs without crossing an owner."""
from pathlib import Path
import os
import sys
import tempfile
import unittest

from tools.dev_workflow import cleanup, fixture_cleanup, http_fixture, paths, secret_fixture, state
from tools.dev_workflow.common import DevError


class FixturePurge(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.root = state.workspace(self.parent, "test-purge", create=True)
        self.other = state.workspace(self.parent, "test-other", create=True)
        self.http = {"port": 18123, "exchanges": [{"method": "GET", "path": "/value",
                     "requestBody": "", "responseBody": "", "status": 200}]}
        self.secrets = {"references": [{"name": "dev-owned"}]}
        for root in (self.root, self.other):
            http_fixture.credential(root, self.http, create=True)
            secret_fixture.values(root, self.secrets, create=True)
        state.atomic(self.root, "lifecycle.json", {"state": "stopped", "reaped": True})

    @unittest.skipUnless(sys.platform == "linux", "actual Linux native purge")
    def test_purge_removes_complete_and_partial_private_fixtures_and_is_idempotent(self):
        partial = self.root / "event-fixture-private"
        paths.new_directory(partial)
        paths.write_new(partial / "key.pem", b"private partial test key")
        paths.write_new(partial / ("pending-" + "a" * 32), b"partial owner write")
        original_other = fixture_cleanup.plan(self.other)
        original_author = self.root / "author-source.txt"
        paths.write_new(original_author, b"author source remains")
        result = cleanup.purge(self.root, self.root.name, self.root.name)
        self.assertEqual(set(result["fixtureDirectoriesRemoved"]), set(fixture_cleanup.DIRECTORIES))
        self.assertTrue(all(not (self.root / name).exists() for name in fixture_cleanup.DIRECTORIES))
        self.assertEqual(fixture_cleanup.plan(self.other), original_other)
        self.assertEqual(original_author.read_bytes(), b"author source remains")
        self.assertEqual(cleanup.purge(self.root, self.root.name, self.root.name)["fixtureDirectoriesRemoved"], [])

    @unittest.skipUnless(sys.platform == "linux", "actual Linux native purge")
    def test_confirmation_and_stopped_state_are_required_before_private_cleanup(self):
        before = fixture_cleanup.plan(self.root)
        with self.assertRaisesRegex(DevError, "confirm-exact-workspace"):
            cleanup.purge(self.root, self.root.name, self.other.name)
        state.atomic(self.root, "lifecycle.json", {"state": "ready"})
        with self.assertRaisesRegex(DevError, "stop-and-confirm"):
            cleanup.purge(self.root, self.root.name, self.root.name)
        self.assertEqual(fixture_cleanup.plan(self.root), before)

    @unittest.skipUnless(sys.platform == "linux", "actual Linux native purge")
    def test_unknown_later_fixture_entry_rejects_before_any_build_or_credential_deletion(self):
        selected = self.root / "event-fixture-private"
        paths.new_directory(selected)
        paths.write_new(selected / "author-notes.txt", b"unrelated data")
        builds = self.root / "builds"
        paths.new_directory(builds)
        paths.write_new(builds / "unrelated-data", b"preserve")
        prior = (self.root / "http-fixture-private/authorization").read_bytes()
        with self.assertRaisesRegex(DevError, "unrecognized-test-fixture"):
            cleanup.purge(self.root, self.root.name, self.root.name)
        self.assertEqual((self.root / "http-fixture-private/authorization").read_bytes(), prior)
        self.assertEqual((selected / "author-notes.txt").read_bytes(), b"unrelated data")
        self.assertEqual((builds / "unrelated-data").read_bytes(), b"preserve")

    def test_changed_material_and_foreign_purpose_cannot_reuse_purge_preflight(self):
        selected = fixture_cleanup.plan(self.root)
        path = self.root / "http-fixture-private/authorization"
        path.write_bytes(b"changed after preflight")
        with self.assertRaisesRegex(DevError, "purge-input-changed"):
            fixture_cleanup.purge(self.root, selected)
        self.assertTrue(path.exists())
        state.atomic(self.root / "http-fixture-private", "owner.json", {"purpose": "some-other-owner"})
        with self.assertRaisesRegex(DevError, "purpose-mismatch"):
            fixture_cleanup.plan(self.root)

    @unittest.skipUnless(sys.platform == "linux", "Linux link and private mode boundaries")
    def test_links_and_nonprivate_files_fail_without_touching_their_targets(self):
        directory = self.root / "event-fixture-private"
        foreign = self.other / "secret-fixture-private/dev-owned"
        retained = foreign.read_bytes()
        directory.symlink_to(self.other / "secret-fixture-private", target_is_directory=True)
        with self.assertRaises((OSError, DevError)):
            fixture_cleanup.plan(self.root)
        directory.unlink()
        paths.new_directory(directory)
        selected = directory / "key.pem"
        for mode in ("symlink", "hardlink", "public"):
            with self.subTest(mode=mode):
                if mode == "symlink":
                    selected.symlink_to(foreign)
                elif mode == "hardlink":
                    os.link(foreign, selected)
                else:
                    paths.write_new(selected, b"too broad")
                    selected.chmod(0o644)
                with self.assertRaises((OSError, DevError)):
                    fixture_cleanup.plan(self.root)
                self.assertEqual(foreign.read_bytes(), retained)
                selected.unlink()

    def test_count_and_byte_bounds_and_wrong_workspace_reject_before_deletion(self):
        directory = self.root / "secret-fixture-private"
        for index in range(9):
            paths.write_new(directory / f"dev-extra-{index}", b"bounded")
        with self.assertRaisesRegex(DevError, "entry-limit"):
            fixture_cleanup.plan(self.root)
        for index in range(9):
            (directory / f"dev-extra-{index}").unlink()
        (directory / "dev-owned").write_bytes(b"x" * 16385)
        with self.assertRaisesRegex(DevError, "file-byte-limit"):
            fixture_cleanup.plan(self.root)
        named = self.parent / "not-a-test"
        paths.new_directory(named)
        paths.new_directory(named / "http-fixture-private")
        with self.assertRaisesRegex(DevError, "purge-owner-required"):
            fixture_cleanup.plan(named)


if __name__ == "__main__":
    unittest.main()

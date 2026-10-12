import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.run_static_site_workflow import active_installation, corrupt_signed_error_blob
from tools.static_site import MAX_ASSET_BYTES


class Cancellation:
    def __init__(self):
        self.cancelled = False

    def check(self):
        if self.cancelled:
            raise RuntimeError('cancelled')


class StaticErrorCorruptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.installation = self.base / 'restored-installation'
        self.blobs = self.installation / 'data/releases/blobs'
        self.blobs.mkdir(parents=True)
        self.original = b'<!doctype html><h1>Page not found</h1>'
        digest = 'sha256:' + hashlib.sha256(self.original).hexdigest()
        self.asset = {'path': '/404.html', 'mediaType': 'text/html', 'size': len(self.original), 'digest': digest}
        self.path = self.blobs / digest[7:]
        self.path.write_bytes(self.original)
        self.cancellation = Cancellation()
        self.client = SimpleNamespace(directory=self.base / 'client', cancellation=self.cancellation,
                                      deadline=time.monotonic() + 30)

    def test_actual_shared_inode_is_corrupted_without_resizing_then_restored(self):
        alias = self.installation / 'publication-error.bin'
        os.link(self.path, alias)
        identity = self.path.stat().st_ino
        with corrupt_signed_error_blob(self.client, self.installation, self.asset) as observation:
            self.assertEqual(self.path.stat().st_ino, identity)
            self.assertEqual(len(alias.read_bytes()), len(self.original))
            self.assertNotEqual(alias.read_bytes(), self.original)
            self.assertEqual(alias.read_bytes()[1:], self.original[1:])
            self.assertEqual(observation['signedDigest'], self.asset['digest'])
            self.assertFalse(observation['restored'])
        self.assertTrue(observation['restored'])
        self.assertEqual(alias.read_bytes(), self.original)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_exception_in_browser_or_socket_campaign_restores_original_bytes(self):
        with self.assertRaisesRegex(RuntimeError, 'browser failure'):
            with corrupt_signed_error_blob(self.client, self.installation, self.asset):
                raise RuntimeError('browser failure')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_cancellation_and_expired_workflow_do_not_skip_physical_restoration(self):
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            with corrupt_signed_error_blob(self.client, self.installation, self.asset):
                self.cancellation.cancelled = True
                self.client.deadline = time.monotonic() - 1
                self.cancellation.check()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_mismatched_signed_hash_refuses_fault_before_writing(self):
        altered = b'X' + self.original[1:]
        self.path.write_bytes(altered)
        with self.assertRaisesRegex(WorkflowError, 'static-fault-original-digest'):
            with corrupt_signed_error_blob(self.client, self.installation, self.asset):
                self.fail('fault must not start on already corrupt input')
        self.assertEqual(self.path.read_bytes(), altered)

    def test_exact_size_and_original_per_asset_bound_are_required(self):
        for size in (True, 0, -1, MAX_ASSET_BYTES + 1, len(self.original) + 1):
            with self.subTest(size=size):
                with self.assertRaises(WorkflowError):
                    with corrupt_signed_error_blob(self.client, self.installation, {**self.asset, 'size': size}):
                        self.fail('invalid size reached mutation')
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_only_fixed_signed_html_error_member_and_canonical_digest_are_selected(self):
        for change in ({'path': '/index.html'}, {'path': '/../404.html'}, {'mediaType': 'text/javascript'},
                       {'digest': '../foreign'}, {'digest': 'sha256:' + 'A' * 64}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(WorkflowError, 'static-fault-signed-error-asset'):
                    with corrupt_signed_error_blob(self.client, self.installation, {**self.asset, **change}):
                        self.fail('foreign selection reached mutation')
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_concurrent_unknown_content_is_refused_without_overwriting_it(self):
        foreign = b'ZZ' + self.original[2:]
        with self.assertRaisesRegex(WorkflowError, 'static-fault-concurrent-content-change'):
            with corrupt_signed_error_blob(self.client, self.installation, self.asset):
                self.path.write_bytes(foreign)
        self.assertEqual(self.path.read_bytes(), foreign)

    @unittest.skipUnless(os.name == 'posix', 'Linux fixture path and held-inode ownership')
    def test_replaced_path_is_refused_and_foreign_replacement_is_not_written(self):
        retained = self.path.with_name('held-original')
        foreign = b'Y' * len(self.original)
        with self.assertRaisesRegex(WorkflowError, 'static-fault-path-replaced'):
            with corrupt_signed_error_blob(self.client, self.installation, self.asset):
                self.path.rename(retained)
                self.path.write_bytes(foreign)
        self.assertEqual(self.path.read_bytes(), foreign)
        self.assertEqual(retained.read_bytes(), self.original)

    @unittest.skipUnless(os.name == 'posix', 'Linux no-follow fixture path')
    def test_symbolic_blob_and_parent_paths_are_refused_before_writing(self):
        target = self.installation / 'original'
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaisesRegex(WorkflowError, 'static-fault-owned-regular-file'):
            with corrupt_signed_error_blob(self.client, self.installation, self.asset):
                self.fail('symbolic blob reached mutation')
        self.assertEqual(target.read_bytes(), self.original)
        self.path.unlink()
        target.rename(self.path)
        alias = self.base / 'alias'
        alias.symlink_to(self.installation, target_is_directory=True)
        with self.assertRaisesRegex(WorkflowError, 'static-fault-canonical-installation'):
            with corrupt_signed_error_blob(self.client, alias, self.asset):
                self.fail('symbolic installation reached mutation')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_active_root_comes_from_exact_existing_restored_process_configuration(self):
        config = self.installation / 'node.json'
        config.write_text(json.dumps({'dataDirectory': 'data'}), encoding='utf-8')
        arguments = ['node-binary', 'serve', '--config', str(config)]
        node = SimpleNamespace(owner=SimpleNamespace(process=SimpleNamespace(args=arguments)))
        self.assertEqual(active_installation(self.client, node), self.installation)
        config.write_text(json.dumps({'dataDirectory': '../original-installation'}), encoding='utf-8')
        with self.assertRaisesRegex(WorkflowError, 'static-fault-data-directory'):
            active_installation(self.client, node)
        arguments[-1] = str(self.base / 'node.json')
        with self.assertRaisesRegex(WorkflowError, 'static-fault-active-installation'):
            active_installation(self.client, node)

"""Qualification bootstrap rejects altered archives and bounds its own children."""
from pathlib import Path
import hashlib
import os
import sys
import tempfile
import unittest
import zipfile

from tools.dev_packaged_bootstrap import extract
from tools.dev_packaged_process import Command, ProbeFailure, environment


class PackagedProbe(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lsf-packaged-probe-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def bundle(self, names, *, symlink=False, changed=False):
        entries = []
        with zipfile.ZipFile(self.root / 'input.zip', 'w') as archive:
            for index, name in enumerate(names):
                raw = ('harmless fixture ' + str(index)).encode()
                member = zipfile.ZipInfo(name)
                member.create_system = 3
                member.external_attr = (0o120777 if symlink else 0o100600) << 16
                archive.writestr(member, raw)
                entries.append({'path': name, 'size': len(raw), 'executable': name == 'bin/latent-dev.exe',
                    'sha256': 'sha256:' + ('0' * 64 if changed else hashlib.sha256(raw).hexdigest())})
        return {'archive': {'name': 'input.zip'}, 'files': entries}

    def test_exact_inventory_extracts_without_executing_any_member(self):
        manifest = self.bundle(['bin/latent-dev.exe', 'licenses/terms.txt'])
        selected = extract(self.root, manifest, self.root / 'installed')
        self.assertEqual(selected.read_bytes(), b'harmless fixture 0')

    @unittest.skipUnless(os.name == 'nt', 'actual Windows DACL required')
    def test_conductor_protects_only_its_new_windows_directory(self):
        from tools.dev_packaged_windows import make_private
        from tools.dev_workflow.paths import private_root
        sibling = self.root / 'other-owner-data'
        sibling.write_bytes(b'untouched')
        selected = self.root / 'private'
        make_private(selected)
        private_root(selected)
        self.assertEqual(sibling.read_bytes(), b'untouched')

    def test_traversal_device_and_unicode_aliases_reject_before_creation(self):
        for names in (['../escape'], ['bin/NUL.txt'], ['bin/COM0'], ['bin/odd:stream'],
                      ['bin/caf\u00e9', 'bin/cafe\u0301'], ['bin/A', 'bin/a'], ['bin/a\nfile']):
            with self.subTest(names=names):
                manifest = self.bundle(['bin/latent-dev.exe', *names])
                with self.assertRaises(ProbeFailure):
                    extract(self.root, manifest, self.root / 'installed')
                self.assertFalse((self.root / 'installed').exists())

    def test_symlink_rejects_before_creation(self):
        with self.assertRaisesRegex(ProbeFailure, 'frontend-member-identity'):
            extract(self.root, self.bundle(['bin/latent-dev.exe'], symlink=True), self.root / 'installed')
        self.assertFalse((self.root / 'installed').exists())

    def test_changed_bytes_never_return_an_executable(self):
        with self.assertRaisesRegex(ProbeFailure, 'frontend-expanded-member-digest'):
            extract(self.root, self.bundle(['bin/latent-dev.exe'], changed=True), self.root / 'installed')

    def test_linux_target_requires_its_own_entrypoint(self):
        manifest = self.bundle(['bin/latent-dev.exe'])
        manifest['target'] = 'linux-x86_64'
        with self.assertRaisesRegex(ProbeFailure, 'frontend-expanded-byte-bound'):
            extract(self.root, manifest, self.root / 'installed')
        self.assertFalse((self.root / 'installed').exists())

    @unittest.skipUnless(os.name == 'posix', 'actual executable modes required')
    def test_linux_exact_entrypoint_is_executable_and_private(self):
        manifest = self.bundle(['bin/latent-dev', 'helper.pyz'])
        manifest['target'] = 'linux-x86_64'
        manifest['files'][0]['executable'] = True
        selected = extract(self.root, manifest, self.root / 'installed')
        self.assertEqual(selected.stat().st_mode & 0o777, 0o700)
        self.assertEqual((selected.parent.parent / 'helper.pyz').stat().st_mode & 0o777, 0o600)

    def test_output_flood_is_bounded_and_owned_child_is_reaped(self):
        child = Command([sys.executable, '-I', '-B', '-c',
            'import sys,time;sys.stdout.buffer.write(b"x"*5000000);sys.stdout.flush();time.sleep(10)'],
            self.root, environment(self.root))
        try:
            with self.assertRaisesRegex(ProbeFailure, 'conductor-output-limit'):
                child.finish(5)
        finally:
            child.abort_controller()
        self.assertLessEqual(len(child.raw()), 4194304)
        self.assertIsNotNone(child.child.returncode)

    def test_deadline_does_not_replay_the_command(self):
        script = 'from pathlib import Path;import time;p=Path("effects");p.write_text("once");time.sleep(10)'
        child = Command([sys.executable, '-I', '-B', '-c', script], self.root, environment(self.root))
        try:
            with self.assertRaisesRegex(ProbeFailure, 'conductor-command-deadline'):
                child.finish(1)
        finally:
            child.abort_controller()
        self.assertEqual((self.root / 'effects').read_text(), 'once')
        self.assertIsNotNone(child.child.returncode)

    def test_bounded_binary_stdin_reaches_only_the_owned_child(self):
        payload = b'private-test-input\x00' * 1024
        child = Command([sys.executable, '-I', '-B', '-c',
            'import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'],
            self.root, environment(self.root), input_bytes=payload)
        try:
            self.assertEqual(child.finish(5), 0)
            self.assertEqual(child.raw().strip().decode(), hashlib.sha256(payload).hexdigest())
            self.assertNotIn('private-test-input', str(child.receipt()))
        finally:
            child.abort_controller()
        with self.assertRaisesRegex(ProbeFailure, 'conductor-input-byte-limit'):
            Command([sys.executable, '-c', 'raise AssertionError("never starts")'],
                    self.root, environment(self.root), input_bytes=b'x' * (2 * 1024 * 1024 + 1))


if __name__ == '__main__':
    unittest.main()

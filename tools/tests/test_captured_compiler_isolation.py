"""Actual namespace controls and source/sysroot identity checks."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

from tools.application_dependency_store import DependencyError
from tools.build_process import BuildProcessError, run_bounded, run_bounded_result
from tools.captured_compiler_isolation import Isolation, dependency_paths, distribution


class CompilerInputs(unittest.TestCase):
    def test_dependency_output_preserves_escaped_names_and_continuations(self):
        self.assertEqual(dependency_paths(b'lsf-inputs: /selected/a\\ b.c \\\n /selected/a\\#b.h /selected/a$$b.bin\n'),
                         ['/selected/a b.c', '/selected/a#b.h', '/selected/a$b.bin'])

    def test_dependency_output_cannot_hide_rules_variables_or_overflow(self):
        for value in (b'other: /selected/a', b'lsf-inputs: $(secret)', b'lsf-inputs: /one\nextra: /two',
                      b'lsf-inputs: /one\\', b'lsf-inputs: /one#hidden', b'x' * (2 * 1024 * 1024 + 1)):
            with self.subTest(value=value[:50]), self.assertRaises(DependencyError):
                dependency_paths(value)

    def test_distribution_binds_headers_runtime_and_zero_byte_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'zig').write_bytes(b'compiler')
            (root / 'lib').mkdir()
            (root / 'lib/stdio.h').write_bytes(b'header')
            (root / 'lib/empty').write_bytes(b'')
            before = distribution(root)
            self.assertEqual([row['path'] for row in before], ['lib/empty', 'lib/stdio.h', 'zig'])
            (root / 'lib/stdio.h').write_bytes(b'modified-header')
            self.assertNotEqual(distribution(root), before)

    def test_absolute_embedded_file_outside_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'selected'
            workspace.mkdir()
            secret = root / 'outside.bin'
            secret.write_bytes(b'not-a-build-input')
            depfile = workspace / 'inputs.d'
            depfile.write_bytes(('lsf-inputs: ' + secret.as_posix() + '\n').encode())
            observer = Isolation.__new__(Isolation)
            observer.workspace, observer.distributions, observer.shared = workspace, {}, {}
            with self.assertRaises(DependencyError):
                observer.observe_inputs(depfile)


class CompilerNamespace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        usable = sys.platform == 'linux' and shutil.which('bwrap') and shutil.which('ldd')
        if not usable:
            if os.environ.get('LSF_REQUIRE_COMPILER_ISOLATION') == '1':
                raise RuntimeError('required compiler namespace tools are missing')
            raise unittest.SkipTest('actual namespace qualification requires Linux bubblewrap')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / 'selected'
        self.workspace.mkdir()
        self.cat = Path(shutil.which('cat')).resolve(strict=True)
        self.shell = Path(shutil.which('sh')).resolve(strict=True)
        self.isolation = Isolation(self.workspace, {'cat': self.cat, 'shell': self.shell}, {})
        self.environment = {'PATH': os.defpath, 'PRIVATE_CAPTURE_SECRET': 'must-not-reach-the-compiler'}

    def execute(self, tool, *args, timeout=5):
        return run_bounded_result(self.isolation.wrap(tool, list(args), self.workspace, self.environment),
                                  self.workspace, self.environment, timeout, 16384)

    def test_selected_bytes_work_but_ambient_file_and_credentials_are_absent(self):
        selected = self.workspace / 'selected.bin'
        selected.write_bytes(b'captured')
        secret = self.root / 'outside.bin'
        secret.write_bytes(b'ambient-secret')
        self.assertEqual(self.execute(self.cat, str(selected)).stdout, b'captured')
        self.assertNotEqual(self.execute(self.cat, str(secret)).returncode, 0)
        result = self.execute(self.shell, '-c', 'printf "%s|%s" "${PRIVATE_CAPTURE_SECRET-unset}" "$HOME"')
        self.assertEqual(result.stdout, b'unset|/home')
        self.isolation.check_unchanged()

    def test_deadline_kills_descendants_and_next_build_is_clean(self):
        marker = self.workspace / 'child-progress'
        argv = self.isolation.wrap(self.shell, ['-c', 'while :; do printf x >> child-progress; done & wait'],
                                   self.workspace, self.environment)
        with self.assertRaisesRegex(BuildProcessError, 'command-deadline'):
            run_bounded(argv, self.workspace, self.environment, 0.25, 16384)
        before = marker.stat().st_size
        time.sleep(0.1)
        self.assertEqual(marker.stat().st_size, before)
        marker.write_bytes(b'fresh-build')
        self.assertEqual(self.execute(self.cat, str(marker)).stdout, b'fresh-build')


if __name__ == '__main__':
    unittest.main()

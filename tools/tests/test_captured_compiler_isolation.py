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

    def test_selected_sources_are_read_only_and_owned_outputs_remain_writable(self):
        source = self.workspace / 'source'
        source.mkdir()
        (source / 'selected.bin').write_bytes(b'original')
        self.isolation.protect_inputs(source)
        self.assertEqual(self.execute(self.cat, str(source / 'selected.bin')).stdout, b'original')
        script = 'printf changed > source/selected.bin'
        self.assertNotEqual(self.execute(self.shell, '-c', script).returncode, 0)
        self.assertEqual((source / 'selected.bin').read_bytes(), b'original')
        self.assertEqual(self.execute(self.shell, '-c', 'printf generated > output.bin').returncode, 0)
        self.assertEqual((self.workspace / 'output.bin').read_bytes(), b'generated')

    def test_captured_sdk_child_path_cannot_expose_unregistered_executables(self):
        distribution_root = self.root / 'compiler'
        executables = distribution_root / 'bin'
        executables.mkdir(parents=True)
        child = executables / 'captured-cat'
        shutil.copyfile(self.cat, child)
        child.chmod(0o755)
        boundary = Isolation(self.workspace, {'child': child, 'shell': self.shell}, {'compiler': distribution_root})
        boundary.enable_children(executables)
        (self.workspace / 'input.bin').write_bytes(b'captured-child')
        result = run_bounded_result(boundary.wrap(self.shell, ['-c', 'captured-cat input.bin'], self.workspace, self.environment),
                                    self.workspace, self.environment, 5, 16384)
        self.assertEqual(result.stdout, b'captured-child')
        boundary.check_unchanged()
        with self.assertRaisesRegex(DependencyError, 'outside-captured-distribution'):
            boundary.enable_children(self.workspace)
        (executables / 'unregistered').write_bytes(b'host tool')
        with self.assertRaisesRegex(DependencyError, 'not-captured'):
            boundary.enable_children(executables)

    def test_go_compiler_policy_cannot_enable_network_cgo_or_an_ambient_toolchain(self):
        for key, value in (('GOPROXY', 'https://example.invalid'), ('GOTOOLCHAIN', 'auto'), ('CGO_ENABLED', '1'),
                           ('GOWORK', '/ambient/go.work'), ('GOENV', '/ambient/go.env'), ('GOOS', 'linux')):
            with self.subTest(key=key), self.assertRaisesRegex(DependencyError, 'go-compiler-policy-invalid'):
                self.isolation.wrap(self.cat, [], self.workspace, {**self.environment, key: value})
        environment = {**self.environment, 'GOPROXY': 'off', 'GOTOOLCHAIN': 'local', 'CGO_ENABLED': '0'}
        command = self.isolation.wrap(self.shell, ['-c', 'printf "%s|%s|%s" "$GOPROXY" "$GOTOOLCHAIN" "$CGO_ENABLED"'],
                                      self.workspace, environment)
        result = run_bounded_result(command, self.workspace, environment, 5, 16384)
        self.assertEqual(result.stdout, b'off|local|0')

    def test_loader_search_uses_captured_libraries_and_cannot_inherit_ambient_paths(self):
        captured = self.root / 'captured-libraries'
        captured.mkdir()
        original = next(Path(name) for name in self.isolation.shared if Path(name).name == 'libc.so.6')
        shutil.copyfile(original, captured / original.name)
        boundary = Isolation(self.workspace, {'cat': self.cat}, {'loader': captured},
                             loader_directories=(captured,))
        self.assertEqual(boundary.receipt['loaderLibraryDirectories'], [{'distribution': 'loader', 'path': '.'}])
        self.assertNotIn(str(original), boundary.shared)
        command = boundary.wrap(self.cat, ['--version'], self.workspace,
                                {**self.environment, 'LD_LIBRARY_PATH': str(self.root / 'ambient')})
        self.assertIn(['--setenv', 'LD_LIBRARY_PATH', str(captured)],
                      [command[index:index + 3] for index in range(len(command) - 2)])
        self.assertNotIn(str(self.root / 'ambient'), command)
        result = run_bounded_result(command, self.workspace, self.environment, 5, 16384)
        self.assertEqual(result.returncode, 0)
        boundary.check_unchanged()
        relocated = self.root / 'relocated-captured-libraries'
        relocated.mkdir()
        shutil.copyfile(original, relocated / original.name)
        fresh = Isolation(self.workspace, {'cat': self.cat}, {'loader': relocated},
                          loader_directories=(relocated,))
        self.assertEqual(boundary.receipt, fresh.receipt)

    def test_loader_search_rejects_uncaptured_duplicate_and_excessive_directories(self):
        captured = self.root / 'captured-libraries'
        captured.mkdir()
        (captured / 'identity').write_bytes(b'captured')
        for selected in ((self.workspace,), (captured, captured), (captured,) * 9):
            with self.subTest(directories=selected), self.assertRaisesRegex(DependencyError, 'compiler-loader-directory'):
                Isolation(self.workspace, {'cat': self.cat}, {'loader': captured}, loader_directories=selected)

    def test_captured_loader_mutation_is_rejected_before_reuse(self):
        captured = self.root / 'captured-libraries'
        captured.mkdir()
        original = next(Path(name) for name in self.isolation.shared if Path(name).name == 'libc.so.6')
        target = captured / original.name
        shutil.copyfile(original, target)
        boundary = Isolation(self.workspace, {'cat': self.cat}, {'loader': captured},
                             loader_directories=(captured,))
        target.write_bytes(b'changed-captured-library')
        with self.assertRaisesRegex(DependencyError, 'compiler-distribution-or-sysroot-mutated'):
            boundary.check_unchanged()


class CanonicalCompilerHostTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CompilerNamespace.setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="compiler-host-alias-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "selected"
        self.workspace.mkdir()
        self.sandbox = Path(shutil.which("bwrap")).resolve(strict=True)
        self.loader = Path(shutil.which("ldd")).resolve(strict=True)
        self.cat = Path(shutil.which("cat")).resolve(strict=True)

    def test_host_directory_aliases_bind_canonical_tool_bytes_before_namespace_execution(self):
        from unittest.mock import patch
        from tools import captured_compiler_isolation as compiler
        from tools.build_observation import file_identity
        aliases = {"bwrap": self.root / "host-bin", "ldd": self.root / "host-observer"}
        aliases["bwrap"].symlink_to(self.sandbox.parent, target_is_directory=True)
        aliases["ldd"].symlink_to(self.loader.parent, target_is_directory=True)
        selected = {"bwrap": str(aliases["bwrap"] / self.sandbox.name),
                    "ldd": str(aliases["ldd"] / self.loader.name)}
        with patch.object(compiler.shutil, "which", side_effect=selected.get):
            boundary = compiler.Isolation(self.workspace, {"cat": self.cat}, {})
        self.assertEqual(boundary.sandbox, self.sandbox)
        self.assertEqual(boundary.receipt["sandbox"], file_identity(self.sandbox, "build-sandbox"))
        self.assertEqual(boundary.receipt["loaderObserver"], file_identity(self.loader, "loader-dependency-observer"))
        for alias in aliases.values():
            alias.unlink()
            alias.symlink_to(self.root / "unused-host-directory", target_is_directory=True)
        source = self.workspace / "selected.bin"
        source.write_bytes(b"canonical selected bytes")
        environment = {"PATH": os.defpath}
        command = boundary.wrap(self.cat, [str(source)], self.workspace, environment)
        self.assertEqual(command[0], str(self.sandbox))
        self.assertFalse(any(str(alias) in argument for alias in aliases.values() for argument in command))
        result = run_bounded_result(command, self.workspace, environment, 5, 16384)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"canonical selected bytes")
        boundary.check_unchanged()

    def test_explicit_captured_workspace_executable_and_distribution_links_remain_denied(self):
        from unittest.mock import patch
        from tools import captured_compiler_isolation as compiler
        distribution = self.root / "distribution"
        distribution.mkdir()
        (distribution / "selected.bin").write_bytes(b"selected compiler input")
        workspace_link, tool_link, distribution_link = (self.root / name for name in
                                                        ("workspace-link", "tool-link", "distribution-link"))
        workspace_link.symlink_to(self.workspace, target_is_directory=True)
        tool_link.symlink_to(self.cat)
        distribution_link.symlink_to(distribution, target_is_directory=True)
        selected = {"bwrap": str(self.sandbox), "ldd": str(self.loader)}
        for workspace, tools, distributions in ((workspace_link, {"cat": self.cat}, {}),
                                                (self.workspace, {"cat": tool_link}, {}),
                                                (self.workspace, {"cat": self.cat}, {"sdk": distribution_link})):
            with self.subTest(workspace=workspace, tools=tools, distributions=distributions), \
                    patch.object(compiler.shutil, "which", side_effect=selected.get), \
                    self.assertRaisesRegex(DependencyError, "dependency-link-denied"):
                compiler.Isolation(workspace, tools, distributions)


if __name__ == '__main__':
    unittest.main()

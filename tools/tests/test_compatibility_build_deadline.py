"""Actual normal builder pre-command boundaries; no guest/compiler processes."""
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import c_capsule_build, c_capsule_project, go_capsule_build, go_capsule_project
from tools import java_capsule_build, java_capsule_project, rust_capsule_build, rust_capsule_project
from tools import build_observation
from tools import captured_compiler_isolation as isolated
from tools.java_guest import compiler as java_compiler
from tools.dotnet_guest import build as dotnet_build, project as dotnet_project
from tools.typescript_guest import build as typescript_build, project as typescript_project


BUILDERS = (
    ('c', c_capsule_build, c_capsule_project), ('rust', rust_capsule_build, rust_capsule_project),
    ('go', go_capsule_build, go_capsule_project), ('java', java_capsule_build, java_capsule_project),
    ('dotnet', dotnet_build, dotnet_project), ('typescript', typescript_build, typescript_project))


class DeadlineObserved(BaseException):
    """Stop at the actual deadline write before any host tool can run."""


class BuildDeadline(unittest.TestCase):
    def test_real_six_builder_setup_cannot_renew_the_admitted_parent_deadline_before_first_tool(self):
        for language, module, project in BUILDERS:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); app = project.create(root / 'app', 'greeting')
                tools = root / 'tools'; tools.mkdir()
                deadline = time.monotonic() + 120
                observed = []
                class Commands:
                    def __init__(self, *args, **kwargs):
                        # Simulate an inner owner constructed after expensive
                        # copying/inventory. Its own relative budget is later.
                        object.__setattr__(self, 'deadline', deadline + 900)
                        self.records = []
                    def __setattr__(self, name, value):
                        object.__setattr__(self, name, value)
                        if name == 'deadline' and value == deadline - 5:
                            observed.append(value)
                            raise DeadlineObserved
                    def run(self, *args, **kwargs):
                        raise AssertionError('tool-ran-before-parent-deadline-clamp')
                arguments = [app, root / 'build', root / 'contracts', root / 'package',
                             'https://github.com/KirilsTurkins/latent-service-fabric']
                options = {'_deadline': deadline}
                if language == 'java': arguments.append(tools)
                if language in {'dotnet', 'typescript'}: options['tools'] = tools
                if language == 'rust':
                    clocks = []
                    def which(name, **kwargs):
                        if not clocks:
                            clock = patch.object(build_observation.time, 'monotonic', return_value=deadline - 6)
                            clock.start(); clocks.append(clock)
                        return str(tools / name)
                    def probe(*args, **kwargs):
                        self.assertEqual(kwargs['timeout_seconds'], 1)
                        self.assertEqual(kwargs['max_output_bytes'], 16 * 1024)
                        observed.append(build_observation.time.monotonic() + kwargs['timeout_seconds'])
                        raise DeadlineObserved
                    try:
                        with (patch.object(subprocess, 'Popen', side_effect=AssertionError('no-compiler')),
                                patch.object(build_observation.shutil, 'which', side_effect=which),
                                patch.object(build_observation, 'run_bounded', side_effect=probe),
                                self.assertRaises(DeadlineObserved)):
                            module.build(*arguments, **options)
                    finally:
                        for clock in clocks: clock.stop()
                else:
                    with (patch.object(subprocess, 'Popen', side_effect=AssertionError('no-compiler')),
                            patch.object(module, 'Commands', Commands), self.assertRaises(DeadlineObserved)):
                        module.build(*arguments, **options)
                self.assertEqual(observed, [deadline - 5])

    def test_invalid_or_expired_deadlines_refuse_before_any_output_or_source_mutation(self):
        for language, module, _ in BUILDERS:
            for invalid in (False, float('nan'), float('inf'), 0, time.monotonic() - 1, time.monotonic() + 1):
                with self.subTest(language=language, invalid=str(invalid)), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    args = [root / 'missing-app', root / 'output', root / 'contracts', root / 'package',
                            'https://github.com/KirilsTurkins/latent-service-fabric']
                    kwargs = {'_deadline': invalid}
                    if language == 'java': args.append(root / 'tools')
                    if language in {'dotnet', 'typescript'}: kwargs['tools'] = root / 'tools'
                    with self.assertRaises(ValueError): module.build(*args, **kwargs)
                    self.assertEqual(list(root.iterdir()), [])
        with (patch.object(build_observation.time, 'monotonic', return_value=100),
                patch.object(build_observation, 'run_bounded', return_value=SimpleNamespace(stdout=b'original-version')) as child):
            self.assertEqual(build_observation._probe(['tool'], Path.cwd(), {}), 'original-version')
            self.assertEqual(child.call_args.kwargs['timeout_seconds'], 30)
            self.assertEqual(build_observation._probe(['tool'], Path.cwd(), {}, _deadline=106), 'original-version')
            self.assertEqual(child.call_args.kwargs['timeout_seconds'], 1)
            child.reset_mock()
            with self.assertRaises(build_observation.SnapshotError):
                build_observation._probe(['tool'], Path.cwd(), {}, _deadline=104)
            child.assert_not_called()

        # Exercise the actual independent Java owner after cache setup has
        # consumed the parent budget, rather than stopping at Commands' clamp.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); sdk = root / 'sdk'; sdk.mkdir()
            (sdk / 'VERSION').write_text('29.0\nwasi-libc: ac020b86fd44\nllvm: 222fc11f2b8f\nllvm-version: 21.1.4\nconfig: f992bcc08219\n')
            cache = root / 'cache'; cache.mkdir(); (cache / 'dependency').write_bytes(b'cache')
            java = root / 'jdk/bin/java'; java.parent.mkdir(parents=True); java.write_bytes(b'java')
            clock = [100.0]
            def inventory(*args): clock[0] = 107.0
            with (patch.object(java_compiler.time, 'monotonic', side_effect=lambda: clock[0]),
                    patch.object(java_compiler, 'tool_inventory', side_effect=inventory),
                    patch.object(java_compiler, 'source_module', return_value=SimpleNamespace(verify_version=lambda *args: None)),
                    patch.object(java_compiler.shutil, 'which', return_value=str(java)),
                    patch.dict(java_compiler.os.environ, {}, clear=True),
                    patch.object(java_compiler, 'run_bounded_result') as child,
                    self.assertRaisesRegex(ValueError, 'Java build deadline exceeded')):
                java_compiler.Compiler(root / 'compiler', sdk, offline_cache=cache, _deadline=106)
            child.assert_not_called()

        # Inventory can consume setup time; every original ldd probe must
        # reserve cleanup from the original absolute parent again at spawn.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); distribution = root / 'distribution'; distribution.mkdir()
            tools = {}
            for name in ('bwrap', 'ldd', 'one', 'two'):
                path = distribution / name; path.write_bytes(name.encode()); tools[name] = path
            clock = [100.0]
            def observe(*args): clock[0] = 102.0; return []
            def probe(*args):
                self.assertEqual(args[3:], (1.0, 16384))
                clock[0] = 104.0
                return SimpleNamespace(stdout=b'statically linked', stderr=b'', returncode=0)
            with (patch.object(isolated.sys, 'platform', 'linux'),
                    patch.object(isolated.shutil, 'which', side_effect=lambda name, **kwargs: str(tools[name])),
                    patch.object(isolated.time, 'monotonic', side_effect=lambda: clock[0]),
                    patch.object(isolated.Isolation, 'observe_distribution', side_effect=observe),
                    patch.object(isolated, 'run_bounded_result', side_effect=probe) as child,
                    self.assertRaisesRegex(isolated.DependencyError, 'parent-cleanup-reserve')):
                isolated.Isolation(root, {name: tools[name] for name in ('one', 'two')},
                                   {'distribution': distribution}, _deadline=108)
            self.assertEqual(child.call_count, 1)


if __name__ == '__main__': unittest.main()

"""Focused selection, ownership and ordering controls; no signed guest claim."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import c_capsule_project
from tools.c_guest import closed_headers, threading
from tools.c_guest.compiler import Compiler
from tools.rust_capsule_project import inventory, snapshot
from tools.tests.test_c_threading_profile import graph


class ClosedHeadersTests(unittest.TestCase):
    def test_opt_in_captures_guard_and_requires_cooperative_profile(self):
        self.assertFalse(closed_headers.selected({}))
        with self.assertRaisesRegex(ValueError, 'require-cooperative-threading'):
            closed_headers.selected({'headerProfile': closed_headers.PROFILE})
        for bad in (None, True, [], 'signals'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'unsupported-c-header-profile'):
                closed_headers.selected({'headerProfile': bad})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = snapshot(c_capsule_project.create(root / 'plain', 'greeting', threading_profile=threading.PROFILE))
            self.assertNotIn('vendor/lsf/sdk/c-guest/' + closed_headers.GUARD, plain)
            selected = snapshot(c_capsule_project.create(root / 'selected', 'greeting',
                threading_profile=threading.PROFILE, header_profile=closed_headers.PROFILE))
            project, _, _ = c_capsule_project.validate(selected)
            self.assertTrue(closed_headers.selected(project))
            key = 'vendor/lsf/sdk/c-guest/' + closed_headers.GUARD
            self.assertIn(key, selected)
            self.assertIn('sdk/c-guest/' + closed_headers.GUARD,
                          c_capsule_project.authoring_inputs(c_capsule_project.ROOT))
            changed = dict(selected); changed[key] += b'\n'
            with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                c_capsule_project.validate(changed)
            missing = dict(selected); missing.pop(key)
            lock = json.loads(missing['sdk-lock.json'])
            vendor = {name.removeprefix('vendor/lsf/'): data for name, data in missing.items()
                      if name.startswith('vendor/lsf/')}
            lock['sdk'] = json.loads(inventory(vendor))
            missing['sdk-lock.json'] = json.dumps(lock).encode()
            with self.assertRaisesRegex(ValueError, 'require-captured-guard'):
                c_capsule_project.validate(missing)

    def test_reserved_defines_refuse_feature_and_symbol_overrides(self):
        closed_headers.check_defines(('ORDINARY=1', '_GNU_SOURCE=1'))
        for name in closed_headers.RESERVED:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'reserved-define'):
                closed_headers.check_defines((name + '=1',))

    def test_pins_stage_and_guard_object_are_rechecked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); zig = root / 'zig'; zig.write_bytes(b'zig')
            sdk = root / 'sdk'; (sdk / 'runtime').mkdir(parents=True)
            guard = sdk / closed_headers.GUARD; guard.write_bytes(b'guard-source')
            libc = root / 'lib/test.h'; libc.parent.mkdir(parents=True); libc.write_bytes(b'libc-header')
            fake_libc = {'original/signal.h': ('lib/test.h', __import__('hashlib').sha256(b'libc-header').hexdigest())}
            fake_guard = __import__('hashlib').sha256(b'guard-source').hexdigest()
            with patch.object(closed_headers, 'LIBC', fake_libc), patch.object(closed_headers, 'GUARD_DIGEST', fake_guard):
                boundary = closed_headers.prepare(zig, sdk)
                # A full stage has both expected directories even in this input double.
                copies = {**boundary.copies, 'bits/setjmp.h': b'bits'}
                boundary = closed_headers.Boundary(boundary.paths, boundary.materials, copies)
                stage = boundary.stage(root / 'generated')
                stage.check_unchanged()
                signal = stage.directory / 'signal.h'; original = signal.read_bytes()
                signal.write_bytes(original + b'\n')
                with self.assertRaisesRegex(ValueError, 'staged-input-changed'):
                    stage.check_unchanged()
                signal.write_bytes(original)
                (stage.directory / 'extra').mkdir()
                with self.assertRaisesRegex(ValueError, 'staged-input-changed'):
                    stage.check_unchanged()
                (stage.directory / 'extra').rmdir()
                (stage.directory / 'guard.o').write_bytes(b'compiled-guard')
                stage.accept_guard(); stage.check_unchanged()
                (stage.directory / 'guard.o').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'guard-object-changed'):
                    stage.check_unchanged()
                compiler = Compiler.__new__(Compiler)
                compiler.closed_header_boundary, compiler.closed_header_stage = boundary, stage
                compiler.isolation = SimpleNamespace(wrap=lambda *_args: self.fail('subprocess was reached'))
                with self.assertRaisesRegex(ValueError, 'guard-object-changed'):
                    compiler.run('zig', 'version')
                libc.write_bytes(b'changed-header')
                with self.assertRaisesRegex(ValueError, 'original-input-changed'):
                    boundary.check_unchanged()

    def test_selected_profile_requires_isolation_before_generation(self):
        compiler = Compiler.__new__(Compiler); compiler.isolation = None
        with patch('tools.c_guest.compiler.generate') as generate:
            with self.assertRaisesRegex(ValueError, 'require-captured-isolation'):
                compiler.compile([], Path('unused'), 'service', Path('unused-output'),
                    threading_profile=threading.PROFILE, header_profile=closed_headers.PROFILE)
            generate.assert_not_called()

    def test_guard_is_first_through_real_dependency_response_builder(self):
        class StopAtLink(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); sdk = c_capsule_project.ROOT / 'sdk/c-guest'
            app = root / 'main.c'; app.write_text('int app;\n')
            deps = []
            for number in range(65):
                item = root / f'dep{number:03}.c'; item.write_text('int value' + str(number) + ';\n'); deps.append(item)
            include = root / 'app-includes'; include.mkdir()
            guard = root / 'guard.o'; guard.write_bytes(b'guard')
            staged = root / 'owned-headers'; staged.mkdir()
            isolation = SimpleNamespace(receipt={}, observe_inputs=lambda _path: [], protect_inputs=lambda *_paths: None)
            compiler = Compiler.__new__(Compiler)
            compiler.paths = {'zig': root / 'zig', 'c-threading-transformer': root / 'transformer'}
            compiler.sdk, compiler.platform = sdk, None
            compiler.commands, compiler.isolation = None, isolation
            compiler.validate_static_libraries = lambda *_args: None
            compiler.select_closed_header_inputs = lambda: None
            compiler.closed_header_stage = SimpleNamespace(directory=staged)
            compiler.stage_closed_headers = lambda _destination: (guard, [])
            commands = []
            def run(tool, *args):
                if tool == 'wasm-tools':
                    return json.dumps(graph())
                self.assertEqual(tool, 'zig')
                if '-M' in args:
                    return ''
                if '-c' in args:
                    Path(args[args.index('-o') + 1]).write_bytes(b'owned-object')
                    return ''
                commands.append(args)
                raise StopAtLink()
            compiler.run = run
            def generate(_run, _wit, _world, destination, _platform, *, sync_core_abi=False):
                self.assertTrue(sync_core_abi); destination.mkdir()
                (destination / 'probe.c').write_text('int generated;\n')
                (destination / 'probe_component_type.o').write_bytes(b'generated')
                return destination, {}
            with patch('tools.c_guest.compiler.generate', generate), self.assertRaises(StopAtLink):
                compiler.compile([app, *deps], root / 'wit', 'service', root / 'output',
                    trap=False, include_directories=(include,), dependency_sources=tuple(deps),
                    threading_profile=threading.PROFILE, header_profile=closed_headers.PROFILE)
            command = commands[-1]
            responses = [value for value in command if value.startswith('@')]
            self.assertEqual(len(responses), 1)
            self.assertLess(command.index(str(guard)), command.index(str(app)))
            self.assertLess(command.index(str(guard)), command.index(responses[0]))
            self.assertLess(command.index(str(staged)), command.index(str(include)))
            response = Path(responses[0][1:]).read_text()
            self.assertIn('dependency-0000.o', response)
            self.assertIn('dependency-0064.o', response)
            self.assertNotIn(str(guard), response)
            self.assertNotIn('-Wl,--allow-undefined', command)
            self.assertNotIn('-Wl,--allow-multiple-definition', command)


if __name__ == '__main__':
    unittest.main()
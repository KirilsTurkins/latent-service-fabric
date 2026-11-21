"""Link-input binding controls; fixtures are Wasm metadata, not executions."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.java_guest import date_link_guard

from tools.java_guest.date_link_guard import OBJECTS, inspect_objects
from tools.tests.test_c_static_symbols import object_with, symbol


def objects():
    result = {name: object_with([symbol(0, 0, name.replace('.', '_'))]) for name in OBJECTS}
    result['main.o'] = object_with([symbol(0, 0, 'teavm_date_init')])
    return result


class DateLinkGuardTests(unittest.TestCase):
    def test_exact_input_set_accepts_and_missing_initializer_refuses(self):
        good = objects()
        self.assertEqual(set(inspect_objects(good)), set(OBJECTS))
        bad = dict(good)
        bad['main.o'] = object_with([symbol(0, 0, 'other')])
        with self.assertRaises(ValueError):
            inspect_objects(bad)
        del bad['bridge.o']
        with self.assertRaises(ValueError):
            inspect_objects(bad)

    def test_owned_date_link_uses_same_managed_stack_and_memory_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bindings = root / 'bindings'
            bindings.mkdir()
            projected = objects()
            for name in ('bridge.c', 'probe.c', 'probe.h'):
                (bindings / name).write_bytes(name.encode())
            (bindings / 'probe_component_type.o').write_bytes(projected['component.o'])
            libraries = []
            for name, _, _ in date_link_guard.LIBRARIES:
                data = name.encode()
                (root / name).write_bytes(data)
                libraries.append((name, name, hashlib.sha256(data).hexdigest()))
            calls = []

            def compile_object(*args, **kwargs):
                calls.append((args, kwargs))
                if args[0] != 'c-to-wasm':
                    target = args[args.index('-o') + 1]
                    target.write_bytes(projected[target.name])
                return ''

            snapshot = {'runtime/native.h': b'unchanged-sdk'}
            compiler = SimpleNamespace(sdk=root, wasi_sdk=root, original_sdk=snapshot,
                                       deadline=float('inf'), run=compile_object)
            with patch.object(date_link_guard, '_profile'), \
                    patch.object(date_link_guard, 'sdk_snapshot', return_value=snapshot), \
                    patch.object(date_link_guard, 'LIBRARIES', tuple(libraries)):
                receipt = date_link_guard.run(compiler, root / 'generated', (), root,
                                              root / 'core.wasm', b'sealed-input')
            args, kwargs = next(call for call in calls if call[0][0] == 'c-to-wasm')
            self.assertEqual(args[:2], ('c-to-wasm', 'clang'))
            self.assertIn('-Wl,--stack-first', args)
            self.assertEqual([arg for arg in args if str(arg).startswith('-Wl,-z,stack-size=')],
                             ['-Wl,-z,stack-size=131072'])
            self.assertEqual([arg for arg in args if str(arg).startswith('-Wl,--max-memory=')],
                             ['-Wl,--max-memory=67108864'])
            self.assertEqual(set(receipt['objects']), set(OBJECTS))
            self.assertEqual(receipt['sealedSha256'], hashlib.sha256(b'sealed-input').hexdigest())
            for name in OBJECTS:
                self.assertIn(root / 'date-link-inputs' / name, args)
            self.assertEqual(calls[0][1]['input_bytes'], b'sealed-input')

    def test_weak_local_common_and_strong_overrides_are_refused(self):
        for kind, flags in ((0, 0), (0, 1), (0, 2), (1, 3)):
            with self.subTest(kind=kind, flags=flags):
                changed = objects()
                changed['bridge.o'] = object_with([symbol(kind, flags, '__utc')])
                with self.assertRaises(ValueError):
                    inspect_objects(changed)
        changed = objects()
        changed['main.o'] = object_with([symbol(0, 0, 'teavm_date_init'), symbol(0, 2, 'timegm')])
        with self.assertRaises(ValueError):
            inspect_objects(changed)


if __name__ == '__main__':
    unittest.main()

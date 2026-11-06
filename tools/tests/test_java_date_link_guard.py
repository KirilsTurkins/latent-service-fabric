"""Link-input binding controls; fixtures are Wasm metadata, not executions."""
import unittest

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

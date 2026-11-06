"""Source-binding controls for the experimental finite Date initializer."""
import hashlib
import unittest
from unittest.mock import patch

from tools.java_guest import date_guard
from tools.java_guest.enum_guard import _directives


def fixture(call=True):
    block = (b'static time_t teavm_epochStart;\nstatic struct tm teavm_epochStartTm;\n'
             + date_guard.DATE_INIT + b'\nchar* teavm_date_format(int64_t time) { return 0; }')
    source = (b'typedef long long time_t;\n' + date_guard.TM_DECLARATION + b'\n'
              b'struct tm *localtime_r (const time_t *restrict, struct tm *restrict);\n'
              b'time_t timegm(struct tm *);\nextern void teavm_date_init();\n' + block + b'\n'
              + (date_guard.DATE_JAVA_CALLER.encode() + b'\n' if call else b''))
    return source, hashlib.sha256(block).hexdigest()


class DateGuardTests(unittest.TestCase):
    def guard(self, raw, expected, required=True):
        with patch.object(date_guard, 'DATE_BLOCK_SHA256', expected):
            return date_guard.seal(raw, _directives(raw, set()), required=required)

    def test_exact_source_is_replaced_and_unused_source_is_unchanged(self):
        raw, expected = fixture()
        result, receipt = self.guard(raw, expected)
        self.assertIsNotNone(receipt)
        self.assertEqual(result.count(date_guard.FINITE_INIT), 1)
        self.assertNotIn(date_guard.DATE_INIT, result)
        with self.assertRaisesRegex(ValueError, 'unobserved-call'):
            self.guard(raw, expected, required=False)
        raw, expected = fixture(call=False)
        self.assertEqual(self.guard(raw, expected, required=False), (raw, None))
        with self.assertRaisesRegex(ValueError, 'missing-required-call'):
            self.guard(raw, expected)
        raw += b'#define timegm unrelated\n'
        self.assertEqual(self.guard(raw, expected, required=False), (_directives(raw, set()), None))

    def test_changed_block_abi_and_extra_native_definitions_refuse(self):
        raw, expected = fixture()
        cases = [raw.replace(b'.tm_year = 70', b'.tm_year = 71'),
                 raw.replace(b'int __tm_nsec;', b'long long __tm_nsec;'),
                 raw + b'static long long timegm(void* p) { return 1; }\n',
                 raw + b'const char __utc[] = "other";\n',
                 raw + b'long long __tm_to_secs(void* p) { return 1; }\n',
                 raw + b'void another_caller(void) { teavm_date_init(); }\n',
                 raw.replace(date_guard.DATE_JAVA_CALLER.encode(),
                             date_guard.DATE_JAVA_CALLER.encode().replace(b'teavm_date_init();', b'unchecked_init();')),
                 raw + b'long __stack_pointer;\n', raw + b'__attribute__((weakref("timegm"))) int x;\n']
        for changed in cases:
            with self.subTest(changed=changed[-80:]), self.assertRaises(ValueError):
                self.guard(changed, expected)

    def test_protected_macro_and_unbound_checked_bytes_refuse(self):
        raw, expected = fixture()
        with self.assertRaises(ValueError):
            self.guard(b'#define timegm malicious\n' + raw, expected)
        with patch.object(date_guard, 'DATE_BLOCK_SHA256', expected), self.assertRaises(ValueError):
            date_guard.seal(raw, raw + b' ', required=True)


if __name__ == '__main__':
    unittest.main()

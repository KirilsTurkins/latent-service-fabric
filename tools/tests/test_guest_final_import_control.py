"""Finite binary controls only; these do not execute a guest or initializer."""
import unittest
from unittest.mock import patch

from tools import guest_final_import_control as control


# wasm-tools 1.254.0 parse of control.TEMPLATE, without names/custom sections.
TEMPLATE = bytes.fromhex(
    '0061736d0d00010007120142020140000100040005746f75636801000a2a010025'
    '646961676e6f737469633a756e6b6e6f776e2f66696e616c2d696d706f727440'
    '302e312e300500')


def section(kind, payload):
    return bytes([kind]) + control.leb(len(payload)) + payload


def name(value):
    raw = value.encode()
    return b'\0' + control.leb(len(raw)) + raw


class FinalImportControl(unittest.TestCase):
    def test_preserves_all_original_sections_and_changes_only_the_appended_type_index(self):
        original = control.COMPONENT + section(0, b'opaque original custom bytes')
        changed = control.append_unknown(original, TEMPLATE)
        self.assertEqual(changed[:len(original)], original)
        self.assertEqual(changed[len(original):], TEMPLATE[8:])
        self.assertEqual(len(changed) - len(original), 64)
        self.assertEqual([k for k, _ in control.sections(changed)], [0, 7, 10])

    def test_counts_only_outer_declarations_and_not_nested_instance_types(self):
        self.assertEqual(control.outer_type_count(TEMPLATE), 1)
        # The real template contains an instance type enclosing a function type.
        types = control.sections(TEMPLATE)[0][1]
        self.assertEqual(control.outer_type_count(control.COMPONENT + section(7, types)), 1)

    def test_counts_type_aliases_import_bounds_and_type_exports_in_one_outer_index_space(self):
        aliases = b'\x03\x03\x00\x00\x01a\x03\x02\x00\x00\x00\x00\x00\x00\x01b'
        imports = b'\x02' + name('equal') + b'\x03\x00\x00' + name('fresh') + b'\x03\x01'
        exports = b'\x02' + name('type') + b'\x03\x00\x00' + name('func') + b'\x01\x00\x01\x01\x00'
        raw = control.COMPONENT + section(6, aliases) + section(10, imports) + section(11, exports)
        self.assertEqual(control.outer_type_count(raw), 5)

    def test_multi_byte_type_index_does_not_rewrite_any_original_byte(self):
        original = control.COMPONENT + section(7, control.leb(128) + b'opaque bodies')
        changed = control.append_unknown(original, TEMPLATE)
        self.assertEqual(changed[:len(original)], original)
        self.assertTrue(changed.endswith(b'\x05\x80\x01'))
        self.assertEqual(len(changed) - len(original), 65)

    def test_unrelated_core_modules_and_components_are_opaque_and_never_run(self):
        raw = control.COMPONENT + section(1, b'opaque core bytes') + section(4, b'opaque nested component')
        self.assertEqual(control.outer_type_count(raw), 0)
        self.assertEqual(control.append_unknown(raw, TEMPLATE)[:len(raw)], raw)

    def test_truncated_oversized_or_unknown_outer_sections_refuse(self):
        bad = (b'', control.COMPONENT[:-1], control.COMPONENT + b'\x0c\x00',
               control.COMPONENT + b'\x00\x80', control.COMPONENT + b'\x00\x04x',
               control.COMPONENT + b'\x00\x80\x80\x80\x80\x10')
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                control.outer_type_count(raw)
        with patch.object(control, 'MAXIMUM', 8), self.assertRaises(ValueError):
            control.append_unknown(control.COMPONENT, TEMPLATE)
        with self.assertRaises(ValueError):
            control.outer_type_count(control.COMPONENT + section(0, b'') * 4097)
        with self.assertRaises(ValueError):
            control.outer_type_count(control.COMPONENT + section(7, control.leb(16385)))

    def test_extended_names_value_types_bad_aliases_and_trailing_import_bytes_refuse(self):
        payloads = ((10, b'\x01\x02\x00'),
                    (10, b'\x01' + name('value') + b'\x02\x00'),
                    (10, b'\x01' + name('type') + b'\x03\x02'),
                    (6, b'\x01\x03\x03\x00'),
                    (6, b'\x01\x00\x12\x00\x00\x00'),
                    (11, b'\x01' + name('func') + b'\x01\x00\x02'),
                    (10, b'\x00\x00'))
        for kind, payload in payloads:
            with self.subTest(kind=kind, payload=payload), self.assertRaises(ValueError):
                control.outer_type_count(control.COMPONENT + section(kind, payload))

    def test_wrong_template_import_count_name_kind_index_or_extra_sections_refuse(self):
        variants = [TEMPLATE.replace(b'diagnostic:', b'diagnostiX:', 1),
                    TEMPLATE[:-1] + b'\x01', TEMPLATE + section(0, b''),
                    TEMPLATE[:8], TEMPLATE.replace(b'\x0a\x2a\x01', b'\x0a\x2a\x02', 1)]
        for template in variants:
            with self.subTest(template=template), self.assertRaises(ValueError):
                control.append_unknown(control.COMPONENT, template)

    def test_integer_bounds_refuse_bool_negative_and_overflow(self):
        for value in (True, -1, 2**32, '1', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                control.leb(value)
        self.assertEqual(control.leb(0), b'\0')
        self.assertEqual(control.leb(2**32 - 1), b'\xff\xff\xff\xff\x0f')


if __name__ == '__main__':
    unittest.main()

"""Protocol controls for the mandatory host-derived original-read witness."""
import json
import unittest

from tools.go_network_read_barrier import EXPECTED, MAXIMUM_BARRIER_BYTES, MAXIMUM_OUTPUT_BYTES, read_barrier


class GoNetworkReadBarrierTests(unittest.TestCase):
    def output(self, row=None):
        return b'GO_NETWORK_READ_BARRIER ' + json.dumps(EXPECTED if row is None else row).encode() + b'\n'

    def test_exact_original_owner_and_released_short_read_are_required(self):
        self.assertEqual(read_barrier(b'other bounded output\n' + self.output()), EXPECTED)
        result = read_barrier(self.output())
        result['readAdmissions'] = 99
        self.assertEqual(read_barrier(self.output()), EXPECTED)
        self.assertNotIn('kernelRetirementQualified', result)
        self.assertNotIn('normalProviderInstalled', result)

    def test_missing_duplicate_and_empty_witnesses_are_not_success(self):
        for raw in (b'', b'GO_NETWORK_CASE {}\n', self.output() * 2,
                    b'GO_NETWORK_READ_BARRIER \n', self.output() + b'GO_NETWORK_READ_BARRIER\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_barrier(raw)

    def test_first_read_audit_and_failed_admission_cannot_impersonate_second_read(self):
        for changes in (
            {'readAdmissions': 1, 'readReleases': 0, 'releasedReadBytes': 0},
            {'readAdmissions': 2, 'readReleases': 1, 'releasedReadBytes': 0},
            {'readAdmissions': 2, 'readReleases': 2, 'pendingReads': 0},
            {'readAdmissions': 3, 'readReleases': 2},
            {'owners': 2, 'connections': 2},
            {'owners': 0, 'connections': 0},
            {'pendingOperations': 2},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_barrier(self.output(dict(EXPECTED, **changes)))

    def test_every_numeric_field_requires_its_exact_integer_not_a_boolean_or_float(self):
        for key, value in EXPECTED.items():
            if not isinstance(value, int):
                continue
            for replacement in (True, False, float(value), str(value), None, -1, value + 1):
                with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError):
                    read_barrier(self.output(dict(EXPECTED, **{key: replacement})))

    def test_missing_unknown_private_or_qualification_fields_are_rejected(self):
        for key in EXPECTED:
            row = dict(EXPECTED)
            del row[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                read_barrier(self.output(row))
        for key, value in (('destination', 'private.invalid'), ('payload', 'secret'),
                           ('kernelRetirementQualified', True), ('normalProviderInstalled', True)):
            with self.subTest(extra=key), self.assertRaises(ValueError):
                read_barrier(self.output(dict(EXPECTED, **{key: value})))
        with self.assertRaises(ValueError):
            read_barrier(self.output(dict(EXPECTED, case='fresh-after-cancel')))

    def test_malformed_json_duplicate_keys_and_wrong_shapes_fail_closed(self):
        duplicate = self.output().replace(b'"owners": 1', b'"owners": 2, "owners": 1')
        with self.assertRaisesRegex(ValueError, 'duplicate-field'):
            read_barrier(duplicate)
        for value in (b'{', b'null', b'[]', b'false', b'1', b'"text"', b'\xff'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_barrier(b'GO_NETWORK_READ_BARRIER ' + value + b'\n')

    def test_record_bound_is_independent_of_the_complete_native_log(self):
        raw = b'GO_NETWORK_READ_BARRIER ' + b' ' * (MAXIMUM_BARRIER_BYTES + 1) + b'\n'
        with self.assertRaisesRegex(ValueError, 'record-bound'):
            read_barrier(raw)

    def test_output_type_and_bound_are_checked_before_decoding(self):
        for raw in (self.output().decode(), bytearray(self.output()), None,
                    self.output() + b'x' * MAXIMUM_OUTPUT_BYTES):
            with self.subTest(kind=type(raw).__name__), self.assertRaisesRegex(ValueError, 'output-bound'):
                read_barrier(raw)
        padding = MAXIMUM_OUTPUT_BYTES - len(self.output())
        self.assertEqual(read_barrier(self.output() + b'x' * padding), EXPECTED)


if __name__ == '__main__':
    unittest.main()

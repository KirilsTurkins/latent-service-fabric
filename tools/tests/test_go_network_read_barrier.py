"""Behavioral controls for the production signed-Go transcript decoder."""
import json
import unittest

from tools import go_network_read_barrier as evidence
from tools.tests import test_go_network_runtime as samples


class GoNetworkReadBarrierTests(unittest.TestCase):
    def setUp(self):
        self.sample = samples.GoNetworkRuntimeTests()

    def test_current_transcript_keeps_both_edges_without_promoting_kernel_evidence(self):
        raw = self.sample.output()
        record = evidence.outcomes(raw)
        self.assertEqual([row['case'] for row in record['readEdges']],
                         ['fragmented-read', 'cancel-pending-read'])
        self.assertIs(record['completion']['normalProviderInstalled'], False)
        self.assertIs(record['completion']['kernelRetirementQualified'], False)
        self.assertEqual(evidence.SCHEMA_VERSION, 'latent.go.network.runtime.v3')
        # JSON key order and ordinary harness chatter are not protocol identity.
        rows = [(name, dict(reversed(list(row.items())))) for name, row in self.sample.rows()]
        self.assertEqual(evidence.outcomes(b'running 1 test\n' + self.sample.output(rows)
                                          + b'ordinary harness diagnostic\n'), record)

    def test_every_missing_duplicate_or_reordered_event_is_rejected(self):
        original = self.sample.rows()
        for index in range(len(original)):
            for operation in ('missing', 'duplicate', 'reordered'):
                rows = original.copy()
                if operation == 'missing':
                    rows.pop(index)
                elif operation == 'duplicate':
                    rows.insert(index, rows[index])
                else:
                    other = (index + 1) % len(rows)
                    rows[index], rows[other] = rows[other], rows[index]
                with self.subTest(index=index, operation=operation), self.assertRaises(ValueError):
                    evidence.outcomes(self.sample.output(rows))

    def test_malformed_extra_reserved_lines_cannot_disappear_from_the_event_stream(self):
        extras = (b'GO_NETWORK_READ_EDGE', b'GO_NETWORK_READ_EDGE\t{}',
                  b'GO_NETWORK_READ_EDGE ', b'GO_NETWORK_UNKNOWN {}', b'GO_NETWORK_case {}',
                  b' GO_NETWORK_CASE {}', b'\tGO_NETWORK_OWNER {}', b'GO_NETWORK_CASE2 {}',
                  b'GO_NETWORK_READ_BARRIER {}', b'GO_NETWORK_COMPLETE\r{}')
        for extra in extras:
            for before in (True, False):
                raw = extra + b'\n' + self.sample.output() if before else self.sample.output() + extra + b'\n'
                with self.subTest(extra=extra, before=before), self.assertRaises(ValueError):
                    evidence.outcomes(raw)

    def test_each_edge_field_is_closed_and_exactly_typed(self):
        rows = self.sample.rows()
        for index, (name, edge) in enumerate(rows):
            if name != 'GO_NETWORK_READ_EDGE':
                continue
            for key, expected in edge.items():
                invalid = [None, [], {}, 2**128]
                if type(expected) is int:
                    invalid += [bool(expected), float(expected), str(expected), expected + 1]
                elif type(expected) is bool:
                    invalid += [int(expected), not expected]
                else:
                    invalid += [False, 'other-case']
                for value in invalid:
                    changed = self.sample.rows()
                    changed[index][1][key] = value
                    with self.subTest(case=edge['case'], key=key, value=value), self.assertRaises(ValueError):
                        evidence.outcomes(self.sample.output(changed))
            changed = self.sample.rows()
            changed[index][1]['private'] = 'private.invalid'
            with self.assertRaises(ValueError):
                evidence.outcomes(self.sample.output(changed))

    def test_duplicate_json_fields_are_rejected_in_every_record_kind(self):
        for name in ('GO_NETWORK_OWNER', 'GO_NETWORK_CASE', 'GO_NETWORK_READ_EDGE', 'GO_NETWORK_CANCEL_EDGE', 'GO_NETWORK_COMPLETE'):
            raw = self.sample.output()
            begin = raw.index(name.encode() + b' ')
            end = raw.index(b'\n', begin)
            line = raw[begin:end]
            key = b'"cases"' if name.endswith('COMPLETE') else b'"case"'
            duplicate = line.replace(b'{', b'{' + key + b': null, ', 1)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'duplicate-observation-field'):
                evidence.outcomes(raw[:begin] + duplicate + raw[end:])
        escaped = self.sample.output().replace(b'"constructedReads": 2',
            b'"constructedReads": 2, "constructed\\u0052eads": 2', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate-observation-field'):
            evidence.outcomes(escaped)

    def test_invalid_json_shapes_encoding_and_nonfinite_numbers_fail_closed(self):
        raw = self.sample.output()
        begin = raw.index(b'GO_NETWORK_READ_EDGE ')
        end = raw.index(b'\n', begin)
        payloads = (b'null', b'[]', b'1', b'true', b'"private.invalid"', b'{',
                    b'{} {}', b'{"secret":"\xff"}', b'{"secret":NaN}',
                    b'{"secret":Infinity}', b'{"secret":-Infinity}')
        edge = next(row for name, row in self.sample.rows() if name == 'GO_NETWORK_READ_EDGE')
        payloads += tuple(json.dumps(edge).encode(encoding)
                          for encoding in ('utf-16', 'utf-16-le', 'utf-32'))
        for payload in payloads:
            changed = raw[:begin] + b'GO_NETWORK_READ_EDGE ' + payload + raw[end:]
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                evidence.outcomes(changed)

    def test_overdeep_record_fails_with_bounded_public_diagnostic(self):
        extra = b'GO_NETWORK_READ_EDGE ' + b'[' * 1200 + b'0' + b']' * 1200 + b'\n'
        with self.assertRaisesRegex(ValueError, '^Go-network-runtime-[a-z-]+$'):
            evidence.outcomes(self.sample.output() + extra)

    def test_output_record_and_event_count_bounds(self):
        for raw in (self.sample.output() + b'x' * evidence.MAXIMUM_OUTPUT_BYTES,
                    self.sample.output() + b'GO_NETWORK_CASE ' + b' ' * evidence.MAXIMUM_RECORD_BYTES + b'{}\n',
                    self.sample.output() + b'GO_NETWORK_OWNER {}\n'):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                evidence.outcomes(raw)
        for raw in (None, '', bytearray(self.sample.output())):
            with self.subTest(kind=type(raw)), self.assertRaises(ValueError):
                evidence.outcomes(raw)

    def test_filtered_count_requires_nonnegative_integer_and_matching_summary(self):
        for filtered in (False, True, 0.0, -1, '0', None):
            with self.subTest(filtered=filtered), self.assertRaises(ValueError):
                evidence.outcomes(self.sample.output(), filtered=filtered)
        raw = self.sample.output().replace(b'0 filtered out', b'17 filtered out')
        self.assertEqual(evidence.outcomes(raw, filtered=17), evidence.outcomes(self.sample.output()))

    def test_extra_failed_native_case_or_second_summary_cannot_be_hidden(self):
        raw = self.sample.output()
        for extra in (b'test other_case ... FAILED\n', b'test other_case ... ignored\n',
                      b'test other-case ... FAILED\n', b'test other/path.rs ... ignored\n',
                      b'test  ... FAILED\n', b'test\tother ... FAILED\n',
                      b' test other ... FAILED\n', b'test\n',
                      b' test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n',
                      b'test result: FAILED. 0 passed; 1 failed;\n',
                      raw[raw.index(b'test result:'):]):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                evidence.outcomes(raw + extra)

    def test_previous_twelve_case_transcript_is_not_current_read_edge_evidence(self):
        rows = [(name, row) for name, row in self.sample.rows()
                if name != 'GO_NETWORK_READ_EDGE' and row.get('case') != 'fragmented-read']
        rows[-1][1].update(cases=12, contacts=4)
        with self.assertRaises(ValueError):
            evidence.outcomes(self.sample.output(rows))

    def test_refusals_do_not_echo_private_record_contents(self):
        private = 'private.invalid/secret-token'
        rows = self.sample.rows()
        rows[1][1]['result'] = private
        with self.assertRaises(ValueError) as caught:
            evidence.outcomes(self.sample.output(rows))
        self.assertNotIn(private, str(caught.exception))
        malformed = self.sample.output() + b'GO_NETWORK_CASE {"' + private.encode() + b'":\n'
        with self.assertRaises(ValueError) as caught:
            evidence.outcomes(malformed)
        self.assertNotIn(private, str(caught.exception))
        self.assertNotIn(private, repr(caught.exception))


if __name__ == '__main__':
    unittest.main()

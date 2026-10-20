"""Closed source derivation and exact reached-Go error/execution controls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import go_closed_filesystem as closed
from tools import qualify_go_closed_filesystem as reference
from tools import sdk_scratch_fixture as fixture
from tools import sdk_scratch_probe as probe


def scratch_record():
    rows = [{'mode': mode, 'observation': {'category': 'path-error|errno=52', 'unsupported': True},
             'invocation': {'decoded': [{'ok': 'scratch|go|path-error|errno=52|fresh=1'}]}}
            for mode in ['open', 'create', 'temp']]
    return {'status': 'passed', 'language': 'go', 'filesystemGrantsAdded': False,
            'scratchStorageImplemented': False, 'invocations': 33,
            'inherited': {'originalInvocations': 27},
            'scratch': {'status': 'passed', 'language': 'go', 'allErrorsAreUnsupported': True, 'cases': rows}}


def adapter_rows():
    return [{'pathOpen': code, 'preopen': 8, 'mkdir': 76, 'socket': 76, 'read': 8, 'memoryBytes': 65536}
            for code in [76, 52]]


def output(rows):
    return (f'test {closed.ADAPTER_CASE} ... ok\n' +
            '\n'.join('GO_CLOSED_ADAPTER_CASE ' + json.dumps(row) for row in rows) +
            '\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 60 filtered out; finished in 0.02s\n').encode()


class GoClosedFilesystem(unittest.TestCase):
    def test_only_path_open_result_changes_from_the_authenticated_closed_preimage(self):
        original, current = closed.adapter_sources()
        self.assertEqual(hashlib.sha256(original).hexdigest(), closed.ORIGINAL_SHA256)
        self.assertEqual(original.replace(closed.OLD_OPEN, closed.CURRENT_OPEN), current)
        self.assertIn(b'(export "fd_prestat_get") (param i32 i32) (result i32) i32.const 8)', current)
        self.assertIn(b'(export "path_create_directory") (param i32 i32 i32) (result i32) i32.const 76)', current)
        self.assertEqual(current.count(b'(import '), 1)
        self.assertIn(b'(import "env" "memory" (memory 0))', current)

    def test_old_adapter_alias_or_any_unrelated_source_change_fails_before_execution(self):
        original, current = closed.adapter_sources()
        for raw in [original, current.replace(closed.CURRENT_OPEN, closed.CURRENT_OPEN.replace(b'52)', b'58)')),
                    current + b';; unreviewed\n', current.replace(b'i32.const 8)', b'i32.const 0)', 1)]:
            with self.subTest(digest=hashlib.sha256(raw).hexdigest()), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'sdk/go-guest/runtime/deny-wasi.wat'
                path.parent.mkdir(parents=True)
                path.write_bytes(raw)
                with self.assertRaisesRegex(RuntimeError, 'Go-closed-'):
                    closed.adapter_sources(root)

    def test_real_go_fixture_requires_standard_errors_Is_before_publishing_numeric_ENOSYS(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, record = fixture.project('go', Path(temporary) / 'application')
            source = (app / 'src/main.go').read_text()
            guard = 'if errno == syscall.ENOSYS && !errors.Is(err, errors.ErrUnsupported)'
            self.assertEqual(source.count(guard), 1)
            self.assertLess(source.index('errors.As(err, &errno)'), source.index(guard))
            self.assertLess(source.index(guard), source.index('strconv.FormatUint(uint64(errno),10)'))
            for operation in ['os.Open(', 'os.OpenFile(', 'os.CreateTemp(']:
                self.assertEqual(source.count(operation), 1)
            self.assertFalse(record['sdkProfileAndLimitsChanged'])
            self.assertFalse(record['filesystemGrantsAdded'])
            self.assertFalse(record['compilerExecuted'])

    def test_Go_ENOTSUP_is_not_standard_errors_Is_Unsupported_but_ENOSYS_is(self):
        for errno in probe.GO_ERRNOS:
            with self.subTest(errno=errno):
                row = probe.refusal('go', [{'ok': f'scratch|go|path-error|errno={errno}|fresh=1'}])
                self.assertEqual(row['unsupported'], errno == 52)
        self.assertFalse(probe.refusal('go', [{'ok': 'scratch|go|path-error|errno=58|fresh=1'}])['unsupported'])

    def test_strict_actual_packet_requires_all_three_exact_numeric_and_standard_Unsupported_results(self):
        record = scratch_record()
        actual = closed.strict_scratch_result(record)
        self.assertEqual([row['operation'] for row in actual['apiResults']], ['os.Open', 'os.OpenFile', 'os.CreateTemp'])
        self.assertTrue(all(row['errno'] == 52 and row['errorsIsUnsupported'] for row in actual['apiResults']))
        for update in ['missing', 'duplicate', 'alias58', 'notcapable', 'falseUnsupported', 'wrongDecoded']:
            changed = copy.deepcopy(record)
            rows = changed['scratch']['cases']
            if update == 'missing': rows.pop()
            if update == 'duplicate': rows[2] = copy.deepcopy(rows[0])
            if update == 'alias58': rows[0]['observation']['category'] = 'path-error|errno=58'
            if update == 'notcapable': rows[0]['observation']['category'] = 'path-error|errno=76'
            if update == 'falseUnsupported': rows[0]['observation']['unsupported'] = False
            if update == 'wrongDecoded': rows[0]['invocation']['decoded'] = [{'ok': 'scratch|go|unclassified'}]
            with self.subTest(update=update), self.assertRaisesRegex(RuntimeError, 'Go-scratch-'):
                closed.strict_scratch_result(changed)

    def test_original_normal_programme_and_all_six_calls_cannot_be_dropped_or_replaced_by_a_new_grant(self):
        for field, value in [('filesystemGrantsAdded', True), ('scratchStorageImplemented', True),
                             ('language', 'c'), ('status', 'in-progress'), ('invocations', 32)]:
            record = scratch_record()
            record[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'Go-scratch-'):
                closed.strict_scratch_result(record)

    def test_adapter_requires_both_real_old_current_results_and_unchanged_discovery_authority(self):
        self.assertEqual(reference.adapter_observations(output(adapter_rows()), 60), adapter_rows())
        for field, value in [('pathOpen', 58), ('preopen', 0), ('mkdir', 52), ('socket', 0),
                             ('memoryBytes', True), ('private', 'hidden')]:
            rows = adapter_rows()
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'Go-closed-adapter-'):
                reference.adapter_observations(output(rows), 60)
        for rows in [adapter_rows()[:-1], adapter_rows() + adapter_rows(), list(reversed(adapter_rows()))]:
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                reference.adapter_observations(output(rows), 60)

    def test_ignored_other_target_partial_execution_and_oversized_output_are_not_adapter_evidence(self):
        raw = output(adapter_rows())
        for old, new in [(closed.ADAPTER_CASE.encode(), b'other::target'), (b'0 ignored', b'1 ignored'),
                         (b'60 filtered', b'59 filtered'), (b'1 passed', b'2 passed')]:
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                reference.adapter_observations(raw.replace(old, new), 60)
        with self.assertRaisesRegex(RuntimeError, 'output-bound'):
            reference.adapter_observations(b'x' * (2 * 1024 * 1024 + 1), 60)


if __name__ == '__main__':
    unittest.main()

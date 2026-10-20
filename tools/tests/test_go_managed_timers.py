"""Actual v5 timer capture selection and fail-closed signed evidence controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_go_activation as activation
from tools import qualify_go_synchronization as reference


NATIVE17 = [0, 1, 2, 3, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17]


class SourceOnlyCompiler:
    def __init__(self, *_args, **_kwargs):
        self.materials = []

    def compile(self, _source, _wit, _world, output, **_kwargs):
        (output / 'runtime-overlay').mkdir(parents=True)
        (output / 'runtime-overlay/overlay.json').write_bytes(b'{"Replace":{}}')
        component = output / 'component.wasm'
        component.write_bytes(b'unit-test-input-only-no-native-execution')
        return component, {}


def rows():
    return [{'case': case, 'iteration': iteration, 'mode': mode, 'outcome': outcome}
            for case, iteration, mode, outcome in reference.MANAGED_TIMER_ROWS]


def output(values, filtered=50):
    records = '\n'.join('GO_MANAGED_TIMER_CASE ' + json.dumps(row) for row in values)
    return (f'test {reference.MANAGED_TIMER_CASE} ... ok\n{records}\n'
            f'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; {filtered} filtered out; finished in 6.00s\n').encode()


def compile_record(folder):
    source = (reference.ROOT / 'sdk/go-guest/runtime/timers-conformance/main.go').read_bytes()
    (folder / 'src').mkdir()
    (folder / 'src/main.go').write_bytes(source)
    (folder / 'build').mkdir()
    component = b'unit-test-source-control-only'
    (folder / 'build/component.wasm').write_bytes(component)
    return {'profile': 'go-component-activation-v5', 'fixture': 'timers',
            'sourceDigest': 'sha256:' + reference.digest(source), 'sourceUnchanged': True,
            'ordinarySource': True, 'signedExecution': 'not-run',
            'componentDigest': 'sha256:' + reference.digest(component),
            'bindingDigest': 'sha256:' + 'a' * 64, 'tools': [], 'transformations': [],
            'nativeReference': {'modes': NATIVE17, 'output': 42, 'freshProcessPerMode': True,
                                'sourceDigest': 'sha256:' + reference.digest(source)}}


class GoManagedTimers(unittest.TestCase):
    def test_v5_timer_compile_records_native_reference_on_the_same_unmodified_timer_source(self):
        source = (reference.ROOT / 'sdk/go-guest/runtime/timers-conformance/main.go').read_bytes()
        native = {'modes': NATIVE17, 'output': 42, 'freshProcessPerMode': True,
                  'sourceDigest': 'sha256:' + reference.digest(source)}
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), \
                patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value=native) as observe:
            folder = Path(temporary) / 'capture'
            record = activation.compile_fixture(folder, runtime_profile='go-component-activation-v5', fixture='timers')
            self.assertIn('nativeReference', record)
            self.assertEqual(record['nativeReference'], native)
            observe.assert_called_once()
            self.assertEqual(observe.call_args.args[-2:], (source, 'timers'))
            self.assertEqual((folder / 'src/main.go').read_bytes(), source)
            self.assertTrue(record['sourceUnchanged'])
            self.assertEqual(record['signedExecution'], 'not-run')

    def test_legacy_v3_reference_capture_remains_selected_and_not_relabelled(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(activation, 'Compiler', SourceOnlyCompiler), \
                patch.object(activation, 'stage'), \
                patch.object(activation, 'fixture_reference', return_value={'modes': NATIVE17}) as observe:
            record = activation.compile_fixture(Path(temporary) / 'legacy',
                                                 runtime_profile='go-component-activation-v3', fixture='timers')
            observe.assert_called_once()
            self.assertEqual(record['profile'], 'go-component-activation-v3')
            self.assertEqual(record['nativeReference']['modes'], NATIVE17)

    def test_exact_v5_timer_source_profile_and_all_seventeen_native_modes_are_required(self):
        self.assertEqual(reference.TIMER_NATIVE_MODES, NATIVE17)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record = compile_record(folder)
            path = folder / 'GO-ACTIVATION-COMPILE.json'
            path.write_bytes(json.dumps(record).encode())
            actual = reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timers')
            self.assertEqual(actual['sourceDigest'], record['sourceDigest'])
            for key, value in [('profile', 'go-component-activation-v3'), ('fixture', 'managed-idle'),
                               ('sourceUnchanged', False), ('signedExecution', 'passed')]:
                changed = copy.deepcopy(record)
                changed[key] = value
                path.write_bytes(json.dumps(changed).encode())
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source-or-profile'):
                    reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timers')
            for key, value in [('modes', [0, 1, 2]), ('modes', NATIVE17[:-1]),
                               ('freshProcessPerMode', False), ('output', 0), ('sourceDigest', 'sha256:' + 'b' * 64)]:
                changed = copy.deepcopy(record)
                changed['nativeReference'][key] = value
                path.write_bytes(json.dumps(changed).encode())
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'native-reference'):
                    reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v5', 'timers')

    def test_unknown_or_v3_profile_cannot_substitute_for_the_closed_managed_timer_campaign(self):
        fixture = Path('owned-timer-capture')
        self.assertEqual(reference.campaign('managed-timers', fixture, None),
                         {'case': reference.MANAGED_TIMER_CASE, 'fixture': 'timers',
                          'variable': 'LSF_GO_MANAGED_TIMER_FIXTURE', 'inputs': [(fixture, 'go-component-activation-v5')]})
        with self.assertRaisesRegex(ValueError, 'unreviewed-campaign-or-negative'):
            reference.campaign('managed-timers', fixture, Path('legacy-v3'))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record = compile_record(folder)
            (folder / 'GO-ACTIVATION-COMPILE.json').write_bytes(json.dumps(record).encode())
            with self.assertRaisesRegex(ValueError, 'unreviewed-source-profile'):
                reference.compile_identity(folder, reference.ROOT, 'go-component-activation-v3', 'timers')

    def test_all_forty_three_original_outcomes_cover_stop_reset_overlap_gc_and_retirement(self):
        values = rows()
        self.assertEqual(len(values), 43)
        self.assertEqual(reference.managed_timer_observations(output(values), 50), values)
        expected = {0, 1, 2, 3, 4, 5, 6, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}
        for iteration in (0, 1):
            self.assertEqual({r['mode'] for r in values if r['case'] == 'ordinary' and r['iteration'] == iteration}, expected)
        self.assertEqual([(r['case'], r['outcome']) for r in values[36:]],
                         [('timer-capacity', 'guest-trap'), ('fresh-after-timer-capacity', 'success'),
                          ('callback-failure', 'guest-trap'), ('fresh-after-callback-failure', 'success'),
                          ('cancel-original-root', 'cancelled'), ('deadline-original-root', 'deadline-exceeded'),
                          ('fresh-after-cancel-deadline', 'success')])

    def test_missing_duplicate_reordered_and_fake_elapsed_or_capacity_success_are_rejected(self):
        wrong = rows()
        wrong[-2]['outcome'] = 'success'
        capacity = rows()
        capacity[36]['outcome'] = 'success'
        for values in [rows()[:-1], rows() + rows()[:1], list(reversed(rows())), wrong, capacity]:
            with self.subTest(last=values[-1]), self.assertRaisesRegex(ValueError, 'missing-or-extra|invocation-contract'):
                reference.managed_timer_observations(output(values), 50)

    def test_private_unknown_boolean_and_unbounded_iteration_fields_fail_closed(self):
        for key, value in [('private', 'not-exported'), ('iteration', True), ('mode', False),
                           ('iteration', 2**64), ('outcome', 'invented'), ('case', 'unknown')]:
            values = rows()
            values[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'private-or-unknown|invocation-contract'):
                reference.managed_timer_observations(output(values), 50)

    def test_wrapper_success_other_target_or_ignored_cases_cannot_qualify_managed_timers(self):
        raw = output(rows())
        for old, new in [(reference.MANAGED_TIMER_CASE.encode(), reference.CASE.encode()),
                         (b'0 ignored', b'1 ignored'), (b'50 filtered', b'49 filtered'),
                         (b'1 passed', b'2 passed'), (b'GO_MANAGED_TIMER_CASE', b'GO_SYNCHRONIZATION_CASE')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                reference.managed_timer_observations(raw.replace(old, new), 50)
        with self.assertRaisesRegex(ValueError, 'output-bound'):
            reference.managed_timer_observations(b'x' * (2 * 1024 * 1024 + 1), 50)


if __name__ == '__main__':
    unittest.main()

"""Protocol boundaries for the actual captured Rust recovery programme."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import rust_dependency_recovery as suite


def failure(code, fuel=0):
    return {'exitCode': 4, 'processReaped': True, 'response': {'outcomeKnown': True,
        'category': 'platform-failure', 'error': {'code': code}, 'data': {
            'terminalState': code.replace('-', '_'), 'consumption': {'peakMemoryBytes': 4, 'cpuFuel': fuel}}}}


class RustDependencyRecovery(unittest.TestCase):
    def test_failure_requires_terminal_identity_reaping_and_original_memory_bound(self):
        good = failure('guest-trap')
        suite.failed(good, 'guest-trap', 4)
        for path, value in ((('exitCode',), 0), (('processReaped',), False),
                (('response', 'outcomeKnown'), False), (('response', 'category'), 'success'),
                (('response', 'error', 'code'), 'resource-exhausted'),
                (('response', 'data', 'terminalState'), 'resource_exhausted'),
                (('response', 'data', 'consumption', 'peakMemoryBytes'), 5)):
            row = copy.deepcopy(good)
            current = row
            for field in path[:-1]: current = current[field]
            current[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                suite.failed(row, 'guest-trap', 4)

    def run_control(self, mode='accepted'):
        activation = 'rust-library-observed-cancellation'
        client = SimpleNamespace(deadline=float('inf'), call=Mock())
        def control(*args, **kwargs):
            if args[:2] == ('activation', 'get'):
                return {'outcomeKnown': True, 'category': 'success', 'data': {
                    'activationId': activation if mode != 'foreign' else 'another',
                    'phase': 'running', 'terminalState': None}}
            return {'outcomeKnown': mode != 'unknown', 'data': {
                'activationId': activation, 'disposition': 'accepted'}}
        client.call.side_effect = control
        process = Mock()
        def invoked(_client, _target, _template, _function, args, _activation):
            if args == ['panic']: return failure('guest-trap')
            if args == ['memory']: return failure('resource-exhausted')
            if args == ['fuel']: return failure('resource-exhausted', 10_000_000)
            return {'exitCode': 0, 'processReaped': True, 'decoded': [{'ok': 'Hello, SDK!'}],
                'response': {'outcomeKnown': True}}
        patches = [patch.object(suite, 'call', side_effect=invoked),
            patch.object(suite, 'sample', return_value={'idle': True}),
            patch.object(suite, 'start_call', return_value=process),
            patch.object(suite, 'finish_call', return_value=failure('cancelled'))]
        return client, process, patches

    def test_all_four_faults_require_idle_and_fresh_component_calls(self):
        client, process, patches = self.run_control()
        with patches[0] as invoked, patches[1] as observed, patches[2] as started, patches[3] as finished:
            evidence = {'samples': []}
            rows = suite.recover(client, {'budget': {'memoryBytes': 4, 'cpuFuel': 100_000_000}}, None, evidence, 17)
        self.assertEqual([row['case'] for row in rows], ['rust-library-panic', 'rust-library-memory',
            'rust-library-fuel', 'rust-library-cancel'])
        self.assertEqual(len(evidence['samples']), 8)
        self.assertEqual(invoked.call_count, 7)
        self.assertEqual(observed.call_count, 8)
        self.assertEqual(started.call_count, 1)
        self.assertEqual(finished.call_count, 1)
        self.assertEqual([args[0][:2] for args in client.call.call_args_list],
            [('activation', 'get'), ('activation', 'cancel')])
        process.close.assert_called_once_with()
        self.assertEqual(rows[-1]['failure']['cancelCalls'], 1)
        self.assertEqual(started.call_args.args[4], ['spin'])
        fuel_call = next(row for row in invoked.call_args_list if row.args[4] == ['fuel'])
        self.assertEqual(fuel_call.args[1]['budget']['cpuFuel'], 10_000_000)

    def test_wrong_identity_and_unknown_cancel_never_retry_or_report_recovery(self):
        for mode, expected in (('foreign', 'rust-library-cancellation-identity'),
                ('unknown', 'rust-library-cancel-unconfirmed-no-replay')):
            client, process, patches = self.run_control(mode)
            with patches[0], patches[1], patches[2], patches[3] as finished:
                with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, expected):
                    suite.recover(client, {'budget': {'memoryBytes': 4, 'cpuFuel': 100_000_000}}, None, {'samples': []}, 17)
            process.close.assert_called_once_with()
            finished.assert_not_called()
            self.assertEqual(sum(call.args[:2] == ('activation', 'cancel') for call in client.call.call_args_list),
                int(mode == 'unknown'))

    def test_already_fuel_terminal_never_dispatches_cancellation_or_reports_recovery(self):
        client, process, patches = self.run_control()
        activation = 'rust-library-observed-cancellation'
        client.call.side_effect = lambda *args, **kwargs: {
            'outcomeKnown': True, 'category': 'success', 'data': {
                'activationId': activation, 'phase': 'running', 'terminalState': 'resource_exhausted'}}
        with patches[0], patches[1], patches[2], patches[3] as finished:
            with self.assertRaisesRegex(RuntimeError, 'rust-library-terminal-before-cancel'):
                suite.recover(client, {'budget': {'memoryBytes': 4, 'cpuFuel': 100_000_000}},
                              None, {'samples': []}, 17)
        client.call.assert_called_once_with('activation', 'get', activation, codes=(0, 6))
        process.close.assert_called_once_with()
        finished.assert_not_called()

    def test_actual_fixture_emits_zero_page_wasm_spin_and_preserves_resource_authority(self):
        import json
        from pathlib import Path
        import tempfile
        from tools import rust_dependency_fixture as fixture

        class NativeBoundaryReached(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); project = root / 'application'
            (project / 'src').mkdir(parents=True)
            limits = {'cpuFuel': 100_000_000, 'memoryBytes': 4_194_304, 'wallTimeLimitMillis': 1000,
                      'logBytes': 0, 'outboundRequests': 0, 'childCalls': 0}
            descriptor = {'limits': dict(limits), 'explicitAuthority': 'unchanged'}
            (project / 'capsule-project.json').write_text(json.dumps(descriptor))
            (project / 'src/lib.rs').write_bytes(
                b'pub fn greet(name: String) { Ok(format!("Hello, {name}!")) }')
            with patch.object(fixture.cargo_native_authoring, 'author', side_effect=NativeBoundaryReached) as native:
                with self.assertRaises(NativeBoundaryReached):
                    fixture.install(project, root / 'outside', root / 'unavailable-cargo')
            native.assert_called_once()
            self.assertEqual(native.call_args.kwargs['identity'], 'unicode-normalization')
            selected = json.loads((project / 'capsule-project.json').read_bytes())
            self.assertEqual(selected, {**descriptor, 'limits': {**limits, 'wallTimeLimitMillis': 5000}})
            source = (root / 'outside/developer-owned-library/src/lib.rs').read_text()
            spin = source.split('"spin" => loop {', 1)[1].split('        },', 1)[0]
            self.assertIn('#[cfg(target_arch = "wasm32")]', spin)
            self.assertIn('black_box(core::arch::wasm32::memory_grow::<0>(std::hint::black_box(0)))', spin)
            self.assertIn('#[cfg(not(target_arch = "wasm32"))]', spin)
            self.assertNotIn('vec!', spin)
            self.assertNotIn('copy_from_slice', spin)

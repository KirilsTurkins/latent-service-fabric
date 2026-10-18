"""Protocol boundaries for the actual captured Go recovery programme."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import go_dependency_recovery as suite


def failure(code, fuel=0):
    return {'exitCode': 4, 'processReaped': True, 'response': {'outcomeKnown': True,
        'category': 'platform-failure', 'error': {'code': code}, 'data': {
            'terminalState': code.replace('-', '_'), 'consumption': {'peakMemoryBytes': 4, 'cpuFuel': fuel}}}}


class GoDependencyRecovery(unittest.TestCase):
    def test_failure_requires_terminal_identity_reaping_and_original_memory_bound(self):
        good = failure('guest-trap')
        suite.failed(good, 'guest-trap', 4)
        for path, value in ((('exitCode',), 0), (('processReaped',), False),
                (('response', 'outcomeKnown'), False), (('response', 'category'), 'success'),
                (('response', 'error', 'code'), 'resource-exhausted'),
                (('response', 'data', 'terminalState'), 'resource_exhausted'),
                (('response', 'data', 'consumption', 'peakMemoryBytes'), 5),
                (('response', 'data', 'consumption', 'peakMemoryBytes'), -1)):
            row = copy.deepcopy(good)
            current = row
            for field in path[:-1]: current = current[field]
            current[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                suite.failed(row, 'guest-trap', 4)

    def run_control(self, mode='accepted'):
        activation = 'go-library-observed-cancellation'
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
            if args == ['fuel']: return failure('resource-exhausted',
                9_999_999 if mode == 'low-fuel' else 10_000_000)
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
        self.assertEqual([row['case'] for row in rows], ['go-library-panic', 'go-library-memory',
            'go-library-fuel', 'go-library-cancel'])
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
        for mode, expected in (('foreign', 'go-library-cancellation-identity'),
                ('unknown', 'go-library-cancel-unconfirmed-no-replay')):
            client, process, patches = self.run_control(mode)
            with patches[0], patches[1], patches[2], patches[3] as finished:
                with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, expected):
                    suite.recover(client, {'budget': {'memoryBytes': 4, 'cpuFuel': 100_000_000}}, None, {'samples': []}, 17)
            process.close.assert_called_once_with()
            finished.assert_not_called()
            self.assertEqual(sum(call.args[:2] == ('activation', 'cancel') for call in client.call.call_args_list),
                int(mode == 'unknown'))

    def test_fuel_case_requires_exact_lowered_budget_consumption(self):
        client, process, patches = self.run_control('low-fuel')
        with patches[0], patches[1], patches[2] as started, patches[3]:
            with self.assertRaisesRegex(RuntimeError, 'go-library-fuel-limit-not-consumed'):
                suite.recover(client, {'budget': {'memoryBytes': 4, 'cpuFuel': 100_000_000}},
                    None, {'samples': []}, 17)
        started.assert_not_called()
        client.call.assert_not_called()


class GoCancellationWorkload(unittest.TestCase):
    def test_generated_external_workload_uses_value_dependent_scalar_work_without_waits(self):
        import tempfile
        from pathlib import Path
        from tools import go_dependency_fixture as fixture

        class StopBeforeNativeAuthoring(Exception):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'application'
            (project / 'src').mkdir(parents=True)
            (project / 'src/main.go').write_bytes(b'package main\nimport (\n)\nfunc greet(name string) string { return "Hello, " + name + "!" }\n')
            with patch.object(fixture.native_authoring, 'edit', side_effect=StopBeforeNativeAuthoring) as native:
                with self.assertRaises(StopBeforeNativeAuthoring):
                    fixture.install(project, root / 'outside', root / 'not-executed-go')
            native.assert_called_once()
            generated = (root / 'outside/developer-owned-library/prefix.go').read_text(encoding='utf-8')
        spin = generated.split('case "spin":', 1)[1].split('//go:generate', 1)[0]
        # Bulk memory.copy is priced per byte in the pinned engine. The cancel
        # fixture must exercise ordinary scalar instructions at the same limits.
        self.assertIn('source := make([]byte, 128*1024)', spin)
        self.assertIn('destination := make([]byte, len(source))', spin)
        self.assertIn('for index := range destination', spin)
        self.assertIn('destination[index] = source[index] ^ byte(calls)', spin)
        self.assertIn('calls++', spin)
        self.assertIn('runtime.KeepAlive(destination)', spin)
        for forbidden in ('copy(', 'clear(', 'time.Sleep(', 'Gosched(', 'select', 'chan '):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, spin)
        self.assertIn('//go:build sdk_dependency_qualification', generated)
        self.assertIn('case "fuel":\n        for { calls++ }', generated)

    def test_known_terminal_fuel_exhaustion_cannot_qualify_as_cancellation(self):
        client, process, patches = GoDependencyRecovery().run_control()
        original = client.call.side_effect

        def already_terminal(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[:2] == ('activation', 'cancel'):
                result['data'].update(disposition='already_terminal', terminalState='resource_exhausted')
            return result

        client.call.side_effect = already_terminal
        with patches[0] as invoked, patches[1], patches[2] as started, patches[3] as finished:
            with self.assertRaisesRegex(RuntimeError, 'go-library-cancel-unconfirmed-no-replay'):
                suite.recover(client, {'budget': {'memoryBytes': 4, 'cpuFuel': 100_000_000}},
                              None, {'samples': []}, 17)
        self.assertEqual(started.call_count, 1)
        self.assertEqual(invoked.call_count, 6)
        finished.assert_not_called()
        process.close.assert_called_once_with()
        self.assertEqual(sum(row.args[:2] == ('activation', 'cancel') for row in client.call.call_args_list), 1)

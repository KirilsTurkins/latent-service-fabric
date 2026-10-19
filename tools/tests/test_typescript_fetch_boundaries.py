"""Pure wrapper guards; actual native/signed evidence must come from hosted execution."""
from contextlib import ExitStack
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import diagnose_typescript_fetch_boundaries as boundaries
from tools.phase2_operator_process import WorkflowError


class FetchBoundaries(unittest.TestCase):
    def test_old_sdk_wrapper_adds_strict_zero_io_probes_without_replacing_original_json_gate(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                sources = root/'probes'
                sources.mkdir()
                source = {name: name.encode() for name in ('main.ts', 'default-client.ts')}
                for name, raw in source.items():
                    (sources/name).write_bytes(raw)
                app = root/'app'
                (app/'src').mkdir(parents=True)
                lock = {'template': {'sourceDigest': 'original', 'witDigest': 'unchanged'}, 'sdk': 'old-exact'}
                (app/'sdk-lock.json').write_text(json.dumps(lock))
                binary = root/'latentd'
                binary.write_bytes(b'original-host')
                configured = {'maximumCpuFuel': 10000000000, 'maximumWallTimeMillis': 120000,
                              'maximumLogBytes': 16384}
                config = root/'node.json'
                config.write_text(json.dumps({'execution': configured, 'credentials': 'private-never-export'}))
                client = SimpleNamespace(directory=root/'client')
                client.directory.mkdir()
                fields = json.loads((boundaries.ROOT/'examples/echo-contract/deployment.json').read_bytes())['spec']['resources']
                budget = {**{name: 0 for name in fields}, 'cpuFuel': 1000000000,
                          'memoryBytes': 134217728, 'wallTimeLimitMillis': 120000}
                node = object()
                calls = []

                def original_call(client, target, template, function, arguments, activation):
                    calls.append((template, function, arguments, activation))
                    (client.directory/(activation+'-budget.json')).write_text(json.dumps(budget))
                    if arguments[0] == 0:
                        return {'exitCode': 4, 'decoded': None}
                    expected = {3: 'promise-ready', 4: 'request-copy-ready'}[arguments[0]]
                    return {'exitCode': 0, 'decoded': ['wrong' if invalid else expected], 'processReaped': True,
                        'response': {'outcomeKnown': True, 'data': {'consumption': {
                            'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}}

                def original_qualify(output, tools, engine, splicer, prepared):
                    captured = boundaries.fetch.project(app)
                    self.assertEqual(captured, app)
                    self.assertEqual({name: (app/'src'/name).read_bytes() for name in source}, source)
                    updated = json.loads((app/'sdk-lock.json').read_bytes())
                    self.assertEqual(updated['sdk'], lock['sdk'])
                    self.assertEqual(updated['template']['witDigest'], lock['template']['witDigest'])
                    boundaries.fetch.connect(client, binary, root, config, 'examples', 1)
                    row = boundaries.fetch.call(client, 'target', 'typescript-fetch', 'run',
                        [0, 'http://127.0.0.1/conformance/json'], 'fetch-json')
                    boundaries.fetch.require_result(row, 'unchanged-exact-json', 1)
                    return {'status': 'passed'}

                for name, value in (('project', Mock(return_value=app)), ('call', original_call),
                                    ('connect', Mock(return_value=node)), ('qualify', original_qualify),
                                    ('Probe', Mock(return_value='actual-owned-probe')), ('retire', Mock()),
                                    ('validate', Mock()), ('snapshot', Mock(return_value={}))):
                    stack.enter_context(patch.object(boundaries.fetch, name, value))
                stack.enter_context(patch.object(boundaries, 'run_bounded_result',
                    return_value=SimpleNamespace(returncode=0, stdout=boundaries.TESTED.encode())))
                record = boundaries.run(sources, root/'native', root/'engine', root/'splicer', root/'tools', root/'output')
                self.assertFalse(record['qualification'])
                self.assertFalse(record['currentHeadQualification'])
                self.assertEqual(record['failureClass'], 'WorkflowError')
                self.assertTrue(record['applicationSourceUnchanged'])
                self.assertEqual(record['actualNodeExecutionLimits'], configured)
                self.assertNotIn('private-never-export', json.dumps(record))
                self.assertEqual(record['actualInvocationBudgets']['fetch-promise-ready'], budget)
                self.assertEqual([call[2][0] for call in calls], [3] if invalid else [3, 4, 0])
                self.assertEqual(boundaries.fetch.retire.call_count, 0 if invalid else 2)
                if not invalid:
                    self.assertEqual(record['actualInvocationBudgets']['fetch-json']['cpuFuel'], 1000000000)
                    self.assertEqual(calls[-1], ('typescript-fetch', 'run',
                        [0, 'http://127.0.0.1/conformance/json'], 'fetch-json'))
                self.assertIs(boundaries.fetch.call, original_call)

    def test_emitted_budget_capture_preserves_large_fuel_and_rejects_private_unknown_or_noninteger_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'budget.json'
            fields = {'cpuFuel', 'memoryBytes'}
            expected = {'cpuFuel': 1000000000, 'memoryBytes': 134217728}
            path.write_text(json.dumps(expected))
            self.assertEqual(boundaries.numeric_fields(path, fields), expected)
            for value in ({**expected, 'private': 'credential'}, {**expected, 'cpuFuel': True},
                          {**expected, 'cpuFuel': 'private-value'}, {**expected, 'cpuFuel': 2**64}):
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, 'numeric-budget-fields'):
                    boundaries.numeric_fields(path, fields)


if __name__ == '__main__':
    unittest.main()

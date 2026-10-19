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
                node = object()
                calls = []

                def original_call(client, target, template, function, arguments, activation):
                    calls.append((template, function, arguments, activation))
                    if arguments[0] == 0:
                        raise WorkflowError('original-json-still-fails')
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
                    boundaries.fetch.connect('client', binary)
                    return boundaries.fetch.call('client', 'target', 'typescript-fetch', 'run',
                        [0, 'http://127.0.0.1/conformance/json'], 'fetch-json')

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
                self.assertEqual([call[2][0] for call in calls], [3] if invalid else [3, 4, 0])
                self.assertEqual(boundaries.fetch.retire.call_count, 0 if invalid else 2)
                if not invalid:
                    self.assertEqual(calls[-1], ('typescript-fetch', 'run',
                        [0, 'http://127.0.0.1/conformance/json'], 'fetch-json'))
                self.assertIs(boundaries.fetch.call, original_call)


if __name__ == '__main__':
    unittest.main()

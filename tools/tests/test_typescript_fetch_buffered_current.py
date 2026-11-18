"""Same-source orchestration controls; signed execution is a separate workflow."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools import qualify_typescript_fetch_buffered_current as current
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.standard_http.peer import Peer
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')


class CurrentBufferedFetchTests(unittest.TestCase):
    def execution(self):
        with closing(Peer(b'Bearer ' + b'0'*64, maximum_seconds=5)) as peer:
            peer.close()
            observation = peer.observation()
        rows = current.buffered.vectors()
        cases = [{'name': name, 'outbound': outbound, 'result': result}
                 for name, _mode, _vector, result, outbound in rows]
        cases.append({'name': 'fresh-after-lifecycle', 'outbound': 0, 'result': rows[0][3]})
        return {'status': 'passed', 'fullTicketQualification': False,
                'networkStreamingQualified': False, 'crossTenantQualified': False,
                'bufferedOnly': True, 'signedExecution': 'passed', 'providerExecution': 'passed',
                'cases': cases, 'shutdown': {'reaped': True, 'record': {'clean': True}},
                'peer': observation}

    def test_every_original_vector_and_real_retirement_are_required(self):
        valid = self.execution()
        self.assertEqual(len(current.require_execution(valid)), 8)
        for name, value in (('status', 'failed'), ('fullTicketQualification', True),
                            ('networkStreamingQualified', True), ('crossTenantQualified', True),
                            ('bufferedOnly', False), ('signedExecution', 'not-run'),
                            ('providerExecution', 'not-run'), ('cases', valid['cases'][:-1])):
            with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'original-cases-required'):
                current.require_execution({**valid, name: value})
        for field, replacement in (('name', 'changed'), ('result', 'changed'), ('outbound', 1)):
            changed = deepcopy(valid)
            changed['cases'][5][field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(WorkflowError, 'original-cases-required'):
                current.require_execution(changed)
        with self.assertRaisesRegex(WorkflowError, 'clean-shutdown'):
            current.require_execution({**valid, 'shutdown': {'reaped': False, 'record': {'clean': True}}})
        with self.assertRaises((WorkflowError, ValueError)):
            current.require_execution({**valid, 'peer': {**valid['peer'], 'acceptedConnections': 1}})

    def test_opt_in_lane_uses_same_run_producers_and_preserves_failure_evidence(self):
        workflow = yaml.load((ROOT/'.github/workflows/typescript-guest.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['workflow_dispatch']['inputs']['qualify-current-buffered-fetch']['default'], 'false')
        job = workflow['jobs']['current-buffered-fetch']
        self.assertEqual(job['needs'], ['boundary', 'source-splicer', 'promise-library'])
        self.assertIn("github.ref == 'refs/heads/development'", job['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
        self.assertIn('inputs.qualify-current-buffered-fetch', job['if'])
        for other in ('current-borrow', 'current-published-fetch'):
            self.assertIn('!inputs.qualify-' + other, job['if'])
        for other in ('current-signed-borrow', 'current-published-fetch', 'fetch-component'):
            self.assertIn('!inputs.qualify-current-buffered-fetch', workflow['jobs'][other]['if'])
        self.assertIn("${{ inputs.qualify-current-buffered-fetch && '-current-buffered-fetch' || '' }}",
                      workflow['concurrency']['group'])
        downloads = [step['with']['name'] for step in job['steps']
                     if step.get('uses', '').startswith('KirilsTurkins/lsf-download-artifact@')]
        self.assertEqual(downloads, ['typescript-source-splicer-input-${{ github.sha }}',
            'typescript-fetch-engine-input-${{ github.sha }}', 'typescript-fetch-native-input-${{ github.sha }}'])
        self.assertTrue(all('run-id' not in step.get('with', {}) for step in job['steps']))
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn('tools/qualify_typescript_fetch_buffered_current.py', commands)
        for unwanted in ('typescript_fetch_replay_inputs.py', 'qualify_host_codec_native.py',
                         'test_typescript_dom_exception_ownership', 'test_rust_thread_object_graph'):
            self.assertNotIn(unwanted, commands)
        owner = next(step for step in workflow['jobs']['boundary']['steps']
                     if step.get('name') == 'Check original and current-source buffered Fetch controls')
        self.assertNotIn('if', owner)
        self.assertIn('tools.tests.test_typescript_fetch_buffered_current', owner['run'])
        retained = next(step for step in job['steps'] if step.get('name') ==
                        'Retain current-source attempts and original buffered outcomes')
        self.assertEqual(retained['if'], 'always()')
        self.assertIn('typescript-current-buffered/node/*.json', retained['with']['path'])
        self.assertIn('typescript-current-buffered/build/logs/**', retained['with']['path'])

    def test_same_source_inputs_and_exact_buffered_selection_reach_existing_executor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools, engine, splicer, prepared = (root/name for name in ('tools', 'engine', 'splicer', 'prepared'))
            for path in (tools, engine, splicer, prepared):
                path.mkdir()
            engine_input, splicer_input = {'core': 'current'}, {'compiler': 'current'}
            write_json(engine/'engine-input.json', engine_input)
            write_json(splicer/'splicer-input.json', splicer_input)
            originals = {}
            for name in current.base.PRODUCTS:
                originals[name] = prepared/name
                originals[name].write_bytes(('native-' + name).encode())
            source = {'commit': 'a'*40, 'tree': 'b'*40, 'workflowOrigin': {}}
            compiler, native_identity = {'engine': 'current'}, {'native': 'current'}
            calls = []
            valid = self.execution()

            def project(path):
                path.mkdir()
                (path/'main.ts').write_text('original buffered source')
                return path

            def build(app, output, contracts, package, repository, **kwargs):
                calls.append(('build', kwargs['runtime_engine'], kwargs['runtime_splicer']))
                output.mkdir()
                write_json(output/'typescript-runtime-selection.json',
                    {'profile': IMPORT_PROFILE,
                     'engineInput': engine_input, 'compilerSplicerInput': splicer_input})
                return output

            def execute(artifact, native, output, *, buffered_only):
                calls.append(('execute', artifact, set(native), buffered_only))
                output.mkdir()
                write_json(output/'qualification.json', valid)
                return deepcopy(valid)

            with patch.object(current.sys, 'platform', 'linux'), \
                    patch.object(current.platform, 'machine', return_value='x86_64'), \
                    patch.object(current, 'source_identity', return_value=source), \
                    patch.object(current, 'source_products', return_value=compiler), \
                    patch.object(current.base, 'prepared_native', return_value=(originals, native_identity)), \
                    patch.object(current.base, 'build_evidence', return_value={'component': 'actual'}), \
                    patch.object(current.buffered, 'project', side_effect=project), \
                    patch.object(current, 'build', side_effect=build), \
                    patch.object(current.conformance, 'execute', side_effect=execute) as run:
                result = current.qualify(tools, engine, splicer, prepared, root/'output')
                def incomplete(*args, **kwargs):
                    value = execute(*args, **kwargs)
                    value['cases'].pop()
                    return value
                run.side_effect = incomplete
                with self.assertRaisesRegex(WorkflowError, 'original-cases-required'):
                    current.qualify(tools, engine, splicer, prepared, root/'failed-output')
                def changed_native(artifact, native, output, *, buffered_only):
                    value = execute(artifact, native, output, buffered_only=buffered_only)
                    native['latentd'].write_bytes(b'tampered')
                    return value
                run.side_effect = changed_native
                with self.assertRaisesRegex(WorkflowError, 'inputs-changed'):
                    current.qualify(tools, engine, splicer, prepared, root/'failed-native')
            self.assertEqual(result['status'], 'passed')
            self.assertIs(result['fullTicketQualification'], False)
            self.assertEqual(result['compilerProducts'], compiler)
            self.assertEqual(result['nativeProducts'], native_identity)
            self.assertEqual(calls[0], ('build', engine/'engine.wasm', splicer/'splicer'))
            self.assertEqual(calls[1][0], 'execute')
            self.assertEqual(calls[1][2:], (set(current.base.PRODUCTS), True))
            self.assertFalse((root/'failed-output/BUFFERED-FETCH-CURRENT.json').exists())
            failure = json.loads((root/'failed-output/FAILED.json').read_bytes())
            self.assertEqual((failure['status'], failure['stage']), ('failed', 'signed-provider-execution'))
            self.assertFalse((root/'failed-native/BUFFERED-FETCH-CURRENT.json').exists())
            failure = json.loads((root/'failed-native/FAILED.json').read_bytes())
            self.assertEqual((failure['status'], failure['stage']), ('failed', 'final-input-check'))

    def test_compiler_drift_cannot_reach_execution_or_report_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools, engine, splicer, prepared = (root/name for name in ('tools', 'engine', 'splicer', 'prepared'))
            for path in (tools, engine, splicer, prepared):
                path.mkdir()
            originals = {name: prepared/name for name in current.base.PRODUCTS}
            for path in originals.values():
                path.write_bytes(b'original')
            with patch.object(current.sys, 'platform', 'linux'), \
                    patch.object(current.platform, 'machine', return_value='x86_64'), \
                    patch.object(current, 'source_identity', return_value={'commit': 'a'*40}), \
                    patch.object(current, 'source_products', side_effect=ValueError('compiler-drift')), \
                    patch.object(current.conformance, 'execute') as execute:
                with self.assertRaisesRegex(ValueError, 'compiler-drift'):
                    current.qualify(tools, engine, splicer, prepared, root/'failed-compiler')
                execute.assert_not_called()
            failure = json.loads((root/'failed-compiler/FAILED.json').read_bytes())
            self.assertEqual((failure['status'], failure['stage']), ('failed', 'same-run-products'))
            self.assertFalse((root/'failed-compiler/BUFFERED-FETCH-CURRENT.json').exists())


if __name__ == '__main__':
    unittest.main()

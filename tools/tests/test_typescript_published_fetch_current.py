"""Current-product and orchestration controls, not signed execution evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools import qualify_typescript_published_fetch_current as current
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')


class CurrentPublishedFetchTests(unittest.TestCase):
    def execution(self):
        return {'status': 'passed', 'fullTicketQualification': False,
            'signedExecution': 'passed', 'providerExecution': 'passed',
            'diagnosticOwnerProfile': False, 'failedClientCases': [],
            'cases': ['buffered-reader-probe', 'buffered-json-probe'] +
                     [row[0] for row in current.published.VECTORS]}

    def test_every_original_client_case_and_real_provider_are_required(self):
        valid = self.execution()
        classified = current.require_execution(valid)
        self.assertEqual(classified['expectedUnsupportedCases'], ['ky-http404-unsupported'])
        self.assertNotIn('ky-http404-unsupported', classified['passedCases'])
        for name, value in (('status', 'failed'), ('fullTicketQualification', True), ('signedExecution', 'not-run'),
                ('providerExecution', 'not-run'), ('diagnosticOwnerProfile', True),
                ('failedClientCases', ['ky-json']), ('cases', valid['cases'][:-1])):
            with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'original-cases-required'):
                current.require_execution({**valid, name: value})

    def test_packaged_component_requires_both_exact_compiler_input_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact, engine, splicer = (root/name for name in ('artifact', 'engine', 'splicer'))
            for path in (artifact, engine, splicer):
                path.mkdir()
            engine_input, splicer_input = {'core': 'original'}, {'compiler': 'original'}
            write_json(engine/'engine-input.json', engine_input)
            write_json(splicer/'splicer-input.json', splicer_input)
            selected = {'profile': current.IMPORT_PROFILE, 'engineInput': engine_input,
                        'compilerSplicerInput': splicer_input}
            write_json(artifact/'typescript-runtime-selection.json', selected)
            with patch.object(current.base, 'build_evidence', return_value={'component': 'actual'}):
                self.assertEqual(current.selected_build(artifact, engine, splicer), {'component': 'actual'})
                for name in ('profile', 'engineInput', 'compilerSplicerInput'):
                    changed = deepcopy(selected)
                    changed[name] = 'different'
                    write_json(artifact/'typescript-runtime-selection.json', changed)
                    with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'actual-engine-and-splicer'):
                        current.selected_build(artifact, engine, splicer)

    def test_workflow_uses_only_the_three_existing_same_run_producers(self):
        workflow = yaml.load((ROOT/'.github/workflows/typescript-guest.yml').read_text(), Loader=yaml.BaseLoader)
        selected = workflow['on']['workflow_dispatch']['inputs']['qualify-current-published-fetch']
        self.assertEqual(selected['default'], 'false')
        job = workflow['jobs']['current-published-fetch']
        self.assertEqual(job['needs'], ['boundary', 'source-splicer', 'promise-library'])
        self.assertIn("github.ref == 'refs/heads/development'", job['if'])
        self.assertIn('inputs.qualify-current-published-fetch', job['if'])
        self.assertIn('!inputs.qualify-current-borrow', job['if'])
        self.assertEqual(workflow['concurrency']['group'],
            "typescript-guest-${{ github.ref }}${{ inputs.qualify-current-borrow && '-current-borrow' || '' }}"
            "${{ inputs.qualify-current-published-fetch && '-current-published-fetch' || '' }}")
        self.assertIn('!inputs.qualify-current-published-fetch', workflow['jobs']['current-signed-borrow']['if'])
        downloads = [step['with']['name'] for step in job['steps']
                     if step.get('uses', '').startswith('KirilsTurkins/lsf-download-artifact@')]
        self.assertEqual(downloads, ['typescript-source-splicer-input-${{ github.sha }}',
            'typescript-fetch-engine-input-${{ github.sha }}', 'typescript-fetch-native-input-${{ github.sha }}'])
        self.assertTrue(all('run-id' not in step.get('with', {}) for step in job['steps']))
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        for unwanted in ('typescript_fetch_replay_inputs.py', 'build_typescript_native_engine.py',
                'build_typescript_source_splicer.py', 'qualify_host_codec_native.py',
                'test_rust_thread_object_graph', 'compile_rust_thread_http_sibling.py'):
            self.assertNotIn(unwanted, commands)
        self.assertIn('!inputs.qualify-current-published-fetch', workflow['jobs']['fetch-component']['if'])

    def test_two_variants_use_same_validated_products_and_no_fake_pass(self):
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

            def project(path, name):
                path.mkdir()
                (path/'main.ts').write_text(name)
                return path

            def build(app, output, contracts, package, repository, **kwargs):
                calls.append(('build', kwargs['runtime_engine'], kwargs['runtime_splicer']))
                output.mkdir()
                write_json(output/'typescript-runtime-selection.json', {'profile': current.IMPORT_PROFILE,
                    'engineInput': engine_input, 'compilerSplicerInput': splicer_input})
                return output

            def execute(artifact, native, output):
                calls.append(('execute', artifact, set(native)))
                output.mkdir()
                write_json(output/'qualification.json', self.execution())
                return self.execution()

            with patch.object(current.sys, 'platform', 'linux'), \
                    patch.object(current.platform, 'machine', return_value='x86_64'), \
                    patch.object(current, 'source_identity', return_value=source), \
                    patch.object(current, 'source_products', return_value=compiler), \
                    patch.object(current.base, 'prepared_native', return_value=(originals, native_identity)), \
                    patch.object(current.base, 'build_evidence', return_value={'component': 'actual'}), \
                    patch.object(current.fixture, 'project', side_effect=project), \
                    patch.object(current.fixture, 'capture', return_value={'defaultGlobals': True}), \
                    patch.object(current, 'build', side_effect=build), \
                    patch.object(current.published, 'execute', side_effect=execute) as run:
                result = current.qualify(tools, engine, splicer, prepared, root/'output')
                def incomplete(artifact, native, output):
                    row = execute(artifact, native, output)
                    return {**row, 'cases': row['cases'][:-1]}
                run.side_effect = incomplete
                with self.assertRaisesRegex(WorkflowError, 'original-cases-required'):
                    current.qualify(tools, engine, splicer, prepared, root/'failed-output')
                self.assertFalse((root/'failed-output/PUBLISHED-FETCH-CURRENT.json').exists())
                failure = json.loads((root/'failed-output/FAILED.json').read_bytes())
                self.assertEqual((failure['status'], failure['stage']), ('failed', 'signed-execution-1'))
            self.assertEqual(result['status'], 'passed')
            self.assertIs(result['fullTicketQualification'], False)
            self.assertEqual(len(result['variants']), 2)
            self.assertEqual([row[0] for row in calls], ['build', 'execute', 'build', 'execute', 'build', 'execute'])
            self.assertTrue(all(row[1:] == (engine/'engine.wasm', splicer/'splicer')
                                for row in calls if row[0] == 'build'))
            self.assertEqual(result['compilerProducts'], compiler)
            self.assertEqual(result['nativeProducts'], native_identity)


if __name__ == '__main__':
    unittest.main()

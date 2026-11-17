"""Finite identity and workflow guards; these do not run or qualify a guest."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest
from tools.typescript_guest import borrow_current_controls as current


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True)+'\n', encoding='utf-8')


class CurrentBorrowSourceTests(unittest.TestCase):
    def test_missing_skipped_or_failed_source_controls_are_not_accepted(self):
        current.require_source_controls({'testsRun':15, 'skipped':0, 'failures':0, 'errors':0})
        for value in ({'testsRun':14, 'skipped':0, 'failures':0, 'errors':0},
                      {'testsRun':15, 'skipped':1, 'failures':0, 'errors':0},
                      {'testsRun':15, 'skipped':0, 'failures':1, 'errors':0},
                      {'testsRun':15, 'skipped':False, 'failures':0, 'errors':0}):
            with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, 'source-controls-no-skips'):
                current.require_source_controls(value)

    def origin(self):
        commit = 'a'*40
        return commit, {'GITHUB_REPOSITORY': 'KirilsTurkins/latent-service-fabric',
            'GITHUB_WORKFLOW_REF': 'KirilsTurkins/latent-service-fabric/.github/workflows/typescript-guest.yml@refs/heads/development',
            'GITHUB_WORKFLOW_SHA': commit, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': commit,
            'GITHUB_REF': 'refs/heads/development'}

    def test_only_first_development_dispatch_with_exact_source_is_accepted(self):
        commit, origin = self.origin()
        self.assertEqual(current.workflow_origin(origin, commit), origin)
        for name, value in (
            ('GITHUB_REPOSITORY', 'elsewhere'), ('GITHUB_EVENT_NAME', 'push'),
            ('GITHUB_REF', 'refs/heads/release'), ('GITHUB_SHA', 'b'*40),
            ('GITHUB_WORKFLOW_SHA', 'b'*40), ('GITHUB_RUN_ID', '0'),
            ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_WORKFLOW_REF', 'other'),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'exact-development-workflow'):
                current.workflow_origin({**origin, name: value}, commit)

    def products(self, root):
        engine, splicer = root/'engine', root/'splicer'
        engine.mkdir()
        splicer.mkdir()
        core = b'\0asm\x01\0\0\0\0'
        (engine/'engine.wasm').write_bytes(core)
        (splicer/'splicer-input.json').write_bytes(b'actual bounded splicer input')
        (engine/'source-derivation.json').write_bytes(b'actual bounded derivation')
        splicer_identity = {'inputDigest': digest((splicer/'splicer-input.json').read_bytes()), 'files': []}
        profile = current.runtime_profile.IMPORT_PROFILE
        paths = current.activation_engine.engine_input_paths(profile)
        recipe = ('tools/build_typescript_native_engine.py', 'tools/typescript_guest/native_build.py', *paths)
        compilation = {'schemaVersion': 'latent.typescript.native-engine-source-build.v1',
            'status': 'core-compiled', 'scope': 'normal-cmake-engine-compile-only',
            'qualification': 'unknown', 'apiSupport': 'not-evaluated', 'signedExecution': 'not-run',
            'recipe': {name: file_identity(ROOT/name) for name in recipe},
            'engine': file_identity(engine/'engine.wasm'), 'sourceSplicer': splicer_identity}
        write_json(engine/'engine-compilation.json', compilation)
        sdk = {name: (ROOT/name).read_bytes() for name in paths}
        envelope = {'schemaVersion': current.runtime_profile.IMPORT_ENGINE_SCHEMA,
            'profile': profile, 'coreDigest': digest(core), 'coreBytes': len(core),
            'sdkInputs': [{'path': name, 'digest': digest(raw), 'size': len(raw)}
                          for name, raw in sorted(sdk.items())],
            'runtimeWitDigest': digest((ROOT/'wit/platform/activation-runtime/package.wit').read_bytes()),
            'upstream': current.runtime_profile.SOURCE_PINS,
            'qualification': 'unknown', 'apiSupport': 'not-evaluated', 'inputTrust': 'operator-asserted',
            'compilerSplicerInputDigest': splicer_identity['inputDigest'],
            'buildReceiptDigest': digest((engine/'engine-compilation.json').read_bytes()),
            'sourceDerivationDigest': digest((engine/'source-derivation.json').read_bytes())}
        write_json(engine/'engine-input.json', envelope)
        build = {**compilation, 'status': 'passed', 'input': file_identity(engine/'engine-input.json')}
        write_json(engine/'engine-build.json', build)
        return engine, splicer, splicer_identity

    def test_original_build_receipt_engine_and_splicer_remain_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine, splicer, identity = self.products(Path(temporary))
            with patch.object(current.native_build, 'source_splicer', return_value=identity):
                result = current.source_products(engine, splicer)
                self.assertEqual(result['splicer'], identity)
                compilation = json.loads((engine/'engine-compilation.json').read_bytes())
                compilation['signedExecution'] = 'passed'
                write_json(engine/'engine-compilation.json', compilation)
                with self.assertRaisesRegex(WorkflowError, 'original-engine-splicer-and-recipe'):
                    current.source_products(engine, splicer)

    def test_splicer_mismatch_or_absent_original_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine, splicer, identity = self.products(Path(temporary))
            with patch.object(current.native_build, 'source_splicer', return_value={**identity, 'inputDigest': 'sha256:'+'f'*64}):
                with self.assertRaisesRegex(WorkflowError, 'original-engine-splicer-and-recipe'):
                    current.source_products(engine, splicer)
            (engine/'source-derivation.json').unlink()
            with self.assertRaisesRegex(WorkflowError, 'resource-identity-file'):
                current.source_products(engine, splicer)

    def test_engine_from_different_sdk_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine, splicer, identity = self.products(Path(temporary))
            envelope = json.loads((engine/'engine-input.json').read_bytes())
            envelope['sdkInputs'][0]['digest'] = 'sha256:'+'f'*64
            write_json(engine/'engine-input.json', envelope)
            with patch.object(current.native_build, 'source_splicer', return_value=identity):
                with self.assertRaisesRegex(ValueError, 'sdk-source-mismatch'):
                    current.source_products(engine, splicer)

    def test_current_job_requires_both_same_run_producers_and_separate_concurrency(self):
        workflow = yaml.load((ROOT/'.github/workflows/typescript-guest.yml').read_text(), Loader=yaml.BaseLoader)
        selected = workflow['on']['workflow_dispatch']['inputs']['qualify-current-borrow']
        self.assertEqual(selected['default'], 'false')
        job = workflow['jobs']['current-signed-borrow']
        self.assertEqual(job['needs'], ['source-splicer', 'promise-library'])
        self.assertIn("github.ref == 'refs/heads/development'", job['if'])
        self.assertIn('inputs.qualify-current-borrow', job['if'])
        self.assertIn('inputs.qualify-current-borrow', workflow['concurrency']['group'])
        downloads = [step['with']['name'] for step in job['steps']
                     if step.get('uses', '').startswith('KirilsTurkins/lsf-download-artifact@')]
        self.assertEqual(downloads, ['typescript-source-splicer-input-${{ github.sha }}',
                                     'typescript-fetch-engine-input-${{ github.sha }}'])
        self.assertTrue(all('run-id' not in step.get('with', {}) for step in job['steps']))
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        for duplicate in ('build_typescript_promise_library.py', 'build_typescript_native_engine.py',
                          'build_typescript_source_splicer.py'):
            self.assertNotIn(duplicate, commands)
        upload = next(step for step in workflow['jobs']['promise-library']['steps']
                      if step.get('with', {}).get('name') == 'typescript-fetch-engine-input-${{ github.sha }}')
        for name in current.ENGINE_FILES:
            self.assertIn('/'+name, upload['with']['path'])
        self.assertIn('!inputs.qualify-current-borrow', workflow['jobs']['fetch-component']['if'])
        self.assertIn('!inputs.qualify-current-borrow', workflow['jobs']['boundary']['if'])


if __name__ == '__main__':
    unittest.main()

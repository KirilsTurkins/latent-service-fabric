"""Bounded real-compiler handoff and honest Fetch qualification evidence."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import qualify_typescript_fetch_component as fetch
from tools.phase2_operator_process import WorkflowError
from tools.typescript_guest.project import validate


class TypeScriptFetchComponentTests(unittest.TestCase):
    def write_json(self, path, value):
        path.write_text(json.dumps(value) + '\n', encoding='utf-8')

    def test_capture_retains_normal_sdk_and_exact_async_http_world(self):
        with tempfile.TemporaryDirectory() as name:
            app = fetch.project(Path(name) / 'application')
            project, lock, _pins = validate(fetch.snapshot(app))
            self.assertEqual(project['runtimeProfile'], fetch.IMPORT_PROFILE)
            self.assertEqual(project['world'], fetch.WORLD)
            self.assertEqual(project['limits']['outboundRequests'], 1)
            self.assertEqual((app / 'src/default-client.ts').read_bytes(),
                fetch.read_file(fetch.ROOT / fetch.FIXTURE / 'default-client.ts'))
            self.assertEqual((app / 'wit/deps/http-v3/package.wit').read_bytes(),
                fetch.read_file(fetch.ROOT / 'wit/platform/http-v3/package.wit'))
            self.assertEqual(lock['template']['witDigest'], fetch.digest((app / 'wit/world.wit').read_bytes()))

    def evidence(self, root):
        engine = {'coreDigest': 'sha256:' + '1' * 64, 'coreBytes': 100}
        selected = {'profile': fetch.IMPORT_PROFILE, 'qualification': 'unknown',
            'apiSupport': 'not-evaluated', 'engineInput': engine}
        compiler = {'selectedEngine': {'digest': engine['coreDigest'], 'size': 100,
            'profile': fetch.IMPORT_PROFILE, 'qualification': 'unknown', 'apiSupport': 'not-evaluated'},
            'selectedCompilerSplicer': True, 'qualification': 'unknown'}
        bundle = {'standardFetchProfile': fetch.PROFILE,
            'selection': {'runtimeProfile': fetch.IMPORT_PROFILE, 'standardFetchProfile': fetch.PROFILE},
            'capturedInputs': [{'path': 'src/main.ts'}, {'path': 'src/default-client.ts'}],
            'standardFetchBackendDigest': 'sha256:' + '2' * 64,
            'snapshotGuardDigest': 'sha256:' + '3' * 64}
        for filename, value in (('typescript-runtime-selection.json', selected),
                ('compiler.json', compiler), ('application.mjs.inputs.json', bundle)):
            self.write_json(root / filename, value)
        (root / 'component.wasm').write_bytes(b'\0asm\x0d\0\x01\0')
        return engine, selected, compiler, bundle

    def test_compiled_evidence_never_claims_signed_provider_or_client_execution(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            engine, _selected, _compiler, _bundle = self.evidence(root)
            result = fetch.compilation_evidence(root, engine)
            self.assertEqual(result['component']['bytes'], 8)
            self.assertEqual(result['directAndTransitiveInitialization'],
                'source-selected; execution-not-observed')
            for field in ('asyncFunctionRuntimeExecution', 'signedExecution',
                    'providerExecution', 'unchangedPublishedClients'):
                self.assertEqual(result[field], 'not-run')

    def test_public_sync_or_different_engine_cannot_substitute(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            engine, selected, _compiler, _bundle = self.evidence(root)
            for field, value in (('profile', 'spidermonkey-public-sync-v1'),
                    ('engineInput', dict(engine, coreBytes=101)), ('qualification', 'passed')):
                changed = dict(selected, **{field: value})
                self.write_json(root / 'typescript-runtime-selection.json', changed)
                with self.subTest(field=field), self.assertRaisesRegex(WorkflowError, 'selected-engine-mismatch'):
                    fetch.compilation_evidence(root, engine)

    def test_real_source_splicer_selection_and_exact_core_identity_are_required(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            engine, _selected, compiler, _bundle = self.evidence(root)
            for changed in (dict(compiler, selectedCompilerSplicer=False),
                    dict(compiler, selectedEngine=dict(compiler['selectedEngine'], size=99))):
                self.write_json(root / 'compiler.json', changed)
                with self.assertRaisesRegex(WorkflowError, 'real-import-compiler-required'):
                    fetch.compilation_evidence(root, engine)

    def test_missing_automatic_backend_transitive_source_or_bootstrap_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            engine, _selected, _compiler, bundle = self.evidence(root)
            for field, value, error in (
                ('standardFetchProfile', None, 'automatic-backend-required'),
                ('capturedInputs', [{'path': 'src/main.ts'}], 'transitive-source-required'),
                ('snapshotGuardDigest', 'sha256:' + 'x' * 64, 'bootstrap-identities-required')):
                changed = deepcopy(bundle)
                changed[field] = value
                self.write_json(root / 'application.mjs.inputs.json', changed)
                with self.subTest(field=field), self.assertRaisesRegex(WorkflowError, error):
                    fetch.compilation_evidence(root, engine)

    def test_core_wasm_cannot_be_reported_as_a_component(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            engine, _selected, _compiler, _bundle = self.evidence(root)
            (root / 'component.wasm').write_bytes(b'\0asm\x01\0\0\0')
            with self.assertRaisesRegex(WorkflowError, 'real-component-required'):
                fetch.compilation_evidence(root, engine)

    def test_actual_fixture_uses_globals_before_module_initialization_and_parses_typed_response(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'The pinned Node host is required for this source control')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            script = r"""
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
const [fixture, temporary, backend] = process.argv.slice(2);
const {installFetch} = await import(pathToFileURL(backend));
let contacts = 0, reads = 0, drops = 0;
const owner = () => ({[Symbol.dispose]() {drops++;}});
installFetch({
  async open(request) {
    contacts++;
    assert.equal(request.url, 'https://fixture.invalid/conformance/json');
    assert.deepEqual(request.headers, [{name: 'x-client', value: 'ordinary-global'}]);
    return owner();
  },
  async finish() {return {status: 200, headers: [], body: owner()};},
  async read() {return reads++ === 0 ? owner() : undefined;},
  async chunkBytes() {return new TextEncoder().encode('{"message":"fixture"}');},
}, () => false);
for (const name of ['default-client', 'main']) {
  const source = stripTypeScriptTypes(await readFile(fixture + '/' + name + '.ts', 'utf8'));
  await writeFile(temporary + '/' + name + '.mjs', source.replace("'./default-client.js'", "'./default-client.mjs'"));
}
const {api} = await import(pathToFileURL(temporary + '/main.mjs'));
assert.equal(contacts, 0);
assert.equal(await api.run('https://fixture.invalid/conformance/json'), '200:fixture');
assert.equal(contacts, 1);
assert.equal(drops, 2); // materialized chunk and body; finish consumed upload.
"""
            entry = root / 'control.mjs'
            entry.write_text(script, encoding='utf-8')
            completed = subprocess.run([node, str(entry), str(fetch.ROOT / fetch.FIXTURE),
                str(root), str(fetch.ROOT / 'tools/typescript_guest/fetch.mjs')],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()

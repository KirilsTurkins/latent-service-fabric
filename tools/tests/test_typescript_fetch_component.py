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


class TypeScriptFetchManifestTests(unittest.TestCase):
    def large_compiler_manifest(self):
        # The exact first hosted run's source-splicer compiler inventory had
        # 4,431 {path,digest,size} rows and 347,044,903 content bytes. Model that
        # real shape without copying its 918,721-byte public receipt into Git.
        rows = [{'path': 'node_modules/@bytecodealliance/jco/typescript-component-compiler/'
            + str(index) + '/generated-file.js', 'digest': 'sha256:' + 'a' * 64,
            'size': 100} for index in range(4431)]
        return {'files': rows, 'bytes': sum(row['size'] for row in rows)}

    def test_large_compiler_manifest_binds_every_row_with_equal_pre_post_summaries(self):
        value = self.large_compiler_manifest()
        original = deepcopy(value)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertGreater(len(json.dumps(value, separators=(',', ':')).encode()), 262144)
            with self.assertRaisesRegex(WorkflowError, 'fixture-size'):
                fetch.write_json(root / 'full.json', value)
            self.assertFalse((root / 'full.json').exists())
            before = fetch.compiler_manifest_summary(value)
            after = fetch.compiler_manifest_summary(deepcopy(value))
            self.assertEqual(before, after)
            self.assertEqual(before['fileCount'], 4431)
            self.assertEqual(before['contentBytes'], value['bytes'])
            self.assertEqual(value, original)
            fetch.write_json(root / 'before.json', before)
            fetch.write_json(root / 'after.json', after)
            self.assertEqual((root / 'before.json').read_bytes(), (root / 'after.json').read_bytes())
            self.assertLess((root / 'before.json').stat().st_size, 512)
            for field, replacement in (('path', 'changed.js'), ('digest', 'sha256:' + 'b' * 64), ('size', 101)):
                changed = deepcopy(value)
                changed['files'][-1][field] = replacement
                self.assertNotEqual(fetch.compiler_manifest_summary(changed)['manifestDigest'], before['manifestDigest'])

    def test_large_containment_manifest_is_fully_bound_under_original_writer_limit(self):
        value = {'distributions': {'typescript-compiler': self.large_compiler_manifest()['files']},
            'network': 'denied', 'ambientHome': 'absent', 'credentials': 'not-inherited'}
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with self.assertRaisesRegex(WorkflowError, 'fixture-size'):
                fetch.write_json(root / 'full.json', value)
            summary = fetch.manifest_summary(value)
            fetch.write_json(root / 'summary.json', summary)
            self.assertLess((root / 'summary.json').stat().st_size, 512)
            self.assertEqual(summary, fetch.manifest_summary(deepcopy(value)))
            changed = deepcopy(value)
            changed['network'] = 'allowed'
            self.assertNotEqual(summary['manifestDigest'], fetch.manifest_summary(changed)['manifestDigest'])
            changed = deepcopy(value)
            changed['distributions']['typescript-compiler'][-1]['digest'] = 'sha256:' + 'c' * 64
            self.assertNotEqual(summary['manifestDigest'], fetch.manifest_summary(changed)['manifestDigest'])

if __name__ == '__main__':
    unittest.main()

"""Pinned contract and actual JS adapter controls; no component qualification."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.typescript_guest import entropy_profile as profile

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptEntropy(unittest.TestCase):
    def graph(self):
        standard = json.loads((ROOT / 'tools/tests/fixtures/typescript_entropy_random.json').read_bytes())['graph']
        graph = deepcopy(standard)
        graph['packages'].append({'name': 'examples:entropy@1.0.0', 'interfaces': {}, 'worlds': {'service': 0}})
        graph['worlds'] = [{'name': 'service', 'package': 2,
            'imports': {'interface-0': {'interface': {'id': 0}}}, 'exports': {}}]
        return graph, standard

    def javascript(self, code):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for actual adapter controls')
        prefix = "import assert from 'node:assert/strict';\nimport {installMathRandom} from " + json.dumps(
            (ROOT / 'tools/typescript_guest/entropy.mjs').as_uri()) + ';\n'
        result = subprocess.run([node, '--input-type=module', '-e', prefix + code],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_generated_random_contract_selects_only_its_declared_profile(self):
        graph, standard = self.graph()
        base = {'runtimeProfile': 'spidermonkey-public-sync-v1', 'standardFetchProfile': 'preserved',
                'standardConsoleProfile': 'preserved'}
        self.assertTrue(profile.selected([profile.INTERFACE]))
        selected = profile.configuration(base, graph, 'examples:entropy/service@1.0.0', standard)
        self.assertEqual(selected, {**base, 'standardEntropyProfile': profile.PROFILE})
        self.assertEqual(base['standardFetchProfile'], 'preserved')
        graph['worlds'][0]['imports'] = {}
        self.assertEqual(profile.configuration(base, graph, 'examples:entropy/service@1.0.0', None),
                         {**base, 'standardEntropyProfile': profile.CLOSED})
        with self.assertRaisesRegex(ValueError, 'unselected-contract'):
            profile.configuration(base, graph, 'examples:entropy/service@1.0.0', standard)

    def test_wrong_width_error_order_async_kind_and_version_refuse_exact_contract(self):
        graph, standard = self.graph()
        for mutate in (lambda g: g['types'][3]['kind']['result'].update(ok='u32'),
                       lambda g: g['types'][0]['kind']['variant']['cases'].reverse(),
                       lambda g: g['interfaces'][0]['functions']['u64-value'].update(kind='async-freestanding'),
                       lambda g: g['packages'][0].update(name='latent:random@0.2.0')):
            changed = deepcopy(graph); mutate(changed)
            with self.assertRaisesRegex(ValueError, 'standard-entropy-'):
                profile.configuration({}, changed, 'examples:entropy/service@1.0.0', standard)
        with self.assertRaisesRegex(ValueError, 'exact-random-interface'):
            profile.configuration({}, graph, 'examples:entropy/service@1.0.0', None)

    def test_capture_metadata_cannot_inject_or_override_the_backend(self):
        graph, standard = self.graph()
        for field in ('standardEntropyProfile', 'standardEntropyBackendDigest'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'cannot-override'):
                profile.configuration({field: 'caller-owned'}, graph, 'examples:entropy/service@1.0.0', standard)

    def test_high_53_bits_are_exact_and_every_call_draws_without_a_seed_or_cache(self):
        self.javascript(r"""
const target={}, draws=[0n, 0xffffffffffffffffn, 1n << 63n, 2047n, 2048n];let calls=0;
installMathRandom({u64Value(){return draws[calls++];}},()=>false,target);
assert.equal(target.random.name,'random');assert.equal(target.random.length,0);
assert.deepEqual([target.random(),target.random(),target.random(),target.random(),target.random()],
                 [0,1-2**-53,0.5,0,2**-53]);
assert.equal(calls,5);
const descriptor=Object.getOwnPropertyDescriptor(target,'random');
assert.equal(descriptor.enumerable,false);assert.equal(descriptor.configurable,true);assert.equal(descriptor.writable,true);
""")

    def test_snapshot_and_undeclared_calls_refuse_without_using_original_or_host_source(self):
        self.javascript(r"""
let calls=0,snapshot=true;const target={random(){throw new Error('original-must-not-run');}};
installMathRandom({u64Value(){calls++;return 42n;}},()=>snapshot,target);
const captured=target.random;assert.throws(captured,/snapshot-time-entropy-observation-unsupported/);
assert.equal(calls,0);snapshot=false;assert.equal(captured(),0);assert.equal(calls,1);
const closed={random(){throw new Error('original-must-not-run');}};
installMathRandom(null,()=>false,closed);assert.throws(closed.random,/unsupported:Math.random/);
assert.equal(calls,1);
""")

    def test_host_error_identity_is_preserved_and_no_retry_or_plausible_result_is_returned(self):
        self.javascript(r"""
for(const error of [{payload:{tag:'budget-exhausted'}},{payload:{tag:'unavailable'}},new Error('fixed-technical')]) {
 let calls=0;const target={};installMathRandom({u64Value(){calls++;throw error;}},()=>false,target);
 assert.throws(target.random,value=>value===error);assert.equal(calls,1);
}
for(const value of [-1n,1n<<64n,1,0,'42',null,undefined]) {
 const target={};installMathRandom({u64Value(){return value;}},()=>false,target);
 assert.throws(target.random,/standard-entropy-u64-result/);
}
""")

    def test_installation_is_lazy_and_leaves_compiler_math_and_other_intrinsics_unchanged(self):
        self.javascript(r"""
const original=Math.random, target=Object.create(Math);let calls=0;
installMathRandom({u64Value(){calls++;return 0n;}},()=>false,target);
assert.equal(calls,0);assert.equal(Math.random,original);assert.equal(target.sqrt(4),2);
assert.equal(target.PI,Math.PI);
const originalNumber=globalThis.Number;
try { globalThis.Number=()=>{throw new Error('caller-global-must-not-run');};assert.equal(target.random(),0); }
finally {globalThis.Number=originalNumber;}
assert.equal(calls,1);
for(const source of [{}, {u64Value:1}, undefined]) assert.throws(()=>installMathRandom(source,()=>false,{}),TypeError);
assert.throws(()=>installMathRandom(null,null,{}),TypeError);
""")

    def test_real_bundle_banner_is_application_scoped_and_rejects_snapshot_random(self):
        # This exercises the maintained banner builder and emitted module in
        # Node. A tiny esbuild stand-in transports those bytes unchanged; it is
        # neither an esbuild/Wizer reference nor component qualification.
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for emitted-header controls')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stub = root / 'esbuild.mjs'
            stub.write_bytes(b"import {readFile} from 'node:fs/promises';\n"
                b"const originalRandom=Math.random;\n"
                b"export async function build(options) {\n"
                b" if(Math.random!==originalRandom) throw Error('compiler-host-random-mutated');\n"
                b" const input=await readFile(options.entryPoints[0],'utf8');\n"
                b" const text=options.banner.js+'\\n'+input+'\\n'+options.footer.js;\n"
                b" return {metafile:{inputs:{}},outputFiles:[{path:options.outfile,text,contents:Buffer.from(text)}]};\n"
                b"}\n")
            imports, configuration = root / 'imports.json', root / 'configuration.json'
            imports.write_bytes(b'[]')
            configuration.write_bytes(json.dumps({'standardEntropyProfile': profile.CLOSED}).encode())
            for early in (False, True):
                with self.subTest(snapshot_initializer=early):
                    source = root / ('early.mjs' if early else 'ordinary.mjs')
                    source.write_bytes(b'export const value=Math.random();\n' if early else
                        b'export const answer=40+Math.sqrt(4);\nexport function draw(){return Math.random();}\n')
                    output = root / ('early-output.mjs' if early else 'ordinary-output.mjs')
                    built = subprocess.run([node, str(ROOT / 'tools/typescript_guest/bundle.mjs'),
                        str(stub), str(root), str(source), str(output), str(imports), str(configuration)],
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    metadata = json.loads(Path(str(output) + '.inputs.json').read_bytes())
                    self.assertEqual(metadata['standardEntropyProfile'], profile.CLOSED)
                    self.assertRegex(metadata['standardEntropyBackendDigest'], r'^sha256:[0-9a-f]{64}$')
                    if early:
                        check = "await assert.rejects(import(moduleURL),/snapshot-time-entropy-observation-unsupported/);"
                    else:
                        check = "const m=await import(moduleURL);assert.equal(m.answer,42);assert.throws(m.draw,/unsupported:Math.random/);"
                    result = subprocess.run([node, '--input-type=module', '-e',
                        "import assert from 'node:assert/strict';const moduleURL=" + json.dumps(output.as_uri()) + ';' + check],
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_compiler_banner_does_not_retain_the_deterministic_original_fallback(self):
        source = (ROOT / 'tools/typescript_guest/bundle.mjs').read_text(encoding='utf-8')
        self.assertNotIn('__lsfOriginalRandom', source)
        self.assertIn('standardEntropyBackendDigest', source)
        self.assertIn('installMathRandom', (ROOT / 'tools/typescript_guest/entropy.mjs').read_text())
        self.assertIn("disableFeatures: ['stdio', 'random', 'clocks', 'http', 'fetch-event']",
                      (ROOT / 'tools/typescript_guest/componentize.mjs').read_text())


if __name__ == '__main__': unittest.main()

"""Application clock guards; actual signed engine qualification is separate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ApplicationClockTests(unittest.TestCase):
    def test_isolated_compiler_stages_exact_clock_source_and_real_bundle_can_read_it(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from tools.typescript_guest.compiler import Compiler
        old = os.environ.get('LSF_CLOCK_TEST_COMPILER')
        if old:
            import importlib.util
            spec = importlib.util.spec_from_file_location('clock_compiler_preimage_control', old)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            Compiler = module.Compiler
        def command(stage, *_arguments):
            if stage == 'node-version': return b'v24.19.0'
            if stage == 'wasm-tools-version': return b'wasm-tools 1.254.0'
            self.assertEqual(stage, 'prepare-compiler-adapter')
            return b''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tools = root/'tools'; tools.mkdir()
            package = b'{"dependencies":{}}'; (tools/'package.json').write_bytes(package)
            isolated = root/'isolated'; isolated.mkdir()
            commands = SimpleNamespace(environment={'PATH': os.environ['PATH']}, run=command)
            # Only external adapter preparation and namespace installation are
            # mocked. The constructor must copy its actual recipe and Node reads it.
            with patch('tools.captured_compiler_isolation.Isolation'):
                compiler = Compiler(tools, commands, {'package.json': package}, isolated_workspace=isolated)
            self.assertEqual((compiler.recipe/'clock_app.mjs').read_bytes(),
                             (ROOT/'tools/typescript_guest/clock_app.mjs').read_bytes())
            stub = root/'esbuild.mjs'
            stub.write_bytes(b"export async function build(o){const text=o.banner.js+o.footer.js;return {metafile:{inputs:{},outputs:{[o.outfile]:{bytes:text.length}}},outputFiles:[{path:o.outfile,text,contents:new TextEncoder().encode(text)}]};}")
            imports = root/'imports.json'; imports.write_bytes(b'[]')
            configuration = root/'configuration.json'; configuration.write_bytes(b'{}')
            source = root/'main.js'; source.write_bytes(b'export const answer=42;\n')
            result = subprocess.run([shutil.which('node'), str(compiler.recipe/'bundle.mjs'), str(stub),
                str(root), str(source), str(root/'application.mjs'), str(imports), str(configuration)],
                capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))

    def test_selected_bundle_uses_verified_native_clocks_without_application_JS_imports(self):
        from tools.typescript_guest.compiler import native_clock_configuration
        from tools.typescript_guest.runtime_profile import CLOCK_PROFILES, SELECTED_WORLD
        fixture = ROOT/'tools/tests/fixtures/typescript_clock_profile/selected-graph.json'
        graph = json.loads(fixture.read_bytes())['graph']
        node = shutil.which('node'); self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stub = root/'esbuild.mjs'
            stub.write_bytes(b"export async function build(o){const text=o.banner.js+o.footer.js;return {metafile:{inputs:{},outputs:{[o.outfile]:{bytes:text.length}}},outputFiles:[{path:o.outfile,text,contents:new TextEncoder().encode(text)}]};}")
            imports = root/'imports.json'; imports.write_bytes(b'[]')
            source = root/'main.js'; source.write_bytes(b'export const answer=42;\n')
            for profile in CLOCK_PROFILES:
                configuration = native_clock_configuration({'runtimeProfile': profile}, profile, graph, SELECTED_WORLD)
                self.assertEqual(configuration['nativeClockInterfaces'],
                    ['latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'])
                for index, changed in enumerate((None, [], configuration['nativeClockInterfaces'][:1],
                                                 configuration['nativeClockInterfaces']*2)):
                    with self.subTest(profile=profile, interfaces=changed):
                        value = configuration if changed is None else {**configuration, 'nativeClockInterfaces': changed}
                        path = root/'configuration.json'; path.write_bytes(json.dumps(value).encode())
                        output = root/f'application-{profile}-{index}.mjs'
                        script = os.environ.get('LSF_CLOCK_TEST_BUNDLE', str(ROOT/'tools/typescript_guest/bundle.mjs'))
                        built = subprocess.run([node, script, str(stub), str(root), str(source), str(output),
                            str(imports), str(path)], capture_output=True, text=True, timeout=10)
                        self.assertEqual(built.returncode == 0, changed is None, built.stderr)
                        if changed is None:
                            metadata = json.loads(output.with_suffix('.mjs.inputs.json').read_bytes())
                            self.assertEqual(metadata['standardClockProfile'], 'lsf-standard-clock-native-v1')

    def test_native_clock_selection_cannot_be_supplied_by_capture_or_omit_a_verified_interface(self):
        from tools.typescript_guest.compiler import native_clock_configuration
        from tools.typescript_guest.runtime_profile import CLOCK_PROFILE, SELECTED_WORLD, SYNC_PROFILE
        fixture = ROOT/'tools/tests/fixtures/typescript_clock_profile'
        selected = json.loads((fixture/'selected-graph.json').read_bytes())['graph']
        original = json.loads((fixture/'original-graph.json').read_bytes())['graph']
        for field in ('standardClockProfile', 'standardClockBackendDigest', 'nativeClockInterfaces'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'cannot-override'):
                native_clock_configuration({field: []}, CLOCK_PROFILE, selected, SELECTED_WORLD)
        with self.assertRaisesRegex(ValueError, 'requires-verified-native'):
            native_clock_configuration({}, CLOCK_PROFILE, original, 'tests:typescript-async/capsule@1.0.0')
        self.assertEqual(native_clock_configuration({}, SYNC_PROFILE, original,
            'tests:typescript-async/capsule@1.0.0'), {'nativeClockInterfaces': []})

    def javascript(self, body):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for actual clock guard controls')
        prefix = "import assert from 'node:assert/strict';import vm from 'node:vm';\n"
        prefix += 'import {installApplicationClocks} from '+json.dumps(
            (ROOT/'tools/typescript_guest/clock_app.mjs').as_uri())+';\n'
        prefix += "const context=vm.createContext({performance:{}});const target=vm.runInContext('globalThis',context);\n"
        result = subprocess.run([node, '--input-type=module', '-e', prefix+body],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_reads_refuse_but_explicit_date_arguments_and_statics_remain_deterministic(self):
        self.javascript(r"""
const compilerDate=Date;installApplicationClocks(false,()=>false,target);
for(const call of [()=>target.Date.now(),()=>target.Date(),()=>target.Date('literal'),
 ()=>new target.Date(),()=>target.performance.now(),()=>target.performance.timeOrigin])
 assert.throws(call,/unsupported:standard-clock-without-approved-profile/);
assert.equal(new target.Date(0).toISOString(),'1970-01-01T00:00:00.000Z');
assert.equal(new target.Date(null).valueOf(),0);
assert.ok(Number.isNaN(new target.Date(undefined).valueOf()));
assert.equal(target.Date.parse('1970-01-01T00:00:00.000Z'),0);
assert.equal(target.Date.UTC(1970,0,1),0);
class Derived extends target.Date{};const derived=new Derived(0);
assert.ok(derived instanceof Derived);assert.ok(derived instanceof target.Date);
assert.equal(new target.Date(0).constructor,target.Date);assert.equal(Date,compilerDate);
assert.equal(target.Date.now,target.Date.now);
""")

    def test_selected_backend_is_lazy_and_snapshot_reads_never_reach_it(self):
        self.javascript(r"""
let wallCalls=0,monoCalls=0,originCalls=0,snapshot=true;
target.__lsfSelectedClockBridge={wall(){wallCalls++;return 1234567890123;},
 now(){monoCalls++;return 1.25;},origin(){originCalls++;return 1234567890123;}};
vm.runInContext(SOURCE,context);installApplicationClocks(true,()=>snapshot,target);
assert.deepEqual([wallCalls,monoCalls,originCalls],[0,0,0]);
for(const call of [()=>target.Date.now(),()=>target.Date(),()=>target.Date('literal'),
 ()=>new target.Date(),()=>target.performance.now(),()=>target.performance.timeOrigin])
 assert.throws(call,/snapshot-time-clock-observation-unsupported/);
assert.equal(new target.Date(0).valueOf(),0);assert.deepEqual([wallCalls,monoCalls,originCalls],[0,0,0]);
snapshot=false;assert.equal(target.Date.now(),1234567890123);
assert.equal(new target.Date().valueOf(),1234567890123);assert.equal(typeof target.Date('ignored'),'string');
assert.equal(target.performance.now(),1.25);assert.equal(target.performance.timeOrigin,1234567890123);
assert.deepEqual([wallCalls,monoCalls,originCalls],[3,1,1]);
""".replace('SOURCE', json.dumps((ROOT/'sdk/typescript-guest/activation/clock_globals.js').read_bytes().decode())))

    def test_backend_error_identity_and_full_millisecond_value_are_preserved_without_retry(self):
        self.javascript(r"""
let calls=0,fail=false;const failure={kind:'closed-known-provider-failure'};
target.__lsfSelectedClockBridge={wall(){calls++;if(fail)throw failure;return 8640000000000000;},
 now(){if(fail)throw failure;return 0;},origin(){if(fail)throw failure;return 8640000000000000;}};
vm.runInContext(SOURCE,context);installApplicationClocks(true,()=>false,target);
assert.equal(target.Date.now(),8640000000000000);assert.equal(calls,1);fail=true;
assert.throws(target.Date.now,error=>error===failure);assert.equal(calls,2);
assert.throws(()=>target.performance.now(),error=>error===failure);
assert.throws(()=>target.performance.timeOrigin,error=>error===failure);
""".replace('SOURCE', json.dumps((ROOT/'sdk/typescript-guest/activation/clock_globals.js').read_bytes().decode())))

    def test_unknown_installation_or_backend_shape_fails_before_a_clock_read(self):
        self.javascript(r"""
for(const selected of [null,undefined,'yes',1,{}])
 assert.throws(()=>installApplicationClocks(selected,()=>false,target),TypeError);
assert.throws(()=>installApplicationClocks(false,null,target),TypeError);
assert.throws(()=>installApplicationClocks(true,()=>false,target),/backend-shape/);
""")

    def test_actual_bundle_replaces_frozen_default_clock_success_and_blocks_snapshot_reads(self):
        # A tiny transport stand-in emits the actual maintained banner/footer.
        # This exercises production source generation, not an esbuild/engine claim.
        node = shutil.which('node'); self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            stub=root/'esbuild.mjs'
            stub.write_bytes(b"import {readFile} from 'node:fs/promises';export async function build(o){const source=await readFile(o.entryPoints[0],'utf8');const text=o.banner.js+source+o.footer.js+'\\n';return {metafile:{inputs:{'main.js':{}},outputs:{[o.outfile]:{bytes:text.length}}},outputFiles:[{path:o.outfile,text,contents:new TextEncoder().encode(text)}]};}")
            imports=root/'imports.json';imports.write_bytes(b'[]')
            configuration=root/'configuration.json';configuration.write_bytes(b'{}')
            for early in (False,True):
                with self.subTest(snapshot=early):
                    source=root/'main.js'
                    source.write_bytes(b'export const value=Date.now();\n' if early else
                        b'export function value(){return Date.now();}\nexport const literal=new Date(0).valueOf();\n')
                    output=root/('early.mjs' if early else 'ordinary.mjs')
                    script=os.environ.get('LSF_CLOCK_TEST_BUNDLE',str(ROOT/'tools/typescript_guest/bundle.mjs'))
                    built=subprocess.run([node,script,str(stub),str(root),str(source),str(output),
                        str(imports),str(configuration)],capture_output=True,text=True,timeout=10)
                    self.assertEqual(built.returncode,0,built.stderr)
                    check=("await assert.rejects(import(url),/snapshot-time-clock-observation-unsupported/);" if early else
                        "const m=await import(url);assert.equal(m.literal,0);assert.throws(m.value,/unsupported:standard-clock-without-approved-profile/);")
                    evaluated=subprocess.run([node,'--input-type=module','-e',
                        "import assert from 'node:assert/strict';Date.now=()=>0;const url="+json.dumps(output.as_uri())+';'+check],
                        capture_output=True,text=True,timeout=10)
                    self.assertEqual(evaluated.returncode,0,evaluated.stderr)


if __name__ == '__main__': unittest.main()

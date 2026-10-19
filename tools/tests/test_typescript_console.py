"""Bounded console and activation-module controls; signed execution is separate."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.typescript_guest import console_profile as profile
from tools import typescript_console_probe as signed

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptConsole(unittest.TestCase):
    def javascript(self, source, *, parser=False):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is required for actual adapter semantics')
        imports = "import assert from 'node:assert/strict';\n" + (
            f"import {{installConsole}} from {json.dumps((ROOT/'tools/typescript_guest/console.mjs').as_uri())};\n")
        if parser:
            selected = os.environ.get('LSF_TYPESCRIPT_ACORN')
            if selected is None and os.environ.get('LSF_TYPESCRIPT_FRONTEND'):
                selected = str(Path(os.environ['LSF_TYPESCRIPT_FRONTEND'])/'node_modules/acorn/dist/acorn.mjs')
            if selected is None:
                self.skipTest('Pinned compiler Acorn input is required for activation-module parser controls')
            self.assertTrue(Path(selected).is_file())
            imports += f"import {{parse}} from {json.dumps(Path(selected).as_uri())};\n"
            imports += f"import {{activationModule}} from {json.dumps((ROOT/'tools/typescript_guest/activation_module.mjs').as_uri())};\n"
        result = subprocess.run([node, '--input-type=module', '-e', imports + source],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def graph(self):
        standard = json.loads((ROOT/'tools/tests/fixtures/typescript_console_log.json').read_bytes())
        graph = deepcopy(standard)
        graph['packages'].append({'name': 'examples:console@1.0.0', 'interfaces': {}, 'worlds': {'service': 0}})
        function = {'name': 'run', 'kind': 'freestanding', 'params': [{'name': 'mode', 'type': 'u32'}], 'result': 'string'}
        graph['worlds'] = [{'name': 'service', 'package': 1, 'imports': {'interface-0': {'interface': {'id': 0}}},
                            'exports': {'run': {'function': function}}}]
        return graph, standard

    def test_only_declared_exact_log_interface_selects_the_strict_profile_without_grant(self):
        self.assertFalse(profile.selected([]))
        self.assertFalse(profile.selected(['latent:log/log@0.2.0']))
        self.assertTrue(profile.selected([profile.INTERFACE]))
        graph, standard = self.graph()
        result = profile.configuration({'runtimeProfile': 'spidermonkey-public-sync-v1'}, graph,
                                       'examples:console/service@1.0.0', standard)
        self.assertEqual(result, {'runtimeProfile': 'spidermonkey-public-sync-v1',
            'standardConsoleProfile': profile.PROFILE,
            'activationExports': [{'name': 'run', 'parameters': 1, 'functions': None}]})
        for changed in (dict(result, standardConsoleProfile='forged'), {'activationExports': []}):
            with self.assertRaisesRegex(ValueError, 'cannot-override'):
                profile.configuration(changed, graph, 'examples:console/service@1.0.0', standard)

    def test_malformed_log_signature_and_resource_export_fail_closed(self):
        graph, standard = self.graph()
        for mutate in (lambda g: g['interfaces'][0]['functions']['write'].update(result='bool'),
                       lambda g: g['types'][0]['kind']['enum']['cases'].reverse(),
                       lambda g: g['interfaces'][0]['functions']['write'].update(kind='async-freestanding')):
            changed = deepcopy(graph)
            mutate(changed)
            with self.assertRaisesRegex(ValueError, 'exact-log-interface'):
                profile.configuration({}, changed, 'examples:console/service@1.0.0', standard)
        graph['worlds'][0]['exports']['run']['function']['kind'] = {'constructor': 0}
        with self.assertRaisesRegex(ValueError, 'resource-export-unsupported'):
            profile.configuration({}, graph, 'examples:console/service@1.0.0', standard)

    def test_standard_primitive_formatting_levels_and_undefined_return_are_synchronous(self):
        self.javascript(r"""
const target={}, calls=[];
installConsole({write(...args){calls.push(args);return true;}},()=>false,target);
assert.equal(target.console.log('hello %s %i %f', 'world', '12.8', '4.5'),undefined);
target.console.info('plain',true,null,undefined);
target.console.debug('%% %s','value');target.console.warn('warning');target.console.error('error');
assert.deepEqual(calls,[['info','hello world 12 4.5',[]],['info','plain true null undefined',[]],
  ['debug','% value',[]],['warn','warning',[]],['error','error',[]]]);
target.console.log();assert.equal(calls.length,5);
const original=target.console.log;target.console.log=(...args)=>original('wrapped',...args);
target.console.log('still standard');assert.equal(calls.at(-1)[1],'wrapped still standard');
""")

    def test_integer_formatter_uses_console_standard_parseint_instead_of_node_percent_d_extension(self):
        self.javascript(r"""
const target={},calls=[];installConsole({write(level,message){calls.push(message);return true;}},()=>false,target);
for(const value of ['12.8',true,null,undefined,-0]) target.console.log('%d',value);
assert.deepEqual(calls,['12','NaN','NaN','NaN','0']);
""")

    def test_utf8_boundary_replacement_and_oversize_refuse_before_host_write(self):
        self.javascript(r"""
const target={},calls=[];installConsole({write(level,message){calls.push(message);return true;}},()=>false,target);
target.console.log('x'.repeat(256));target.console.log('λ'.repeat(128));target.console.log('😀'.repeat(64));
target.console.log('\ud800');assert.equal(calls.at(-1),'\ufffd');
for(const text of ['x'.repeat(257),'λ'.repeat(129),'😀'.repeat(65)]) assert.throws(()=>target.console.log(text),RangeError);
assert.throws(()=>target.console.log(...Array(17).fill('')),RangeError);assert.equal(calls.length,4);
""")

    def test_strict_host_rejections_and_false_never_acknowledge_or_retry(self):
        self.javascript(r"""
for(const outcome of [false,{payload:{tag:'budget-exhausted'}},{payload:{tag:'unavailable'}},{payload:{tag:'invalid-field',val:'host-private'}}]) {
 const target={};let calls=0;installConsole({write(){calls++;if(outcome===false)return false;throw outcome;}},()=>false,target);
 assert.throws(()=>target.console.error('fixed'),error=>outcome===false ? error.message==='console-log-not-accepted' : error===outcome);
 assert.equal(calls,1);
}
""")

    def test_snapshot_denial_unsupported_values_and_methods_do_not_inspect_objects_or_flush(self):
        self.javascript(r"""
const target={};let calls=0, inspected=0,snapshot=true;
installConsole({write(){calls++;return true;}},()=>snapshot,target);
assert.throws(()=>target.console.log('build'),/snapshot-denied/);snapshot=false;
const privateValue={toString(){inspected++;return 'credential';},get secret(){inspected++;return 'private';}};
for(const value of [privateValue,[],()=>{},Symbol('private'),1n]) assert.throws(()=>target.console.log(value),/unsupported-value/);
for(const format of ['%o','%O','%c']) assert.throws(()=>target.console.log(format,'text'),/unsupported-format/);
for(const method of ['table','trace','time','clear','group','assert']) assert.throws(()=>target.console[method]('fixed'),/unsupported:/);
assert.equal(target.console.flush,undefined);assert.equal(inspected,0);assert.equal(calls,0);
""")

    def test_actual_parser_defers_transitive_and_direct_initializers_preserving_live_exports(self):
        self.javascript(r"""
const exports=[{name:'api',functions:[{name:'run',parameters:1},{name:'read',parameters:0}]}];
const source=`let state=0;
globalThis.events.push('transitive-init');
state+=2;
globalThis.events.push('direct-init');
const api={run(value){this.saved=value;return ++state;},read(){return [state,this.saved];}};
export {api};`;
const derived=activationModule(source,exports,parse);
globalThis.events=[];
const load=async suffix=>await import('data:text/javascript,'+encodeURIComponent(derived.source)+'#'+suffix);
const first=await load('first');assert.deepEqual(globalThis.events,[]);
assert.equal(first.api.run.length,1);assert.equal(first.api.run('one'),3);
assert.deepEqual(first.api.read(),[3,'one']);assert.equal(first.api.run('two'),4);
assert.deepEqual(globalThis.events,['transitive-init','direct-init']);
const second=await load('fresh-store');assert.equal(second.api.run('fresh'),3);
assert.deepEqual(second.api.read(),[3,'fresh']);assert.equal(globalThis.events.length,4);
assert.equal(derived.source.split('\n').indexOf('let state=0;'),derived.lineShift);
""", parser=True)

    def test_initializer_log_failure_is_sticky_with_no_retry_or_build_time_log(self):
        self.javascript(r"""
const calls=[];let allowed=false;
const target={};installConsole({write(level,message){calls.push(message);if(!allowed)throw new Error('denied');return true;}},()=>false,target);
const source=`globalThis.ownedConsole.info('transitive');globalThis.ownedConsole.info('direct');let state=0;
function run(){return ++state;}export {run};`;
globalThis.ownedConsole=target.console;
const derived=activationModule(source,[{name:'run',parameters:0,functions:null}],parse);
const first=await import('data:text/javascript,'+encodeURIComponent(derived.source)+'#denied');
assert.deepEqual(calls,[]);assert.throws(()=>first.run(),/denied/);allowed=true;
assert.throws(()=>first.run(),/denied/);assert.deepEqual(calls,['transitive']);
const fresh=await import('data:text/javascript,'+encodeURIComponent(derived.source)+'#fresh');
assert.equal(fresh.run(),1);assert.equal(fresh.run(),2);assert.deepEqual(calls,['transitive','transitive','direct']);
""", parser=True)

    def test_mutable_export_bindings_and_getter_receiver_remain_live_after_initialization(self):
        self.javascript(r"""
const source=`let run=()=>{run=()=>42;return 1;};
let api={name:'original',get call(){api={name:'replacement',call(){return this.name;}};return function(){return this.name;};}};
export {run,api};`;
const expected=[{name:'run',parameters:0,functions:null},{name:'api',functions:[{name:'call',parameters:0}]}];
const derived=activationModule(source,expected,parse);
const module=await import('data:text/javascript,'+encodeURIComponent(derived.source));
assert.equal(module.run(),1);assert.equal(module.run(),42);
assert.equal(module.api.call(),'original');assert.equal(module.api.call(),'replacement');
""", parser=True)

    def test_parser_rejects_tla_reexports_missing_and_extra_exports_and_resource_shapes(self):
        self.javascript(r"""
const expected=[{name:'run',parameters:0,functions:null}];
for(const source of ['await Promise.resolve();function run(){}export {run};',
 'export {run} from "outside";', 'export default function run(){}',
 'function run(){}function extra(){}export {run,extra};','function other(){}export {other};']) {
 assert.throws(()=>activationModule(source,expected,parse),/console-activation-/);
}
assert.throws(()=>activationModule('const api={};export {api};',[{name:'api',functions:[]}],parse),/function-set/);
const source='async function run(){await Promise.resolve();return 3;}export {run};';
const result=activationModule(source,expected,parse);
const module=await import('data:text/javascript,'+encodeURIComponent(result.source));assert.equal(await module.run(),3);
""", parser=True)

    def test_actual_esbuild_capture_defers_both_modules_and_preserves_source_map_locations(self):
        tools = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
        if tools is None:
            self.skipTest('Pinned esbuild/Acorn compiler inputs are required for real bundle controls')
        tools = Path(tools)/'node_modules'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'src').mkdir()
            (root/'src/child.ts').write_text("console.info('transitive-init');export let state=0;export function bump(){return ++state;}\n")
            (root/'src/main.ts').write_text("import {bump} from './child.js';console.warn('direct-init');export const api={run(value:string){return value+':'+bump();}};\n")
            (root/'imports.json').write_text(json.dumps([profile.INTERFACE]))
            selected = {'moduleRoot': 'src', 'conditions': [], 'runtimeProfile': 'spidermonkey-public-sync-v1',
                'standardConsoleProfile': profile.PROFILE,
                'activationExports': [{'name': 'api', 'functions': [{'name': 'run', 'parameters': 1}]}]}
            (root/'configuration.json').write_text(json.dumps(selected))
            output = root/'application.mjs'
            command = [shutil.which('node'), str(ROOT/'tools/typescript_guest/bundle.mjs'),
                str(tools/'esbuild/lib/main.js'), str(root), str(root/'src/main.ts'), str(output),
                str(root/'imports.json'), str(root/'configuration.json'), str(tools/'acorn/dist/acorn.mjs')]
            result = subprocess.run(command, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

            actual = output.read_text()
            metadata = json.loads((root/'application.mjs.inputs.json').read_text())
            self.assertEqual(metadata['outputs']['application.mjs']['bytes'], len(output.read_bytes()))
            self.assertEqual(metadata['outputs']['application.mjs.map']['bytes'], len((root/'application.mjs.map').read_bytes()))
            self.assertEqual(actual.count("import * as __lsfConsoleLog from 'latent:log/log@0.1.0';"), 1)
            self.assertIn('__lsfInitializeApplication', actual)
            source_map = json.loads((root/'application.mjs.map').read_text())
            lines = actual.splitlines()
            digits = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
            source = original_line = original_column = 0
            observed = []
            for line, mappings in enumerate(source_map['mappings'].split(';')):
                for segment in mappings.split(','):
                    if not segment:
                        continue
                    values, number, shift = [], 0, 0
                    for char in segment:
                        value = digits.index(char)
                        number += (value & 31) << shift
                        if value & 32:
                            shift += 5
                        else:
                            values.append(-(number >> 1) if number & 1 else number >> 1)
                            number = shift = 0
                    if len(values) >= 4:
                        source += values[1]
                        original_line += values[2]
                        original_column += values[3]
                        if original_line == 0 and 'console.' in lines[line] and 'init' in lines[line]:
                            observed.append(source_map['sources'][source])
            self.assertEqual(set(observed), {'src/child.ts', 'src/main.ts'})
            # Only the owned test module substitutes its typed LOG sink. No
            # generated component or runtime-provider success is inferred.
            (root/'typed-log.mjs').write_text("export function write(level,message,fields){return globalThis.consoleTestWrite(level,message,fields);}\n")
            (root/'test-application.mjs').write_text(actual.replace(
                "from 'latent:log/log@0.1.0'", "from './typed-log.mjs'", 1))
            script = """
import assert from 'node:assert/strict';
const calls=[];globalThis.consoleTestWrite=(...args)=>{calls.push(args);return true;};
const module=await import('./test-application.mjs');assert.deepEqual(calls,[]);
assert.equal(module.api.run('value'),'value:1');assert.equal(module.api.run('next'),'next:2');
assert.deepEqual(calls,[['info','transitive-init',[]],['warn','direct-init',[]]]);
"""
            result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script],
                                    cwd=root, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)


    def test_owned_signed_fixture_keeps_sdk_default_profile_limits_and_original_greeting(self):
        from tools.typescript_guest.project import create, validate
        from tools.rust_capsule_project import snapshot
        with tempfile.TemporaryDirectory() as directory:
            app = create(Path(directory)/'application', 'greeting')
            before = snapshot(app)
            prepared = signed.prepare(app)
            after = snapshot(app)
            project, lock, _pins = validate(after)
            original = json.loads(before['capsule-project.json'])
            self.assertEqual(project, {**original, 'limits': {**original['limits'], 'logBytes': 16384}})
            self.assertEqual({k: v for k, v in after.items() if k.startswith('vendor/')},
                             {k: v for k, v in before.items() if k.startswith('vendor/')})
            self.assertEqual(lock['sdk'], json.loads(before['sdk-lock.json'])['sdk'])
            self.assertIn(b'Hello, ${clean}!', after['src/main.ts'])
            self.assertIn(b'Please enter a name.', after['src/main.ts'])
            self.assertEqual(after['wit/deps/log/package.wit'], (ROOT/'wit/platform/log/package.wit').read_bytes())
            self.assertEqual(prepared['cases'], list(signed.CASES))
            self.assertEqual(prepared['signedExecution'], 'pending')
            with self.assertRaisesRegex(Exception, 'original-world'):
                signed.prepare(app)

    def test_signed_programme_requires_preentry_denial_and_all_strict_accounted_cases(self):
        from types import SimpleNamespace
        from tools.phase2_operator_process import WorkflowError
        for bad in (False, True):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = {'service': 'examples/my-greeting', 'generation': '1', 'budget': {'logBytes': 16384}}
                client = SimpleNamespace(directory=root, call=lambda *a, **k: None)
                node = SimpleNamespace(startup_record={'providers': [{'id': 'log', 'capability': profile.INTERFACE,
                    'profile': 'activation-log-v1', 'tenant': 'examples', 'service': 'runtime-host', 'configurationDigest': 'fixed'}]})
                result = {'invocations': [], 'providerIdle': []}
                denied = {'exitCode': 4, 'response': {'error': {'code': 'permission-denied'}, 'outcomeKnown': True,
                    'data': {'terminalState': 'rejected', 'consumption': {'cpuFuel': '1' if bad else '0',
                        'peakMemoryBytes': '0', 'logBytes': '0'}}}}
                rows = [denied] + [{'activation': 'ts-console-'+str(i), 'response': {'data': {'consumption': {
                    'logBytes': '1234', 'outboundRequests': 0, 'childCalls': 0, 'effectCount': 0}}}} for i in range(8)]
                with patch('tools.rust_capsule_node.call', side_effect=rows) as call, \
                     patch('tools.rust_capsule_node.assert_value') as value, \
                     patch('tools.rust_capsule_node.deploy', return_value=target), \
                     patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}):
                    if bad:
                        with self.assertRaisesRegex(WorkflowError, 'reject-before-guest'):
                            signed.grant_and_probe(client, node, root, {'greeting': target}, {'greeting': 'publication'}, result)
                        self.assertEqual(call.call_count, 1)
                    else:
                        signed.grant_and_probe(client, node, root, {'greeting': target}, {'greeting': 'publication'}, result)
                        self.assertEqual([row['case'] for row in result['typescriptConsoleCases']], list(signed.CASES))
                        self.assertEqual(call.call_count, 9)
                        self.assertEqual(value.call_count, 8)
                        self.assertEqual(len(result['providerIdle']), 8)


if __name__ == '__main__':
    unittest.main()

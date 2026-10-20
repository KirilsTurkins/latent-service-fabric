"""Source/capture/protocol controls; these do not execute a guest component."""
import ast
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import embedded_resource_fixture as fixture, embedded_resource_probe as probe
from tools import qualify_embedded_resources as qualification
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_project import ROOT, digest, inventory, read_json, snapshot


def node_case(language, *, malformed=None):
    def call(_client,_target,_interface,_method,args,label):
        mode = args[0].removeprefix('resources:')
        consumption = {'cpuFuel':1,'peakMemoryBytes':1,'outboundRequests':0,'logBytes':0,'effectCount':0}
        row = {'activation':label,'processReaped':True,'exitCode':0,
            'response':{'outcomeKnown':True,'data':{'consumption':consumption}}}
        if mode == 'trap':
            row.update(exitCode=4)
            row['response']['error'] = {'code':'guest-trap'}
            row['response']['data']['terminalState'] = 'guest_trap'
        else:
            value = fixture.EXPECTED[language][mode]
            if malformed == 'nul' and mode == 'text': value = value.replace('\0','')
            row['decoded'] = [{'ok':value}]
        if malformed == 'effect': consumption['effectCount'] = 1
        if malformed == 'unreaped': row['processReaped'] = False
        return row
    result = {'invocations':[],'providerIdle':[],'samples':[]}
    idle = {'unavailable':False,'counters':{key:0 for key in ACTIVE_COUNTERS}}
    with patch('tools.rust_capsule_node.call',side_effect=call), \
            patch('tools.rust_capsule_node.provider_idle',return_value=idle), \
            patch('tools.rust_capsule_node.sample',return_value={'physical':'sample'}):
        probe.probe(None,{'grants':[],'budget':{'cpuFuel':10,'memoryBytes':10}},None,result,17,language=language)
    return result


class EmbeddedResources(unittest.TestCase):
    def test_three_real_outside_source_trees_have_exact_empty_nul_binary_and_ordinary_apis(self):
        for language in fixture.LANGUAGES:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                app,record = fixture.source_project(language,base/'app',base/'outside')
                child = base/'outside/data'
                assets = child/'src' if language == 'rust' else child
                self.assertEqual({name:(assets/name).read_bytes() for name in fixture.DATA},fixture.DATA)
                self.assertIn(b'\0',fixture.DATA['text.txt'])
                self.assertEqual(fixture.DATA['binary.bin'],b'\x00\xff\x80A\r\n')
                self.assertEqual(digest((app/'sdk-lock.json').read_bytes()),record['sdkLock'])
                self.assertEqual(set(record['packages']),set(fixture.PACKAGES[language]))
                self.assertEqual(record['outsideSource'],json.loads(inventory(snapshot(base/'outside'))))
                self.assertNotIn('capsule-resources.json',snapshot(app))
                code = (app/record['sourceFile']).read_bytes()
                self.assertIn(b'resources:',code)
                if language == 'go':
                    original = code.replace(b'\n    resource "'+fixture.PACKAGES['go'][0].encode()+b'"',b'',1)
                    original = original.replace(b'\n    if strings.HasPrefix(name, "resources:") { return wit.Ok[string, string](resource.Run(strings.TrimPrefix(name, "resources:"))) }',b'',1)
                elif language == 'rust':
                    original = code.replace(b'    if let Some(mode) = name.strip_prefix("resources:") { return Ok(outside_embedded_resource_library::run(mode)); }\n',b'',1)
                else:
                    original = code.removeprefix(b"import {resourceCase} from 'outside-embedded-resource-library';\n")
                    original = original.replace(b"\n    if (name.startsWith('resources:')) return resourceCase(name.slice(10));",b'',1)
                self.assertEqual(digest(original),record['originalSource'])

    def test_missing_transitive_edge_cannot_be_called_a_captured_resource_closure(self):
        for language,key in (('go','module'),('rust','package')):
            first,second = fixture.PACKAGES[language]
            version = 'v0.0.0' if language == 'go' else '0.1.0'
            lock = {'artifacts':[{'id':first,'role':'application','metadata':{key:first,'version':version},'dependencies':[second]},
                {'id':second,'role':'application','metadata':{key:second,'version':version},'dependencies':[]}]}
            fixture.verify_graph(language,lock,Path('not-read'))
            for broken in ('edge','package','version','duplicate'):
                changed = copy.deepcopy(lock)
                if broken == 'edge': changed['artifacts'][0]['dependencies'] = []
                elif broken == 'package': changed['artifacts'].pop()
                elif broken == 'version': changed['artifacts'][0]['metadata']['version'] = '9.9.9'
                else: changed['artifacts'].append(changed['artifacts'][0])
                with self.subTest(language=language,broken=broken), self.assertRaisesRegex(RuntimeError,'transitive-native'):
                    fixture.verify_graph(language,changed,Path('not-read'))

    def test_native_capture_seams_review_exact_candidate_before_removing_original_sources(self):
        for language in fixture.LANGUAGES:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                base = Path(temporary); app = base/'app'; outside = base/'outside'
                first,second = fixture.PACKAGES[language]
                key = 'module' if language == 'go' else 'package'
                version = 'v0.0.0' if language == 'go' else '0.1.0'
                lock = {'artifacts':[{'id':first,'role':'application','metadata':{key:first,'version':version},'dependencies':[second]},
                    {'id':second,'role':'application','metadata':{key:second,'version':version},'dependencies':[]}]}
                def resolve(_app,candidate,**_kwargs):
                    assets = outside/'data/src' if language == 'rust' else outside/'data'
                    self.assertEqual({name:(assets/name).read_bytes() for name in fixture.DATA},fixture.DATA)
                    if language == 'typescript':
                        (app/'npm-resolved.lock.json').write_bytes(json.dumps({'nodes':[
                            {'location':'node_modules/'+name,'selected':True} for name in (first,second)]}).encode())
                    candidate.write_bytes(json.dumps(lock).encode())
                    return lock
                def review(_app,candidate,identity):
                    self.assertEqual(identity,digest(candidate.read_bytes()))
                    self.assertTrue((outside/'library').is_dir())
                    self.assertTrue((outside/'data').is_dir())
                    (app/'latent.dependencies.lock.json').write_bytes(candidate.read_bytes())
                targets = {
                    'go':('tools.go_native_authoring.edit','tools.go_native_authoring.create_lock',
                        'tools.go_application_dependencies.resolve','tools.go_dependency_authoring.review'),
                    'rust':('tools.cargo_native_authoring.author',None,
                        'tools.rust_application_dependencies.resolve','tools.rust_dependency_authoring.review'),
                    'typescript':('tools.typescript_dependency_authoring.edit','tools.npm_lock_authoring.create_lock',
                        'tools.typescript_application_dependencies.resolve','tools.typescript_dependency_authoring.review')}
                edit,locked,resolved,reviewed = targets[language]
                edited = stack.enter_context(patch(edit))
                if locked: stack.enter_context(patch(locked))
                stack.enter_context(patch(resolved,side_effect=resolve))
                stack.enter_context(patch(reviewed,side_effect=review))
                verified = SimpleNamespace(identity='sha256:'+'1'*64)
                stack.enter_context(patch.object(fixture,'verify_inputs',return_value=verified))
                compiler = (Path('unused-node'),Path('unused-npm')) if language == 'typescript' else Path('unused-compiler')
                selected,record = fixture.capture(language,app,outside,compiler)
                self.assertEqual(selected,app)
                self.assertEqual(edited.call_count,2 if language == 'go' else 1)
                self.assertTrue(record['originalsRemoved'])
                self.assertFalse((outside/'library').exists())
                self.assertFalse((outside/'data').exists())
                self.assertEqual(record['candidateDigest'],digest((app/'latent.dependencies.lock.json').read_bytes()))
                self.assertEqual(record['sdkLock'],digest((app/'sdk-lock.json').read_bytes()))
                self.assertFalse(record['applicationResourceBridge'])

    def test_typescript_requires_both_selected_native_nodes_not_just_an_archive_name(self):
        first,second = fixture.PACKAGES['typescript']
        nodes = [{'location':'node_modules/'+name,'selected':True} for name in (first,second)]
        with patch.object(fixture,'read_json',return_value={'nodes':nodes}):
            fixture.verify_graph('typescript',{},Path('not-read'))
        nodes[-1]['selected'] = False
        with patch.object(fixture,'read_json',return_value={'nodes':nodes}), self.assertRaisesRegex(RuntimeError,'transitive-npm'):
            fixture.verify_graph('typescript',{},Path('not-read'))

    def test_compiler_observation_rejects_old_text_only_embedding_and_foreign_standard_packages(self):
        value = {'packages':[{'importPath':name,'standard':True,'embedFiles':[]} for name in ('embed','io/fs')]+[
            {'importPath':fixture.PACKAGES['go'][1],'standard':False,'embedFiles':sorted(fixture.DATA)}]}
        qualification.selected_go_packages(value)
        for broken in ('old-text-only','empty-omitted','duplicate','false-standard'):
            changed = copy.deepcopy(value)
            if broken == 'old-text-only': changed['packages'][-1]['embedFiles'] = ['message.txt']
            elif broken == 'empty-omitted': changed['packages'][-1]['embedFiles'].remove('empty.bin')
            elif broken == 'duplicate': changed['packages'].append(changed['packages'][-1])
            else: changed['packages'][0]['standard'] = False
            with self.subTest(broken=broken), self.assertRaisesRegex(RuntimeError,'embedded-resource-Go'):
                qualification.selected_go_packages(changed)

    def test_signed_protocol_requires_all_exact_values_trap_and_fresh_without_effects(self):
        for language in fixture.LANGUAGES:
            with self.subTest(language=language):
                result = node_case(language)
                expected = len(fixture.EXPECTED[language])+2
                self.assertEqual(len(result['invocations']),expected)
                self.assertEqual(len(result['providerIdle']),expected)
                self.assertEqual(len(result['samples']),expected)
                self.assertEqual(result['embeddedResourceConformance']['freshAfterTrap']['decoded'],
                    [{'ok':fixture.EXPECTED[language]['binary']}])
                self.assertFalse(result['embeddedResourceConformance']['resourceStreamClosureIsHostRetirement'])
                for malformed in ('nul','effect','unreaped'):
                    with self.subTest(malformed=malformed), self.assertRaises(RuntimeError):
                        node_case(language,malformed=malformed)

    def test_final_projection_preserves_named_baseline_and_rejects_live_or_borrowed_evidence(self):
        for language in fixture.LANGUAGES:
            ancestry = {'normalActivations':['original-normal'],'physicalSamples':1,'idleSamples':0}
            node = node_case(language)
            node.update(status='passed',language=language,nodeShutdown={'reaped':True,'record':{'clean':True}})
            node['invocations'].insert(0,{'activation':'original-normal','processReaped':True,'response':{'outcomeKnown':True}})
            node['samples'].insert(0,{'original':'physical'})
            qualification.observation(node,ancestry,language)
            for malformed in ('baseline','duplicate','owner','fresh','case','shutdown'):
                changed = copy.deepcopy(node)
                if malformed == 'baseline': changed['invocations'][0]['activation'] = 'different-normal'
                elif malformed == 'duplicate': changed['invocations'].append(changed['invocations'][-1])
                elif malformed == 'owner': changed['providerIdle'][-1]['counters'][ACTIVE_COUNTERS[0]] = 1
                elif malformed == 'fresh': changed['embeddedResourceConformance']['freshAfterTrap'] = changed['invocations'][0]
                elif malformed == 'case': changed['embeddedResourceConformance']['cases'].pop()
                else: changed['nodeShutdown']['record']['clean'] = False
                with self.subTest(language=language,malformed=malformed), self.assertRaises((RuntimeError,KeyError)):
                    qualification.observation(changed,ancestry,language)

    def test_historical_or_wrong_current_normal_source_refuses_before_product_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw = b'{"original":"historical"}\n'
            (directory/'source-inputs.json').write_bytes(raw)
            (directory/'qualification.json').write_bytes(json.dumps({'schemaVersion':'latent.go-capsule.qualification.v1',
                'status':'passed','sourceIdentityDigest':digest(raw)}).encode())
            with patch.object(qualification,'inputs',return_value={'current':'different'}), \
                    self.assertRaisesRegex(RuntimeError,'original-current-normal'):
                qualification.prepared(directory,'go')

    def test_original_runner_ast_is_preserved_except_default_false_guard_and_one_probe(self):
        source = (ROOT/'tools/run_rust_capsule_workflow.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name == 'run')
        self.assertEqual(function.args.kwonlyargs[-1].arg,'embedded_resource_conformance')
        self.assertFalse(function.args.kw_defaults[-1].value)
        function.args.kwonlyargs.pop(); function.args.kw_defaults.pop()
        class Projection(ast.NodeTransformer):
            def visit_Expr(self,node):
                return None if 'embedded-resource-selector' in ast.unparse(node) else self.generic_visit(node)
            def visit_If(self,node):
                if isinstance(node.test,ast.Name) and node.test.id == 'embedded_resource_conformance': return None
                return self.generic_visit(node)
        tree = Projection().visit(tree)
        actual = hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()
        self.assertEqual(actual,'2170a595bdc3c57118cc1fc102bd58b39b49ce4aa13a10dea72da6e80925da8c')


if __name__ == '__main__': unittest.main()

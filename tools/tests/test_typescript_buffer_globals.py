"""Pinned compiler mechanisms and real provenance readers, not signed guests."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.rust_capsule_project import ROOT, inventory
from tools.typescript_guest import buffer_profile
BASELINE = '95b8d8b16c29d94755262345a305401ee99a801f'


class BufferGlobalControls(unittest.TestCase):
    def tools(self):
        selected = os.environ.get('LSF_TYPESCRIPT_FRONTEND')
        node = shutil.which('node')
        if not selected or not node:
            self.skipTest('explicit pinned TypeScript frontend required; owning qualification refuses skips')
        root = Path(selected)
        for name in ('esbuild/lib/main.js', 'acorn/dist/acorn.mjs', 'typescript/bin/tsc'):
            self.assertTrue((root/'node_modules'/name).is_file(), name)
        self.assertEqual(subprocess.check_output([node, '--version'], text=True).strip(), 'v24.19.0')
        return node, root

    def javascript(self, body):
        node, tools = self.tools()
        source = "import assert from 'node:assert/strict';\n"
        source += 'import {parse} from '+json.dumps((tools/'node_modules/acorn/dist/acorn.mjs').as_uri())+';\n'
        source += 'import {bufferGlobalReferences} from '+json.dumps((ROOT/'tools/typescript_guest/buffer_globals.mjs').as_uri())+';\n'
        result = subprocess.run([node, '--input-type=module', '-e', source+body], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def bundle(self, project, *, script=None):
        node, tools = self.tools()
        (project/'imports.json').write_text('[]')
        (project/'configuration.json').write_text(json.dumps({'moduleRoot':'dependencies/npm/node_modules'}))
        result = subprocess.run([node, script or ROOT/'tools/typescript_guest/bundle.mjs',
            tools/'node_modules/esbuild/lib/main.js', project, project/'main.ts', project/'out.mjs',
            project/'imports.json', project/'configuration.json', tools/'node_modules/acorn/dist/acorn.mjs'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        return (project/'out.mjs').read_bytes(), json.loads((project/'out.mjs.inputs.json').read_bytes())

    def test_selector_distinguishes_real_global_references_from_lexical_bindings(self):
        self.javascript(r"""
for(const source of [
 'export const x=Buffer.alloc(1)', 'function f(x=Buffer.alloc(1)){var Buffer;return x}',
 'class C {static value=Buffer.alloc(1)}', 'const {[Buffer.from("x")]: x}=value',
 'function f(){return Buffer}; var x=1', 'Buffer=someOtherConstructor',
])assert.deepEqual(bufferGlobalReferences(source,parse),['Buffer'],source);
for(const source of [
 'const Buffer=1; export {Buffer}', 'function f(Buffer){return Buffer}',
 'function f(){return Buffer;var Buffer}', 'const {Buffer}=value;Buffer.alloc(1)',
 'const {x:Buffer=1}=value;Buffer', 'try{}catch(Buffer){Buffer.alloc(1)}',
 'class Buffer{static x=Buffer}', 'class C{static {var Buffer;Buffer}}',
 'for(let Buffer of values){Buffer.alloc(1)}', 'const x={Buffer:1,Buffer(){}}',
 'import {Buffer} from "node:buffer";Buffer.alloc(1)',
 'function f(globalThis){return globalThis.Buffer}',
])assert.deepEqual(bufferGlobalReferences(source,parse),[],source);
assert.deepEqual(bufferGlobalReferences('globalThis.Buffer.from("x");globalThis["Buffer"];Buffer',parse),['Buffer','globalThis.Buffer']);
assert.deepEqual(bufferGlobalReferences('Reflect.get(globalThis,"Buffer")',parse),[]); // not a reflection certificate
// Pure source-derived small-bound control; the production cap stays one million.
const original=bufferGlobalReferences.toString(),needle='if (++count > 1000000)';
assert.equal(original.split(needle).length,2);
const bounded=await import('data:text/javascript,'+encodeURIComponent('export '+original.replace(needle,'if (++count > 8)')));
assert.throws(()=>bounded.bufferGlobalReferences('const {a,b,c,d}=value;',parse),/buffer-global-selection-node-bound/);
""")

    def test_pinned_bundle_installs_same_real_global_before_transitive_esm_and_commonjs(self):
        node, _ = self.tools()
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project/'esm.mjs').write_text('export const initial = Buffer.from([65]);')
            (project/'child.cjs').write_text('module.exports = {initial:globalThis.Buffer.alloc(2,66)};')
            (project/'main.ts').write_text('''import {initial} from './esm.mjs';
import child from './child.cjs'; import {Buffer as a} from 'buffer'; import {Buffer as b} from 'node:buffer';
export function check(){
 if(Buffer!==a||a!==b||globalThis.Buffer!==a||initial[0]!==65||child.initial[1]!==66)throw Error('preinit/alias');
 const original=Buffer;globalThis.Buffer=17;if(Buffer!==17)throw Error('global reassignment');
 globalThis.Buffer=original;return original.from([1,2]).readUInt16BE(0);
}''')
            raw, selected = self.bundle(project)
            self.assertEqual(selected['standardBufferGlobalReferences'], ['Buffer','globalThis.Buffer'])
            node_check = 'delete globalThis.Buffer;const app=await import('+json.dumps((project/'out.mjs').as_uri())+');if(app.check()!==258)throw Error("numeric");'
            result = subprocess.run([node,'--input-type=module','-e',node_check],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            conflict = subprocess.run([node,'--input-type=module','-e','await import('+json.dumps((project/'out.mjs').as_uri())+')'],capture_output=True,text=True,timeout=20)
            self.assertNotEqual(conflict.returncode,0)
            self.assertIn('compiler-owned-buffer-global-already-present',conflict.stderr)
            self.assertNotIn(b'export { originalBuffer as Buffer',raw)
            # The private bootstrap cannot be imported by an application.
            (project/'out.mjs').unlink();(project/'out.mjs.inputs.json').unlink()
            (project/'main.ts').write_text('import "lsf:typescript-buffer-global-initializer";export const x=1')
            with self.assertRaises(AssertionError) as error:self.bundle(project)
            self.assertIn('compiler-private-buffer-global-initializer',str(error.exception))
            for label,source in [('global-only','export const value=Buffer.alloc(1,7)[0]'),
                                 ('snapshot-clock','export const value=Buffer.from(String(Date.now()))')]:
                child=project/label;child.mkdir();(child/'main.ts').write_text(source)
                _,metadata=self.bundle(child)
                self.assertEqual(metadata['standardBufferModules'],['node:buffer'])
                command='delete globalThis.Buffer;const app=await import('+json.dumps((child/'out.mjs').as_uri())+');if(app.value!==7)throw Error("bytes");'
                actual=subprocess.run([node,'--input-type=module','-e',command],capture_output=True,text=True,timeout=20)
                if label=='global-only':self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
                else:
                    self.assertNotEqual(actual.returncode,0)
                    self.assertIn('snapshot-time-clock-observation-unsupported',actual.stderr)

    def test_unselected_shadowed_and_erased_bundles_are_byte_identical_to_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/'old';old.mkdir()
            names=subprocess.check_output(['git','--no-lazy-fetch','ls-tree','-r','--name-only',BASELINE,'--','tools/typescript_guest'],cwd=ROOT,text=True).splitlines()
            for name in names:
                if name.endswith('.mjs'):(old/Path(name).name).write_bytes(subprocess.check_output(['git','--no-lazy-fetch','show',BASELINE+':'+name],cwd=ROOT))
            for index,body in enumerate((
                'export function run(){return 42}',
                'function unused(){return Buffer.alloc(1)};export function run(Buffer){return Buffer+1}',
                'import {Buffer} from "node:buffer";export function run(){return Buffer.from([1])[0]}',
            )):
                project=root/str(index);project.mkdir();(project/'main.ts').write_text(body)
                before,meta=self.bundle(project,script=old/'bundle.mjs')
                (project/'out.mjs').unlink();(project/'out.mjs.inputs.json').unlink()
                (project/'out.mjs.map').unlink()
                after,new=self.bundle(project)
                self.assertEqual(after,before)
                self.assertEqual(new,meta)

    def test_selected_declaration_reaches_real_strict_tsc_and_leaves_unselected_bytes(self):
        node,tools=self.tools()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);first=root/'generated';second=root/'second';first.mkdir();second.mkdir()
            declaration=(ROOT/buffer_profile.GLOBAL_RECIPE['declaration']).read_bytes()
            for directory in (first,second):(directory/'buffer-runtime.d.ts').write_bytes((ROOT/buffer_profile.DECLARATION).read_bytes())
            original=inventory({p.name:p.read_bytes() for p in first.iterdir()})
            def absent():raise AssertionError('unselected capture read')
            buffer_profile.prepare_global_declarations(None,declaration,absent,(first,second))
            self.assertEqual(inventory({p.name:p.read_bytes() for p in first.iterdir()}),original)
            (root/'main.ts').write_text('const value:Buffer=Buffer.from("x");export const count:number=value.length;')
            (root/'tsconfig.json').write_text(json.dumps({'compilerOptions':{'target':'ES2022','module':'ESNext','moduleResolution':'Bundler','strict':True,'noEmit':True,'lib':['ES2022'],'types':[], 'paths':{'node:buffer':['./generated/buffer-runtime.d.ts']}},'include':['main.ts','generated/*.d.ts']}))
            argv=[node,tools/'node_modules/typescript/bin/tsc','--project',root/'tsconfig.json']
            failed=subprocess.run(argv,capture_output=True,text=True,timeout=30);self.assertNotEqual(failed.returncode,0)
            buffer_profile.prepare_global_declarations({'globalBufferInstalled':True},declaration,lambda:declaration,(first,second))
            passed=subprocess.run(argv,capture_output=True,text=True,timeout=30);self.assertEqual(passed.returncode,0,passed.stdout+passed.stderr)
            self.assertEqual(inventory({p.name:p.read_bytes() for p in first.iterdir()}),inventory({p.name:p.read_bytes() for p in second.iterdir()}))
            (second/'buffer-runtime-globals.d.ts').unlink()
            buffer_profile.prepare_global_declarations({'globalBufferInstalled':True},declaration,lambda:declaration,(second,),provided_node=True)
            self.assertFalse((second/'buffer-runtime-globals.d.ts').exists())
            with self.assertRaisesRegex(ValueError,'captured TypeScript global Buffer'):
                buffer_profile.prepare_global_declarations({'globalBufferInstalled':True},declaration,lambda:b'forged',(first,second))

    def test_actual_context_and_outcome_readers_bind_complete_global_source_group(self):
        from tools.tests.test_guest_compatibility_buffer import CapturedBuffer,COMPONENT
        from tools import guest_compatibility as compatibility,guest_compatibility_context as context
        from tools.dev_workflow.common import digest,encode
        with tempfile.TemporaryDirectory() as temporary:
            fixture=CapturedBuffer(Path(temporary))
            extra={name:(ROOT/name).read_bytes() for name in buffer_profile.GLOBAL_RECIPE.values()}
            fixture.files['vendor/lsf/'+buffer_profile.GLOBAL_RECIPE['declaration']]=extra[buffer_profile.GLOBAL_RECIPE['declaration']]
            fixture.source=inventory(fixture.files)
            fixture.recipe=inventory({buffer_profile.BACKEND:fixture.backend,buffer_profile.DECLARATION:(ROOT/buffer_profile.DECLARATION).read_bytes(),**extra})
            fixture.write_bound('recipe-inputs.json','build-recipe',fixture.recipe)
            fixture.selection=buffer_profile.check_selection({'standardBufferModules':['node:buffer'],'standardBufferProfile':buffer_profile.PROFILE,'standardBufferBackendDigest':digest(fixture.backend),'standardBufferGlobalProfile':buffer_profile.GLOBAL_PROFILE,'standardBufferGlobalReferences':['Buffer'],'standardBufferGlobalIdentities':{key:value for key,value in buffer_profile.global_identities(ROOT).items() if key!='declaration'}},digest(fixture.backend),buffer_profile.global_identities(ROOT))
            fixture.write_bound('typescript-buffer-selection.json',context.BUFFER_MATERIALS[0],encode(fixture.selection))
            compiled=fixture.root/'compiled';compiled.mkdir()
            (compiled/'typescript-buffer-selection.json').write_bytes(encode(fixture.selection))
            assets,materials=buffer_profile.retain_selection(compiled,fixture.output,digest(fixture.backend),buffer_profile.global_identities(ROOT))
            self.assertEqual(assets[0][2],'application/vnd.latent.typescript.buffer-selection.v2+json')
            self.assertEqual(materials[0]['digest'],digest(encode(fixture.selection)))
            fixture.report=compatibility.report('typescript',digest(fixture.source),digest(COMPONENT),'lsf-host-abi-phase3-v5',[],[compatibility.finding('unresolved-behavior','initialization','not-evaluated')])
            (fixture.output/'source-inputs.json').write_bytes(fixture.source)
            (fixture.output/'compatibility-report.json').write_bytes(encode(fixture.report))
            value=fixture.finish();self.assertEqual(fixture.read().context_state,'observed')
            self.assertIn('SELECTED runtime global: Buffer',context.present(value))
            for name in context.BUFFER_GLOBAL_MATERIALS:self.assertIn(name,context.buffer_module(value))
            changed=copy.deepcopy(value)
            changed['materials']=[row for row in changed['materials'] if row['name'] not in context.BUFFER_GLOBAL_MATERIALS]
            changed['identity']=digest(encode({key:item for key,item in changed.items() if key!='identity'}))
            (fixture.output/'compatibility-context.json').write_bytes(encode(changed))
            self.assertEqual(fixture.read().context_state,'invalid-present')
            changed=copy.deepcopy(value)
            changed['materials']=[row for row in changed['materials']
                if row['name'] not in (*context.BUFFER_MATERIALS,*context.BUFFER_GLOBAL_MATERIALS)]
            changed['identity']=digest(encode({key:item for key,item in changed.items() if key!='identity'}))
            (fixture.output/'compatibility-context.json').write_bytes(encode(changed))
            self.assertEqual(fixture.read().context_state,'invalid-present')
            for field,bad in [('globalBufferInstalled',1),('nativeStorage',0.0)]:
                altered=dict(fixture.selection,**{field:bad})
                with self.assertRaises(ValueError):buffer_profile.validate_selection(altered,digest(fixture.backend),buffer_profile.global_identities(ROOT))
            altered=copy.deepcopy(fixture.selection)
            altered['globalProvision']['identities']['initializer']='sha256:'+'0'*64
            with self.assertRaises(ValueError):buffer_profile.validate_selection(altered,digest(fixture.backend),buffer_profile.global_identities(ROOT))
        with tempfile.TemporaryDirectory() as temporary:
            fixture=CapturedBuffer(Path(temporary))
            value=fixture.finish()
            self.assertEqual(fixture.read().context_state,'observed')
            removed=copy.deepcopy(value)
            removed['materials']=[row for row in removed['materials'] if row['name'] not in context.BUFFER_MATERIALS]
            removed['identity']=digest(encode({key:item for key,item in removed.items() if key!='identity'}))
            (fixture.output/'compatibility-context.json').write_bytes(encode(removed))
            self.assertEqual(fixture.read().context_state,'invalid-present')
            # A valid module-only v1 receipt cannot authenticate extra global
            # material rows, even with a freshly rehashed complete context.
            value['materials'].extend(context.material('runtime',name,identity,
                profile=context.BUFFER_GLOBAL_PROFILE) for name,identity in
                zip(context.BUFFER_GLOBAL_MATERIALS,buffer_profile.global_identities(ROOT).values()))
            value['identity']=digest(encode({key:item for key,item in value.items() if key!='identity'}))
            context.validate(value,report=fixture.report,component=digest(COMPONENT))
            (fixture.output/'compatibility-context.json').write_bytes(encode(value))
            self.assertEqual(fixture.read().context_state,'invalid-present')

"""Closed fixture derivation controls; no canonical component is built or run."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.typescript_guest import owned_result_fixture as fixture

ROOT=Path(__file__).resolve().parents[2]


class TypeScriptOwnedFixtureTests(unittest.TestCase):
    def javascript(self,body):
        node=shutil.which('node')
        if node is None:self.skipTest('Node required for fixture source controls only')
        parser=os.environ.get('LSF_TYPESCRIPT_ACORN')
        imports="import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';import {createHash} from 'node:crypto';\n"
        if parser:
            self.assertTrue(Path(parser).is_file())
            imports+=f"import {{parse}} from {json.dumps(Path(parser).as_uri())};\n"
        else:
            # Source-test mechanism only. The future owning component compiler
            # requires its actual original pinned Acorn, with no fallback.
            imports+="const scope={};vm.runInNewContext(process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'],scope);const {parse}=scope.acorn;\n"
        base=ROOT/'tools/typescript_guest'
        imports+=f"import {{directIdleTaskSlots,fuseNativeImportAwaits,inlineNativeTaskMeta}} from {json.dumps((base/'async_waiters.mjs').as_uri())};\n"
        imports+=f"import {{ownedResultFixtureBindings,ownFixtureSelection}} from {json.dumps((base/'owned_result_fixture.mjs').as_uri())};\n"
        for variable,name,field in [('prefix','typescript_native_task_state.json','prefixSha256'),('binding','typescript_native_open_binding.json','sourceSha256')]:
            imports+=f"const {variable}Material=JSON.parse(await readFile(new URL({json.dumps((ROOT/'tools/tests/fixtures'/name).as_uri())}),'utf8'));assert.equal(createHash('sha256').update({variable}Material.source).digest('hex'),{variable}Material.{field});\n"
        imports+="const captured=bindingMaterial.source.replace('\\n  try {','\\n  /* lsf-owned-result-transfer:wit-result */\\n  try {');const selected=ownFixtureSelection.map(row=>captured.replaceAll('import_latent_http_streaming_0_3_0$open',row.binding));const source=inlineNativeTaskMeta(fuseNativeImportAwaits(directIdleTaskSlots(prefixMaterial.source+selected.join('\\n')),parse),parse);\n"
        result=subprocess.run([node,'--input-type=module','-e',imports+body],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_captured_shapes_get_only_three_closed_carrier_reactions(self):
        self.javascript(r"""
const transformed=ownedResultFixtureBindings(source,parse);
assert.equal((transformed.match(/const carrier=\$/g)||[]).length,3);
assert.equal((transformed.match(/carrier.then\(/g)||[]).length,3);
assert.equal((transformed.match(/__lsfImports.delivered\(/g)||[]).length,(source.match(/__lsfImports.delivered\(/g)||[]).length);
assert.equal((transformed.match(/await task.enter\(\)/g)||[]).length,3);
assert(!transformed.includes('setStatus'));assert(!transformed.includes('pumpHook'));
parse(transformed,{ecmaVersion:'latest',sourceType:'module'});
assert.throws(()=>ownedResultFixtureBindings(transformed,parse),/shape-drift/);
""")

    def test_missing_first_yield_unknown_native_call_and_module_collision_refuse(self):
        self.javascript("""
for(const changed of [source.replace('await task.enter()','task.enter()'),
 source.replace('await task.enter()','await other.enter()'),
 source.replace('$'+ownFixtureSelection[0].binding,'$differentNative'),
 source+'\\nconst __ownedFixtureContext=null;',source+"\\nconst reserved='tests:owned-result/control@1.0.0';"]){
 assert.throws(()=>ownedResultFixtureBindings(changed,parse),/shape-drift/);
}
""")

    def test_fixture_frontend_is_separate_and_normal_inputs_stay_identical(self):
        normal=ROOT/'tools/typescript_guest/componentize.mjs';before=normal.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'fixture';record=fixture.prepare(output)
            self.assertEqual(normal.read_bytes(),before)
            derived=(output/'recipe/componentize.mjs').read_bytes()
            self.assertEqual(derived.count(b'generatedBindings = ownedResultFixtureBindings('),1)
            self.assertEqual(derived.count(b'generatedBindings = borrowReleaseHandoff('),0)
            inverse=derived.replace(b"\nimport {ownedResultFixtureBindings} from './owned_result_fixture.mjs';",b'',1)
            inverse=inverse.replace(b'generatedBindings = ownedResultFixtureBindings(generatedBindings, parseBindings);',
                                    b'generatedBindings = borrowReleaseHandoff(generatedBindings, parseBindings);',1)
            self.assertEqual(inverse,before)
            self.assertEqual((output/'recipe/async_waiters.mjs').read_bytes(),(ROOT/'tools/typescript_guest/async_waiters.mjs').read_bytes())
            self.assertFalse(record['runtimePumpPatched']);self.assertFalse(record['canonicalIntrinsicsMocked'])
            self.assertFalse(record['signedExecution']);self.assertEqual(len(record['cases']),11)
            with self.assertRaises(FileExistsError):fixture.prepare(output)

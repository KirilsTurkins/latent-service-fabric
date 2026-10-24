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
        self.javascript('const {nativeCarrierImports}=await import('+json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())+');\n'+r"""
const native=nativeCarrierImports(fuseNativeImportAwaits(directIdleTaskSlots(prefixMaterial.source+selected.join('\n')),parse),parse);
const transformed=ownedResultFixtureBindings(native,parse);
assert.equal((transformed.match(/const carrier=\$/g)||[]).length,3);
assert.equal((transformed.match(/carrier.then\(/g)||[]).length,3);
assert.equal((transformed.match(/__lsfImports.delivered\(/g)||[]).length,(source.match(/__lsfImports.delivered\(/g)||[]).length);
assert.equal((transformed.match(/await task.enter\(\)/g)||[]).length,0);
assert.equal((transformed.match(/await __lsfAwaitImport\(/g)||[]).length,3);
assert(!transformed.includes('setStatus'));assert(!transformed.includes('pumpHook'));
parse(transformed,{ecmaVersion:'latest',sourceType:'module'});
assert.throws(()=>ownedResultFixtureBindings(transformed,parse),/shape-drift/);
assert.throws(()=>ownedResultFixtureBindings(source,parse),/shape-drift/);
""")

    def test_missing_first_yield_unknown_native_call_and_module_collision_refuse(self):
        self.javascript('const {nativeCarrierImports}=await import('+json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())+');\n'+"""
const native=nativeCarrierImports(fuseNativeImportAwaits(directIdleTaskSlots(prefixMaterial.source+selected.join('\\n')),parse),parse);
for(const changed of [native.replace('await __lsfAwaitImport','__lsfAwaitImport'),
 native.replace('await __lsfAwaitImport','await otherNative'),
 native.replace('$'+ownFixtureSelection[0].binding,'$differentNative'),
 native+'\\nconst __ownedFixtureContext=null;',native+"\\nconst reserved='tests:owned-result/control@1.0.0';"]){
 assert.throws(()=>ownedResultFixtureBindings(changed,parse),/shape-drift/);
}
""")

    def test_backing_fixture_captures_only_readonly_count_and_closed_fourth_import(self):
        self.javascript('const {nativeCarrierImports}=await import('+json.dumps((ROOT/'tools/typescript_guest/async_waiters.mjs').as_uri())+');\n'+r"""
const backing=captured.replaceAll('import_latent_http_streaming_0_3_0$open','import_tests_owned_result_provider_1_0_0$backing');
const input=nativeCarrierImports(fuseNativeImportAwaits(directIdleTaskSlots(prefixMaterial.source+[...selected,backing].join('\n')),parse),parse);
const transformed=ownedResultFixtureBindings(input,parse,true);
assert.equal((transformed.match(/const carrier=\$/g)||[]).length,4);
assert.equal((transformed.match(/carrier.then\(/g)||[]).length,4);
assert.equal((transformed.match(/backingFreeCount\(\)\{return __lsfImports.backingFreeCount\(\);\}/g)||[]).length,1);
const native=nativeCarrierImports(fuseNativeImportAwaits(directIdleTaskSlots(prefixMaterial.source+selected.join('\n')),parse),parse);
assert(!ownedResultFixtureBindings(native,parse).includes('__lsfImports.backingFreeCount'));
assert.throws(()=>ownedResultFixtureBindings(input,parse,1),/shape-drift/);
assert.throws(()=>ownedResultFixtureBindings(source,parse,true),/shape-drift/);
parse(transformed,{ecmaVersion:'latest',sourceType:'module'});
""")
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'fixture'
            record=fixture.prepare(output,backing=True)
            self.assertEqual(record['cases'],list(fixture.CASE_NAMES))
            self.assertEqual(record['backingCases'],list(fixture.BACKING_CASE_NAMES))
            self.assertEqual(len(record['cases']),11)
            self.assertEqual(len(record['backingCases']),8)
            self.assertIn('backing-run:async func', (output/'world.wit').read_text())
            self.assertIn('zero:list<u8>',(output/'world.wit').read_text())
            self.assertNotIn('tuple<>',(output/'world.wit').read_text())
            self.assertFalse(record['zeroStrideNormalComponentSupported'])
            self.assertFalse(record['zeroStrideNormalComponentQualified'])
            self.assertIn(b'ownedResultFixtureBindings(generatedBindings, parseBindings, true)',
                          (output/'recipe/componentize.mjs').read_bytes())
            application=(output/'application.js').read_text()
            self.javascript('parse('+json.dumps(application)+",{ecmaVersion:'latest',sourceType:'module'});")

    def test_fixture_frontend_is_separate_and_normal_inputs_stay_identical(self):
        from unittest.mock import patch
        normal=ROOT/'tools/typescript_guest/componentize.mjs';before=normal.read_bytes()
        # Exercise the actual closed copy selector against both reviewed
        # frontend import forms without executing the compiler or SDK.
        helper=b" from './borrow_probe.mjs';"
        imports=(b'import { borrowProbeBindings, borrowProbeProfile }'+helper,
                 b'import { borrowProbeBindings, borrowProbeProfile, borrowProbeSpliceCapture }'+helper)
        for selected in imports:
            with patch.object(fixture,'read_file',return_value=selected):
                self.assertEqual(fixture.frontend_files().count('borrow_probe.mjs'),1)
        for selected in (imports[0]+b'\n'+imports[1],imports[0]+b'\n'+imports[0],
                         b'import { unreviewed }'+helper):
            with patch.object(fixture,'read_file',return_value=selected):
                with self.assertRaisesRegex(ValueError,'owned-fixture-normal-borrow-helper-import-drift'):
                    fixture.frontend_files()
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

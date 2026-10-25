"""Real reviewed Node24 declarations and strict TSC; no package execution."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.application_dependencies import prepare, verify_inputs
from tools.rust_capsule_project import ROOT, read_file, read_json
from tools.typescript_application_dependencies import npm_archive_files
from tools.typescript_guest import buffer_profile, net_profile, standard_global_types as types

BASELINE = '570ab481ad0d802704cf3c553f520eb1be20af04'
NODE_SRI = 'sha512-93d49wCWJkCyN87MxLpNN6KXPCwFw7bVUg79mGUV1OS40JGWwVCr8n61DXCSqz7CV6/VfPkb7xec7uP2M+QHWQ=='


class InlineStandardGlobalTypes(unittest.TestCase):
    def test_real_captured_inline_provider_strict_types_and_classic_byte_identity(self):
        captured = os.environ.get('LSF_SMART_BUFFER_CAPTURE')
        if not captured:
            self.skipTest('explicit normal SmartBuffer capture required; owning programme refuses skips')
        from tools.tests.test_typescript_buffer_globals import BufferGlobalControls
        from tools.tests.test_typescript_standard_global_types import StandardGlobalTypes
        node, frontend = BufferGlobalControls().tools()
        app = Path(captured).resolve(strict=True)
        verified = verify_inputs(app, 'typescript')
        self.assertIsNotNone(verified)
        self.assertEqual(verified.lock['transformations'], [])
        native = read_json(app/'package-lock.json')
        self.assertEqual(set(native['packages']), {'', 'node_modules/smart-buffer',
            'node_modules/@types/node', 'node_modules/undici-types'})
        self.assertEqual(native['packages']['node_modules/@types/node']['version'], '24.19.2')
        self.assertEqual(native['packages']['node_modules/@types/node']['integrity'], NODE_SRI)
        archives = [row for row in verified.lock['artifacts']
            if row['metadata'].get('assetType') == 'original-package-archive'
            and row['metadata'].get('nativeLocation') == 'node_modules/@types/node']
        self.assertEqual(len(archives), 1)
        original = archives[0]['original']
        self.assertEqual(original, {'size':474850,
            'digest':'sha256:e01cc90bdafb14295f15a8dfbcddd37834250e9dfab4763ff686fb751915d9ce'})
        original_files = npm_archive_files(verified.store.get(original['digest'], original['size']))
        self.assertNotIn('web-globals/performance.d.ts', original_files)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);work = root/'work';output = root/'receipt'
            work.mkdir();output.mkdir()
            closure = prepare(app, work, output, 'typescript')
            selected = types.select(closure)
            self.assertEqual(types.select(verified), selected)
            self.assertEqual(selected['package'], {'name':'@types/node','version':'24.19.2'})
            self.assertEqual(len(selected['files']), 4)
            runtime, clock = read_file(ROOT/types.RUNTIME), read_file(ROOT/types.CLOCK)
            derived_runtime, derived_clock, record = types.compose(selected, runtime, clock)
            self.assertEqual(record['providerLayout'], types.INLINE_LAYOUT)
            self.assertEqual(record['qualification'], 'unknown')
            self.assertEqual(record['authority'], 'none')
            self.assertIs(record['runtimeApiChange'], False)
            self.assertIn(b'typeof import("node:perf_hooks").performance', derived_clock)
            # The conventional prepared layout gives TSC real native resolution,
            # without a custom package path or an ambient fake declaration.
            project = work/'dependencies/npm'
            source = project/'src';generated = project/'generated'
            source.mkdir();generated.mkdir()
            (source/'main.ts').write_text("""import { SmartBuffer } from 'smart-buffer';
const initial = SmartBuffer.fromSize(2).writeUInt16BE(0x1234);
export async function run(): Promise<string> {
  const value = await new Promise<number>(resolve => setTimeout(() => resolve(initial.readUInt16BE()), 1));
  const grown = SmartBuffer.fromSize(2).writeUInt16BE(value).writeUInt8(0x56).insertUInt8(0xab, 1);
  const shared = grown.toBuffer(); shared[1] = 0xcd;
  const text = SmartBuffer.fromSize(2).writeStringNT('A\\u00e9').readStringNT();
  const copied: Buffer = Buffer.from(shared);
  return copied.toString('hex') + ':' + text;
}
""", encoding='utf-8')
            (generated/'activation-runtime-globals.d.ts').write_bytes(derived_runtime)
            (generated/'clock-runtime-globals.d.ts').write_bytes(derived_clock)
            for origin, name in ((buffer_profile.DECLARATION,'buffer-runtime.d.ts'),
                                 (net_profile.DECLARATION,'net-runtime.d.ts')):
                (generated/name).write_bytes(read_file(ROOT/origin))
            # Match the normal compiler's fixed aliases and strict/noEmit options.
            config = {'compilerOptions':{'target':'ES2022','module':'ESNext','moduleResolution':'Bundler',
                'strict':True,'noEmit':True,'lib':['ES2022'],'types':[],
                'paths':{'buffer':['./generated/buffer-runtime.d.ts'],
                    'node:buffer':['./generated/buffer-runtime.d.ts'],
                    'net':['./generated/net-runtime.d.ts'],'node:net':['./generated/net-runtime.d.ts']}},
                'include':['src/**/*.ts','generated/**/*.d.ts']}
            (project/'tsconfig.json').write_text(json.dumps(config,indent=2)+'\n')
            result = subprocess.run([node,frontend/'node_modules/typescript/bin/tsc',
                '--project',project/'tsconfig.json'],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            closure.check_unchanged()

            # Compare actual prior helper outputs, not a handwritten model.
            baseline = root/'original_helper.py'
            baseline.write_bytes(subprocess.check_output(['git','--no-lazy-fetch','show',
                BASELINE+':tools/typescript_guest/standard_global_types.py'],cwd=ROOT))
            spec = importlib.util.spec_from_file_location('original_standard_global_types',baseline)
            prior = importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
            classic = StandardGlobalTypes();classic.original = npm_archive_files(
                read_file(ROOT/'tools/tests/fixtures/npm-types-node-26.6.5.tgz'))
            classic_root = root/'classic';classic_root.mkdir()
            _owner, classic_closure = classic.captured(classic_root)
            old_selected = prior.select(classic_closure)
            self.assertEqual(types.select(classic_closure),old_selected)
            self.assertEqual(types.compose(old_selected,runtime,clock),prior.compose(old_selected,runtime,clock))
            self.assertEqual(types.compose(None,runtime,clock),prior.compose(None,runtime,clock))

            # Real default declarations still accept the owned encoding union,
            # and actual TSC rejects a value outside it, without Node globals.
            plain = root/'plain';(plain/'src').mkdir(parents=True);(plain/'generated').mkdir()
            for name in ('buffer-runtime.d.ts','net-runtime.d.ts'):
                (plain/'generated'/name).write_bytes(read_file(generated/name))
            (plain/'tsconfig.json').write_text(json.dumps(config,indent=2)+'\n')
            default_source = "import { Socket } from 'node:net';\ndeclare const socket: Socket;\nsocket.write('x', 'base64url');socket.end('x', 'utf8');\n"
            (plain/'src/main.ts').write_text(default_source)
            command = [node,frontend/'node_modules/typescript/bin/tsc','--project',plain/'tsconfig.json']
            default = subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(default.returncode,0,default.stdout+default.stderr)
            (plain/'src/main.ts').write_text(default_source.replace("'base64url'", "'not-an-encoding'"))
            rejected = subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('not-an-encoding',rejected.stdout)

            # Negative parser fixtures need only the original layout inputs;
            # the positive TSC above uses the complete native captured graph.
            negative = StandardGlobalTypes()
            negative.original = {name:original_files[name] for name in types.INLINE_FILES}
            alterations = (
                ('mixed',lambda files:files.update({
                    types.PROVIDER+'web-globals/performance.d.ts':classic.original['web-globals/performance.d.ts'],
                    types.PROVIDER+'index.d.ts':files[types.PROVIDER+'index.d.ts']+
                        b'\n/// <reference path="web-globals/performance.d.ts" />\n'})),
                ('missing',lambda files:files.pop(types.PROVIDER+'perf_hooks.d.ts')),
                ('unknown',lambda files:files.update({types.PROVIDER+'perf_hooks.d.ts':
                    files[types.PROVIDER+'perf_hooks.d.ts'].replace(b'typeof _performance',b'string')})),
                ('alias',lambda files:files.update({types.PROVIDER+'perf_hooks.d.ts':
                    files[types.PROVIDER+'perf_hooks.d.ts'].replace(b'performance as _performance',b'other as _performance')})),
            )
            for label,alter in alterations:
                case_root = root/label;case_root.mkdir()
                _owner, bad = negative.captured(case_root,alter)
                with self.subTest(shape=label),self.assertRaisesRegex(ValueError,
                        'mixed-performance-layout|ambiguous-or-incomplete-provider|unreviewed-inline-performance'):
                    types.select(bad)


if __name__ == '__main__':
    unittest.main()

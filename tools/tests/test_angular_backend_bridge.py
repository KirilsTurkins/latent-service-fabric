"""Exercise the shipped private engine ordering without granting a host import."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.build_process import run_bounded

ROOT = Path(__file__).resolve().parents[2]


class AngularBackendBridgeTests(unittest.TestCase):
    def test_production_bridge_permits_one_prepare_and_render_or_one_pure_render(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('the renderer gate provisions Node for executable bridge checks')
        scenarios = {
            'pure': "const result=JSON.parse(await engine.render(frame)); assert.equal(result.backend,null); await denied();",
            'backend': "assert.deepEqual(JSON.parse(await engine.prepare(frame)),{url:'https://provider.invalid/data'}); await assert.rejects(engine.prepare(frame),/renderer-prepare-order/); const result=JSON.parse(await engine.render(withBackend)); assert.deepEqual(result.backend,backend); await denied();",
            'null': "const empty=JSON.stringify({...input,request:{path:'/public'}}); assert.equal(JSON.parse(await engine.prepare(empty)),null); assert.equal(JSON.parse(await engine.render(empty)).backend,null); await denied();",
            'bad-prepare': "await assert.rejects(engine.prepare('{}'),/renderer-adapter-contract/); await assert.rejects(engine.prepare(frame),/renderer-prepare-order/);",
            'bad-render': "await assert.rejects(engine.render('{}'),/renderer-adapter-contract/); await denied();",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"type":"module"}')
            for name in ('bridge.js', 'timers.js'):
                (root / name).write_bytes((ROOT / 'tools/angular-renderer-adapter/runtime' / name).read_bytes())
            (root / 'application.js').write_bytes((ROOT / 'tools/angular_build/application.js').read_bytes())
            (root / 'assets.js').write_text('export const clientAsset="/client.immutable.js";')
            (root / 'server.js').write_text('''
export async function prepare(request,context){return request.path==='/public'?null:{url:'https://provider.invalid/data'}}
export async function render(request,context,backend){return {html:'<h1>bounded</h1>',status:200,headers:[],backend}}
''')
            prefix = '''
import assert from 'node:assert/strict';
import {engine} from './bridge.js';
const input={formatVersion:1,request:{path:'/data'},context:{principal:{subject:'Alice'}}};
const backend={outcome:'response',status:200,body:'scoped response'};
const frame=JSON.stringify(input),withBackend=JSON.stringify({...input,backend});
async function denied(){await assert.rejects(engine.render(frame),/renderer-store-reuse-denied/);await assert.rejects(engine.prepare(frame),/renderer-prepare-order/)}
'''
            for name, scenario in scenarios.items():
                with self.subTest(scenario=name):
                    script = root / (name + '.mjs')
                    script.write_text(prefix + scenario + '\nprocess.stdout.write("bounded-engine-passed");\n')
                    result = run_bounded([node, str(script)], root, dict(os.environ), 30, 8192)
                    self.assertEqual(result.stdout, b'bounded-engine-passed')


if __name__ == '__main__':
    unittest.main()

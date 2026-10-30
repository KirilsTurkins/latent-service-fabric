"""Closed published fixture and retention; strict TSC never executes packages."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools import typescript_published_delay_fixture as fixture
from tools import qualify_typescript_published_delay as owner
from tools.application_dependencies import prepare
from tools.rust_capsule_project import ROOT, read_file, read_json, snapshot
from tools.typescript_guest import buffer_profile, net_profile, standard_global_types as types


class PublishedDelayControls(unittest.TestCase):
    def captured(self):
        value = os.environ.get('LSF_PUBLISHED_DELAY_CAPTURE')
        if not value:
            self.skipTest('explicit normal published delay capture required; owning programme refuses skips')
        app = Path(value).resolve(strict=True)
        fixture.provenance(app)
        return app

    def test_exact_published_fixture_and_actual_strict_types(self):
        from tools.tests.test_typescript_buffer_globals import BufferGlobalControls
        node,frontend = BufferGlobalControls().tools()
        app = self.captured()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);work=root/'work';out=root/'output';work.mkdir();out.mkdir()
            closure = prepare(app,work,out,'typescript')
            runtime,clock,_record = types.compose(types.select(closure),
                read_file(ROOT/types.RUNTIME),read_file(ROOT/types.CLOCK))
            project = work/'dependencies/npm';source=project/'src';generated=project/'generated'
            source.mkdir();generated.mkdir()
            for name in fixture.SOURCES:(source/name).write_bytes(read_file(app/'src'/name))
            for name,raw in (('activation-runtime-globals.d.ts',runtime),('clock-runtime-globals.d.ts',clock),
                    ('buffer-runtime.d.ts',read_file(ROOT/buffer_profile.DECLARATION)),
                    ('net-runtime.d.ts',read_file(ROOT/net_profile.DECLARATION))):
                (generated/name).write_bytes(raw)
            config={'compilerOptions':{'target':'ES2022','module':'ESNext','moduleResolution':'Bundler',
                'strict':True,'noEmit':True,'lib':['ES2022'],'types':[],
                'paths':{'buffer':['./generated/buffer-runtime.d.ts'],'node:buffer':['./generated/buffer-runtime.d.ts'],
                    'net':['./generated/net-runtime.d.ts'],'node:net':['./generated/net-runtime.d.ts']}},
                'include':['src/**/*.ts','generated/**/*.d.ts']}
            (project/'tsconfig.json').write_text(json.dumps(config,indent=2)+'\n')
            result=subprocess.run([node,frontend/'node_modules/typescript/bin/tsc',
                '--project',project/'tsconfig.json'],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            closure.check_unchanged()
            # Real closed project validation, without altering captured inputs.
            probe=fixture.project(root/'probe')
            original=read_file(probe/'src/main.ts')
            (probe/'src/main.ts').write_bytes(original+b'\nexport const changed=true;')
            with self.assertRaisesRegex(RuntimeError,'probe-drift'):fixture.verify_probe(snapshot(probe))
            (probe/'src/main.ts').write_bytes(original)
            changed=read_json(probe/'capsule-project.json');changed['limits']['cpuFuel']+=1
            (probe/'capsule-project.json').write_text(json.dumps(changed)+'\n')
            with self.assertRaisesRegex(RuntimeError,'closed-project'):fixture.verify_probe(snapshot(probe))

    def test_original_graph_bindings_and_public_only_collector(self):
        app=self.captured()
        native,graph=read_json(app/'package-lock.json'),read_json(app/'npm-resolved.lock.json')
        fixture.validate_graph(native,graph)
        changed=copy.deepcopy(native);changed['packages']['node_modules/unlimited-timeout']['version']='0.0.0'
        with self.assertRaisesRegex(RuntimeError,'version-integrity'):fixture.validate_graph(changed,graph)
        changed=copy.deepcopy(graph)
        node=next(row for row in changed['nodes'] if row['location']=='node_modules/delay')
        node['dependencies'][0]['specification']='*'
        with self.assertRaisesRegex(RuntimeError,'original-edges'):fixture.validate_graph(native,changed)
        changed=copy.deepcopy(graph)
        next(row for row in changed['nodes'] if row['location']=='node_modules/delay')['integrity']='sha512-changed'
        with self.assertRaisesRegex(RuntimeError,'version-integrity'):fixture.validate_graph(native,changed)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);artifact=root/'unsigned';artifact.mkdir();logs=artifact/'logs';logs.mkdir()
            raw=b'original compiler diagnostic\xff\x00';(logs/'00-typecheck.stderr.txt').write_bytes(raw)
            (artifact/'BUILD-FAILED.json').write_text('{"stage":"typecheck"}')
            private=artifact/'signed';private.mkdir();(private/'private-key.pem').write_bytes(b'not-public')
            public=owner.Public(root/'public');owner.collect_build(artifact,public)
            rows=read_json(public.root/'BUILD-LOGS.json')
            self.assertEqual(base64.b64decode(rows[0]['base64']),raw)
            self.assertFalse((public.root/'signed').exists())
            with self.assertRaisesRegex(RuntimeError,'public-file'):
                public.put('signed/private-key.pem',b'not-public')
            public.finish()
            self.assertEqual(set(read_json(public.root/'PUBLIC-MANIFEST.json')),
                {'BUILD-LOGS.json','BUILD-FAILED.json'})


if __name__=='__main__':unittest.main()

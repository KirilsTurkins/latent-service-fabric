"""Closed fixture, public retention and owner deadlines; no guest execution."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import typescript_buffer_globals_fixture as fixture
from tools import qualify_typescript_buffer_globals as owner
from tools.rust_capsule_project import ROOT, read_json, write_json


class GlobalBufferQualificationControls(unittest.TestCase):
    def test_normal_project_exact_sources_limits_and_actual_strict_types(self):
        from tools.tests.test_typescript_buffer_globals import BufferGlobalControls
        node, tools = BufferGlobalControls().tools()
        with tempfile.TemporaryDirectory() as temporary:
            app=fixture.project(Path(temporary)/'application')
            files=fixture.verify(app)
            self.assertEqual({name:files['src/'+name] for name in fixture.SOURCES},
                {name:(ROOT/fixture.FIXTURE/name).read_bytes() for name in fixture.SOURCES})
            config=read_json(app/'capsule-project.json')
            self.assertEqual(config['limits'],fixture.LIMITS)
            generated=app/'generated';generated.mkdir()
            for source,destination in (
                ('sdk/typescript-guest/runtime/buffer.d.ts','buffer-runtime.d.ts'),
                ('sdk/typescript-guest/runtime/buffer-globals.d.ts','buffer-runtime-globals.d.ts'),
                ('sdk/typescript-guest/activation/runtime-globals.d.ts','runtime-globals.d.ts')):
                (generated/destination).write_bytes((ROOT/source).read_bytes())
            write_json(app/'tsconfig.json',{'compilerOptions':{'target':'ES2022','module':'ESNext',
                'moduleResolution':'Bundler','strict':True,'noEmit':True,'lib':['ES2022'],'types':[],
                'paths':{'buffer':['./generated/buffer-runtime.d.ts'],'node:buffer':['./generated/buffer-runtime.d.ts']}},
                'include':['src/**/*.ts','generated/*.d.ts']})
            result=subprocess.run([node,tools/'node_modules/typescript/bin/tsc','--project',app/'tsconfig.json'],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            # Remove test-only generated files before normal capture verification.
            for path in generated.iterdir():path.unlink()
            generated.rmdir();(app/'tsconfig.json').unlink()
            original=(app/'src/main.ts').read_bytes()
            (app/'src/main.ts').write_bytes(original+b'\nexport const foreign=true;')
            with self.assertRaisesRegex(ValueError,'probe-drift'):fixture.verify(app)
            (app/'src/main.ts').write_bytes(original)
            config['limits']['cpuFuel']=config['limits']['cpuFuel']+1
            (app/'capsule-project.json').write_bytes((json.dumps(config,indent=2)+'\n').encode())
            with self.assertRaisesRegex(ValueError,'closed-project'):fixture.verify(app)

    def test_public_collector_retains_unsigned_logs_and_refuses_private_or_unknown_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);artifact=root/'build';artifact.mkdir()
            logs=artifact/'logs';logs.mkdir()
            raw=b'original compiler diagnostic\xff\x00'
            (logs/'00-typecheck.stderr.txt').write_bytes(raw)
            (artifact/'BUILD-FAILED.json').write_text('{"stage":"typecheck"}')
            private=artifact/'signed';private.mkdir();(private/'private-key.pem').write_bytes(b'never-public')
            public=owner.Public(root/'public')
            owner.collect_build(artifact,public)
            retained=read_json(public.root/'BUILD-LOGS.json')
            self.assertEqual(base64.b64decode(retained[0]['base64']),raw)
            self.assertFalse((public.root/'signed').exists())
            self.assertFalse(any(b'never-public' in path.read_bytes() for path in public.root.iterdir()))
            with self.assertRaisesRegex(RuntimeError,'public-file'):
                public.put('signed/private-key.pem',b'not copied')
            public.finish()
            manifest=read_json(public.root/'PUBLIC-MANIFEST.json')
            self.assertEqual(set(manifest),{'BUILD-LOGS.json','BUILD-FAILED.json'})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);public=owner.Public(root/'public')
            (public.root/'unexpected.pem').write_bytes(b'not copied')
            with self.assertRaisesRegex(RuntimeError,'unexpected-public-file'):public.finish()

    def test_aggregate_clock_deducts_setup_and_clips_original_process_bounds(self):
        # Same validator used by the owner, over the normal CLI's public schema.
        revision={'revisionId':'revision','releaseDigest':'release','publicationId':'publication',
            'routeGeneration':'1'}
        seen=set()
        for index in range(4):
            row={'response':{'data':{'activationId':'actual-'+str(index),'resolvedRevision':dict(revision)}}}
            owner.invocation_identity(row,'actual-'+str(index),revision,seen)
        self.assertEqual(len(seen),4)
        with self.assertRaisesRegex(RuntimeError,'distinct-activation'):
            owner.invocation_identity(row,'actual-3',revision,seen)
        for field in ('activationId','resolvedRevision'):
            forged={'activationId':'next','resolvedRevision':dict(revision)}
            forged[field]='other' if field=='activationId' else dict(revision,routeGeneration='2')
            with self.assertRaisesRegex(RuntimeError,'actual-'):
                owner.invocation_identity({'response':{'data':forged}},'next',revision,seen)
        numeric={'activationId':'next','resolvedRevision':dict(revision,routeGeneration=1)}
        with self.assertRaisesRegex(RuntimeError,'published-revision'):
            owner.invocation_identity({'response':{'data':numeric}},'next',revision,seen)
        self.assertEqual(len(seen),4)
        with mock.patch.dict(os.environ,{'LSF_BUFFER_GLOBAL_STARTED_NS':'1000000000000'}), \
                mock.patch.object(owner.time,'time_ns',return_value=1010000000000), \
                mock.patch.object(owner.time,'monotonic',return_value=50):
            deadline=owner.Deadline()
            self.assertEqual(deadline.end,1240)
            self.assertEqual(deadline.remaining(30),30)
            with mock.patch.object(owner.time,'monotonic',return_value=1235):
                with self.assertRaisesRegex(RuntimeError,'aggregate-deadline'):deadline.remaining(60)
            with mock.patch.object(owner.time,'monotonic',return_value=1240):
                with self.assertRaisesRegex(RuntimeError,'final-deadline'):deadline.check()
        with mock.patch.dict(os.environ,{'LSF_BUFFER_GLOBAL_STARTED_NS':'1'}):
            with self.assertRaisesRegex(RuntimeError,'aggregate-setup'):owner.Deadline()

"""Pinned failed-outer ancestry, exact reader delta and two-owner public assets."""
import copy
import json
import unittest
from unittest.mock import patch

from tools import replay_rust_wasi_http_async_runtime as replay
from tools.rust_capsule_project import ROOT,digest
from tools.phase2_operator_process import WorkflowError


class RustHttpAsyncRuntimeReplay(unittest.TestCase):
    def test_reused_backend_requires_actual_success_of_only_the_exact_original_step(self):
        from tools import rust_wasi_http_current_backend as backend
        name='Compile exactly one current source-bound standard backend'
        step={'name':name,'number':12,'status':'completed','conclusion':'success'}
        self.assertEqual(backend.backend_step({'steps':[step]}),name)
        for key,value in (('name','Compile another backend'),('number',True),('number',11),
                ('status','in_progress'),('conclusion','failure'),('conclusion','skipped')):
            with self.subTest(key=key,value=value),self.assertRaises(WorkflowError):
                backend.backend_step({'steps':[{**step,key:value}]})
        for steps in ([],[step,step]):
            with self.subTest(steps=steps),self.assertRaises(WorkflowError):
                backend.backend_step({'steps':steps})

    def test_only_exact_failed_original_origin_is_accepted(self):
        pins=json.loads((ROOT/replay.PINS).read_bytes())
        branch='fix/rust-http-explicit-async-entry-20261021'
        run={'id':replay.RUN,'head_sha':replay.SOURCE,'head_branch':branch,'event':'push',
            'path':'.github/workflows/rust-wasi-http-clients.yml','status':'completed','conclusion':'failure'}
        job={'id':replay.JOB,'run_id':replay.RUN,'head_sha':replay.SOURCE,'status':'completed','conclusion':'failure'}
        artifact={**pins['artifact'],'expired':False,'name':'rust-wasi-http-runtime-'+replay.SOURCE,
            'workflow_run':{'id':replay.RUN,'head_sha':replay.SOURCE,'head_branch':branch,
                'repository_id':1337591365,'head_repository_id':1337591365}}
        replay.validate_origin(run,job,artifact,pins)
        for which,key,value in (('run','conclusion','success'),('run','event','workflow_dispatch'),
                ('job','head_sha','0'*40),('artifact','expired',True),
                ('artifact','digest','sha256:'+'0'*64)):
            values=copy.deepcopy({'run':run,'job':job,'artifact':artifact})
            values[which][key]=value
            with self.subTest(which=which,key=key),self.assertRaises(WorkflowError):
                replay.validate_origin(**values,pins=pins)

    def test_exact_one_reader_pair_never_allows_an_unknown_compiler_or_helper_change(self):
        sources={replay.NODE_PATH:b'original node source','Cargo.toml':b'original Cargo source'}
        previous={replay.NODE_PATH:{'sha256':digest(sources[replay.NODE_PATH]),'bytes':len(sources[replay.NODE_PATH])}}
        recipe={'Cargo.toml':{'digest':digest(sources['Cargo.toml']),'size':len(sources['Cargo.toml'])}}
        current={name:{'sha256':digest(body),'bytes':len(body)} for name,body in sources.items()}
        current[replay.NODE_PATH]=replay.CURRENT_NODE
        def observe(path):return current[path.relative_to(ROOT).as_posix()]
        with patch.object(replay,'git_files',return_value=sources),patch.object(replay,'file_identity',side_effect=observe):
            result=replay.source_binding(previous,recipe)
            self.assertFalse(result['currentGuestCompilationClaimed'])
            self.assertEqual(len(result['currentReaderDelta']),1)
            for name in sources:
                saved=current[name];current[name]={'sha256':'sha256:'+'0'*64,'bytes':1}
                with self.subTest(name=name),self.assertRaises(WorkflowError):replay.source_binding(previous,recipe)
                current[name]=saved
            current[replay.NODE_PATH]=previous[replay.NODE_PATH]
            with self.assertRaisesRegex(WorkflowError,'required-reader-correction'):
                replay.source_binding(previous,recipe)

    def test_restored_public_bytes_must_match_both_original_source_and_original_packaging(self):
        raw=b'original public WIT\n';identity={'digest':digest(raw),'size':len(raw)}
        self.assertEqual(replay.public_wit_identity(raw,identity,identity),identity)
        changed={'digest':digest(raw+b'changed'),'size':len(raw+b'changed')}
        for body,source,package in ((raw+b'changed',identity,identity),(raw,changed,identity),
                (raw,identity,changed),(raw,changed,changed)):
            with self.subTest(source=source,package=package),self.assertRaises(WorkflowError):
                replay.public_wit_identity(body,source,package)


if __name__=='__main__':unittest.main()

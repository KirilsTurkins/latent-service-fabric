"""Finite source/data controls; never execute or qualify a C guest locally."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import c_thread_prefix_inputs as inputs, c_thread_runtime_fixture as fixture
from tools import diagnose_c_thread_prefix as diagnostic
from tools.c_guest import threading
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, write_json


class CThreadPrefixControls(unittest.TestCase):
    def test_only_original_failed_owning_origin_and_exact_public_archive_are_accepted(self):
        run = {'id': inputs.RUN, 'head_sha': inputs.SOURCE,
            'head_branch': 'feat/c-thread-runtime-consumer-20261021', 'event': 'push',
            'path': '.github/workflows/c-thread-runtime.yml', 'status': 'completed', 'conclusion': 'failure',
            'repository': {'id': 1337591365}, 'head_repository': {'id': 1337591365}}
        job = {'id': inputs.JOB, 'run_id': inputs.RUN, 'head_sha': inputs.SOURCE,
            'status': 'completed', 'conclusion': 'failure', 'steps': [{'name':
                'Compile one ordinary C project and execute all seventeen original cases', 'conclusion': 'failure'}]}
        artifact = {**inputs.ARTIFACT, 'expired': False, 'workflow_run': {'id': inputs.RUN, 'head_sha': inputs.SOURCE},
            'name': 'c-thread-runtime-'+inputs.SOURCE}
        inputs.origin(run, job, artifact)
        for field in ('source', 'branch', 'event', 'workflow', 'success-relabel', 'job-source', 'job-stage', 'digest', 'size', 'expired'):
            r,j,a = copy.deepcopy(run),copy.deepcopy(job),copy.deepcopy(artifact)
            if field == 'source': r['head_sha'] = '0'*40
            elif field == 'branch': r['head_branch'] = 'other'
            elif field == 'event': r['event'] = 'workflow_dispatch'
            elif field == 'workflow': r['path'] = '.github/workflows/other.yml'
            elif field == 'success-relabel': r['conclusion'] = 'success'
            elif field == 'job-source': j['head_sha'] = '0'*40
            elif field == 'job-stage': j['steps'][0]['name'] = 'different failure'
            elif field == 'digest': a['digest'] = 'sha256:'+'0'*64
            elif field == 'size': a['size_in_bytes'] += 1
            else: a['expired'] = True
            with self.subTest(field=field), self.assertRaises(WorkflowError): inputs.origin(r,j,a)

    def test_normal_source_only_wit_stage_matches_all_three_actual_package_preimages(self):
        expected = {'wit/world.wit': {'digest': 'sha256:e82cd4f7797818028f8996e257a0d76504be1248e73b883ada86dd6db5acecdc', 'size': 242},
            'wit/deps/activation-runtime/package.wit': {'digest': 'sha256:0855e3524edbe15a5d174a825df6034ef41cd87f1330e2fba884ea6e2c58e946', 'size': 2539},
            'wit/deps/native-runtime/package.wit': {'digest': 'sha256:2433ec06c033be01474fd5bf3275c921622eb6720aac344f1307736d09325eb6', 'size': 633}}
        original = Path.write_text
        def unix_text(path,data,encoding=None,errors=None,newline=None):
            return original(path,data,encoding=encoding,errors=errors,newline='\n')
        with tempfile.TemporaryDirectory() as temp, patch.object(Path,'write_text',unix_text):
            app = fixture.prepare(Path(temp)/'app')
            self.assertEqual(inputs.digest((app/'wit/world.wit').read_bytes()),
                'sha256:3d5b485dba2509a66cd9cc419afe64315348e2a0ca097faa0aa0fac45c9ec5ef')
            staged = threading.stage(app/'wit',fixture.WORLD,Path(temp)/'staged',app/'vendor/lsf/wit/platform')
            for name,wanted in expected.items():
                raw = (staged/name.removeprefix('wit/')).read_bytes()
                inputs.public_wit(raw,wanted)
                for bad in (raw+b'\n', raw.replace(b'async func', b'func'), raw.replace(b'@0.1.0',b'@0.2.0')):
                    if bad == raw: continue
                    with self.subTest(path=name), self.assertRaises(WorkflowError): inputs.public_wit(bad,wanted)

    def test_actual_failed_call_is_retained_with_audit_and_retirement_before_revision_refusal(self):
        actual = json.loads((ROOT/'tools/tests/fixtures/c-thread-d928-first-pthread.json').read_bytes())
        self.assertEqual(actual['response']['error']['code'],'guest-trap')
        self.assertEqual(actual['response']['data']['consumption']['cpuFuel'],'78482')
        target = {'budget':{'cpuFuel':1_000_000_000,'memoryBytes':32*1024*1024}}
        revision = actual['response']['data']['resolvedRevision']
        process = SimpleNamespace(authoring_started_unix_millis=1792623412195,close=Mock())
        node = SimpleNamespace(drain=lambda:None,buffers=[bytearray(),bytearray()])
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            def audited(*args):
                self.assertTrue((out/'invocation-c-prefix-pthread.json').is_file())
                write_json(out/'audit-model.json',{'model':True});return [],None
            def retired(*args):
                self.assertTrue((out/'audit-model.json').is_file())
                write_json(out/'retirement-model.json',{'model':True});return {'model':True}
            with patch.object(diagnostic,'selected_revision',return_value=revision), \
                    patch.object(diagnostic,'start_call',return_value=process), \
                    patch.object(diagnostic.original,'finish_call',return_value=actual), \
                    patch.object(diagnostic,'audit',side_effect=audited), \
                    patch.object(diagnostic,'retirement',side_effect=retired):
                row = diagnostic.observe(None,node,None,target,out,'pthread')
                self.assertEqual(row['exitCode'],4);self.assertIs(row['qualification'],False)
                self.assertIs(row['instructionCauseClaimed'],False)
                out = Path(temp)/'foreign';out.mkdir()
                with patch.object(diagnostic,'selected_revision',return_value={'foreign':'revision'}), \
                        self.assertRaisesRegex(WorkflowError,'known-current-reaped'):
                    diagnostic.observe(None,node,None,target,out,'pthread')
                self.assertTrue((out/'invocation-c-prefix-pthread.json').is_file())
                self.assertTrue((out/'retirement-model.json').is_file())
        self.assertEqual(diagnostic.MODES,('application-error','c11','pthread'))


if __name__ == '__main__': unittest.main()

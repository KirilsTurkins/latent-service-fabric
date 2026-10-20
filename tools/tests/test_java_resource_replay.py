"""Historical product selection never invents a current normal qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from tools import replay_java_resources as replay
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, write_json
from tools.tests.test_sdk_scratch_qualification import ordinary


class JavaResourceReplay(unittest.TestCase):
    def test_origin_wrong_source_digest_expiry_and_nonfailure_refuse_before_fetch(self):
        artifact={'id':replay.ARTIFACT,'expired':False,'size_in_bytes':replay.BYTES,'digest':replay.DIGEST,
            'workflow_run':{'id':replay.RUN,'head_sha':replay.COMPILED}}
        job={'run_id':replay.RUN,'head_sha':replay.COMPILED,'status':'completed','conclusion':'failure'}
        for changed in ('expired','digest','source','conclusion'):
            a,j=copy.deepcopy(artifact),copy.deepcopy(job)
            if changed=='expired':a['expired']=True
            elif changed=='digest':a['digest']=digest(b'other')
            elif changed=='source':a['workflow_run']['head_sha']='0'*40
            else:j['conclusion']='success'
            with self.subTest(changed=changed),patch.object(replay.historical,'api',side_effect=[a,j]), \
                    patch.object(replay.subprocess,'check_output',side_effect=AssertionError('unapproved download')):
                with self.assertRaisesRegex(RuntimeError,'fixed-companion-origin'): replay.companions_archive()

    def test_archive_identity_refuses_any_unauthenticated_bytes(self):
        for raw in (b'',b'wrong',b'PK'+bytes(2048)):
            with self.subTest(length=len(raw)),self.assertRaisesRegex(RuntimeError,'ZIP-digest'):
                replay.decode_companions(raw)

    def test_reconstruction_requires_current_application_inventory_before_marker_or_signer_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            selected={'word-count/source-inputs.json':b'{}\n','word-count/component.wasm':b'original-component'}
            with self.assertRaisesRegex(RuntimeError,'original-companion-source-drift'):
                replay.restore_companion(root,'word-count',selected)

    def test_manual_fixed_branch_job_fetches_preimages_before_checks_and_never_builds_native(self):
        model=yaml.safe_load(read_file(ROOT/'.github/workflows/java-resource-replay.yml'))
        events=model.get('on',model.get(True))
        self.assertEqual(set(events),{'workflow_dispatch','push'})
        self.assertEqual(events['push']['branches'],['diagnostic/java-resource-conformance-20261020'])
        self.assertEqual(set(events['push']['paths']),{'.github/workflows/java-resource-replay.yml',
            'tools/replay_java_resources.py','tools/tests/test_java_resource_replay.py'})
        self.assertNotIn('pull_request',events)
        job=model['jobs']['replay']; self.assertEqual(job['timeout-minutes'],20)
        steps=job['steps']
        fetch=next(i for i,s in enumerate(steps) if replay.PRODUCTION in s.get('run',''))
        controls=next(i for i,s in enumerate(steps) if 'test_java_resource_replay' in s.get('run',''))
        self.assertLess(fetch,controls)
        commands='\n'.join(s.get('run','') for s in steps)
        self.assertNotIn('cargo ',commands)
        self.assertNotIn('qualify_java_capsules.py',commands)
        self.assertNotIn('dotnet ',commands)
        self.assertEqual(sum('tools/replay_java_resources.py' in s.get('run','') for s in steps),2)


if __name__=='__main__':unittest.main()

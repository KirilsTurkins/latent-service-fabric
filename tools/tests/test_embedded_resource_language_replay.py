"""Authenticated historical component ancestry remains separate from current source."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from tools import replay_embedded_resource_languages as replay
from tools.rust_capsule_project import ROOT, TEMPLATES, digest


class EmbeddedLanguageReplay(unittest.TestCase):
    def test_component_producer_requires_every_exact_published_identity(self):
        for language,spec in replay.SPECS.items():
            value = {'id':spec['artifact'],'name':spec['name'],'size_in_bytes':spec['archiveBytes'],
                'digest':spec['archiveDigest'],'expired':False,'workflow_run':{'id':spec['run'],
                    'head_sha':spec['head'],'repository_id':1337591365,'head_repository_id':1337591365}}
            with self.subTest(language=language):
                observed = replay.validate_artifact(language,value)
                self.assertFalse(observed['completeArchiveHashVerified'])
                for field in ('id','name','size_in_bytes','digest','expired','run','head_sha','repository_id','head_repository_id'):
                    changed = copy.deepcopy(value)
                    if field in {'run','head_sha','repository_id','head_repository_id'}:
                        key = 'id' if field == 'run' else field
                        changed['workflow_run'][key] = 'substituted'
                    else: changed[field] = True if field == 'expired' else 'substituted'
                    with self.subTest(field=field), self.assertRaisesRegex(RuntimeError,'pinned-component-producer'):
                        replay.validate_artifact(language,changed)

    def test_only_four_public_companions_and_fixed_normal_records_are_selected(self):
        for language,spec in replay.SPECS.items():
            prefix = spec['prefix']
            for name in ('qualification.json','source-inputs.json','node/workflow.json',
                    'builds/word-count/component.wasm','builds/shipping/wit/latent/word/package.wit',
                    'builds/http-status/typescript-entropy-selection.json'):
                self.assertTrue(replay.selected(language,prefix+name))
            for name in ('native-binaries/latentd','builds/greeting/component.wasm','private-key.pem',
                    'builds/recovery/source/private.ts','builds/http-status/../component.wasm',
                    'builds/recovery/wit/../../secret.wit','builds/recovery/wit/package.wit:stream'):
                self.assertFalse(replay.selected(language,prefix+name))
            for name in ('/'+prefix+'qualification.json',prefix+'builds\\shipping\\component.wasm'):
                self.assertFalse(replay.selected(language,name))
        self.assertFalse(replay.selected('typescript','builds/recovery/component.wasm'))

    def fixture(self, directory, language):
        spec = copy.deepcopy(replay.SPECS[language])
        source = b'{"historical":"unaltered"}\n'
        node = {'status':'passed','language':language,'invocations':[
            {'activation':'original-'+str(index),'processReaped':True,'response':{'outcomeKnown':True}}
            for index in range(spec['normalCalls'])], 'samples':[{}]*spec['physical'],
            'providerIdle':[{}]*spec['idle'],'nodeShutdown':{'reaped':True,'record':{'clean':True}}}
        q = {'status':'passed','schemaVersion':'latent.'+language+'-capsule.qualification.v1',
            'sourceIdentityDigest':digest(source),'node':{},'builds':{}}
        if language == 'typescript':
            q['applicationDependencies'] = {'developerOwned':'outside-qualification-module/1.0.0',
                'offlineOriginals':'unavailable-after-capture'}
        raw = (json.dumps(node)+'\n').encode()
        q['node']['receiptDigest'] = digest(raw)
        (directory/'node').mkdir(); (directory/'node/workflow.json').write_bytes(raw)
        (directory/'source-inputs.json').write_bytes(source)
        for name in TEMPLATES:
            if name == 'greeting': continue
            build = directory/'builds'/name; build.mkdir(parents=True)
            marker = {'componentDigest':'sha256:'+('1'*64),'template':name}
            (build/'BUILD-COMPLETE.json').write_bytes(json.dumps(marker).encode())
            q['builds'][name] = marker
        qraw = (json.dumps(q)+'\n').encode(); (directory/'qualification.json').write_bytes(qraw)
        spec.update(qualification=digest(qraw),source=digest(source),node=digest(raw))
        return spec,node,q

    def test_pinned_normal_receipt_binds_original_names_counts_and_all_four_markers(self):
        for language in replay.SPECS:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); spec,_,_ = self.fixture(directory,language)
                with patch.dict(replay.SPECS,{language:spec}), patch.object(replay,'package_identity',return_value={'exact':'layers'}) as packages:
                    companions,proof = replay.historical(language,directory)
                self.assertEqual(set(companions),set(TEMPLATES)-{'greeting'})
                self.assertEqual(packages.call_count,4)
                self.assertEqual(len(proof['normalActivations']),spec['normalCalls'])
                self.assertEqual(proof['physicalSamples'],spec['physical'])
                self.assertEqual(proof['idleSamples'],spec['idle'])
                self.assertFalse(proof['currentNormalReceiptFabricated'])

    def test_rehashed_duplicate_or_wrong_normal_counts_and_changed_marker_are_refused(self):
        for mode in ('names','count','physical','idle','unknown','marker','source','dependencies'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); spec,node,q = self.fixture(directory,'typescript')
                if mode == 'marker':
                    (directory/'builds/recovery/BUILD-COMPLETE.json').write_bytes(b'{"substituted":true}')
                elif mode == 'source': (directory/'source-inputs.json').write_bytes(b'changed')
                elif mode == 'dependencies':
                    q['applicationDependencies']['offlineOriginals'] = 'still-available'
                    raw = json.dumps(q).encode(); (directory/'qualification.json').write_bytes(raw)
                    spec['qualification'] = digest(raw)
                else:
                    if mode == 'names': node['invocations'][1]['activation'] = node['invocations'][0]['activation']
                    elif mode == 'count': node['invocations'].pop()
                    elif mode == 'physical': node['samples'].pop()
                    elif mode == 'idle': node['providerIdle'].pop()
                    else: node['invocations'][0]['response']['outcomeKnown'] = False
                    raw = json.dumps(node).encode(); (directory/'node/workflow.json').write_bytes(raw)
                    spec['node'] = q['node']['receiptDigest'] = digest(raw)
                    raw = json.dumps(q).encode(); (directory/'qualification.json').write_bytes(raw)
                    spec['qualification'] = digest(raw)
                with patch.dict(replay.SPECS,{'typescript':spec}), patch.object(replay,'package_identity'), \
                        self.assertRaisesRegex(RuntimeError,'embedded-replay-original-'):
                    replay.historical('typescript',directory)

    def test_separate_twenty_minute_manual_matrix_keeps_all_existing_jobs_untouched(self):
        workflow = yaml.safe_load((ROOT/'.github/workflows/embedded-resource-languages-reference.yml').read_bytes())
        events = workflow.get('on',workflow.get(True))
        self.assertIsNone(events['workflow_dispatch'])
        self.assertEqual(events['push']['branches'],['diagnostic/rust-typescript-embedded-resources-20261020'])
        self.assertEqual(set(events),{'push','workflow_dispatch'})
        self.assertEqual(workflow['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(set(workflow['jobs']),{'resources'})
        job = workflow['jobs']['resources']; self.assertEqual(job['timeout-minutes'],20)
        self.assertEqual(job['strategy'],{'fail-fast':False,'matrix':{'language':['rust','typescript']}})
        steps = job['steps']; commands = '\n'.join(row.get('run','') for row in steps)
        self.assertNotIn('-p latentd',commands)
        self.assertNotIn('qualify_rust_capsules.py',commands)
        self.assertNotIn('--prepare-engine',commands)
        self.assertIn('--record-producer',commands); self.assertIn('--acquire',commands)
        download = next(row for row in steps if row.get('uses','').startswith('actions/download-artifact@'))
        self.assertEqual(download['with']['run-id'],39373374237)
        self.assertEqual(download['with']['name'],'go-scratch-prepared-'+replay.native.producer.PRODUCER_HEAD)
        self.assertLess(next(index for index,row in enumerate(steps) if '--record-producer' in row.get('run','')),steps.index(download))


if __name__ == '__main__': unittest.main()

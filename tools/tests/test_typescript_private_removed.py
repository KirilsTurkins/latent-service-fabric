"""Finite input/origin/retirement controls; no guest execution claims."""
import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from tools import typescript_private_removed_inputs as inputs
from tools import qualify_typescript_private_removed as consumer
from tools.phase2_operator_process import WorkflowError


class PrivateRemovedInputs(unittest.TestCase):
    def test_transfer_limits_refuse_before_request_and_preserve_last_allowed_read(self):
        from contextlib import nullcontext
        from unittest.mock import patch
        reader=inputs.BoundedRanges('https://fixture.invalid/archive',inputs.MAX_TRANSFER+1)
        response=SimpleNamespace(status=206,headers={'Content-Range':f'bytes 0-0/{reader.size}'},read=lambda n:b'x')
        with patch.object(inputs.urllib.request,'urlopen',return_value=nullcontext(response)) as read:
            reader.requests=inputs.MAX_REQUESTS
            with self.assertRaises(WorkflowError):reader.read(1)
            read.assert_not_called()
            reader.requests=inputs.MAX_REQUESTS-1;reader.transferred=inputs.MAX_TRANSFER
            with self.assertRaises(WorkflowError):reader.read(1)
            read.assert_not_called()
            reader.transferred-=1
            self.assertEqual(reader.read(1),b'x')
            read.assert_called_once()

    def test_server_busy_retries_same_range_with_failed_attempts_still_charged(self):
        from contextlib import nullcontext
        from unittest.mock import patch
        reader=inputs.BoundedRanges('https://fixture.invalid/archive',3)
        busy=inputs.urllib.error.HTTPError(reader.url,503,'Egress is over the account limit.',{},None)
        response=SimpleNamespace(status=206,headers={'Content-Range':'bytes 0-2/3'},read=lambda n:b'abc')
        with patch.object(inputs.urllib.request,'urlopen',side_effect=[busy,busy,nullcontext(response)]) as read, \
                patch.object(inputs.time,'sleep') as sleep,patch.object(inputs.time,'monotonic',return_value=10):
            self.assertEqual(reader.read(3),b'abc')
            self.assertEqual([call.args[0].get_header('Range') for call in read.call_args_list],['bytes=0-2']*3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list],[2,8])
            self.assertEqual((reader.requests,reader.transferred,reader.position),(3,9,3))
        reader=inputs.BoundedRanges('https://fixture.invalid/archive',3)
        with patch.object(inputs.urllib.request,'urlopen',side_effect=busy) as read, \
                patch.object(inputs.time,'sleep') as sleep,patch.object(inputs.time,'monotonic',return_value=10):
            with self.assertRaises(inputs.urllib.error.HTTPError):reader.read(3)
            self.assertEqual(read.call_count,3)
            self.assertEqual((reader.requests,reader.transferred,reader.position),(3,9,0))

    def test_server_busy_retry_refuses_before_caps_or_original_deadline(self):
        from unittest.mock import patch
        for requests,transferred in [(inputs.MAX_REQUESTS-1,0),(0,inputs.MAX_TRANSFER-1)]:
            reader=inputs.BoundedRanges('https://fixture.invalid/archive',1)
            reader.requests=requests;reader.transferred=transferred
            busy=inputs.urllib.error.HTTPError(reader.url,503,'busy',{'x-ms-error-code':'ServerBusy'},None)
            with patch.object(inputs.urllib.request,'urlopen',side_effect=busy) as read, \
                    patch.object(inputs.time,'sleep') as sleep:
                with self.assertRaises(WorkflowError):reader.read(1)
                self.assertEqual(read.call_count,1);sleep.assert_not_called()
                self.assertEqual((reader.requests,reader.transferred,reader.position),(requests+1,transferred+1,0))
        reader=inputs.BoundedRanges('https://fixture.invalid/archive',1)
        with patch.object(inputs.urllib.request,'urlopen',side_effect=busy) as read, \
                patch.object(inputs.time,'sleep') as sleep,patch.object(inputs.time,'monotonic',side_effect=[0,0,29]):
            with self.assertRaises(WorkflowError):reader.read(1)
            self.assertEqual(read.call_count,1);sleep.assert_not_called()

    def test_forbidden_and_unclassified_service_unavailable_never_retry(self):
        from unittest.mock import patch
        for code in (403,503):
            reader=inputs.BoundedRanges('https://fixture.invalid/archive',1)
            error=inputs.urllib.error.HTTPError(reader.url,code,'unclassified',{},None)
            with patch.object(inputs.urllib.request,'urlopen',side_effect=error) as read, \
                    patch.object(inputs.time,'sleep') as sleep:
                with self.assertRaises(inputs.urllib.error.HTTPError):reader.read(1)
                self.assertEqual(read.call_count,1);sleep.assert_not_called()
                self.assertEqual((reader.requests,reader.transferred,reader.position),(1,1,0))

    def test_fixed_members_keep_cancelled_guest_and_separate_host_origins(self):
        value = inputs.fixture()
        self.assertEqual(len(value['members']),72)
        self.assertEqual(sum(r['bytes'] for r in value['members'].values()),63468397)
        self.assertTrue(all(name+'/deployment.json' in value['members'] for name in value['buildDirectories'].values()))
        self.assertFalse(value['wholeProducerQualified'])
        self.assertFalse(value['wholeArchiveDigestVerified'])
        self.assertNotEqual(inputs.SOURCE,consumer.native.SOURCE)
        self.assertEqual(consumer.native.READER.control_count,193)
        self.assertNotIn('npm-private-dependencies/node-2/workflow.json',value['members'])

    def test_original_static_layer_recovery_preserves_package_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);proof=inputs.reconstruct(root)
            name='npm-private-dependencies/build-2/wit/world.wit'
            self.assertEqual(inputs.file_identity(root/name),inputs.fixture()['reconstructed'][name]['identity'])
            self.assertEqual((root/name).stat().st_size,144)
            self.assertTrue(proof[name]['artifactMemberAbsent'])
            self.assertFalse(proof[name]['componentRebuilt'])
            with self.assertRaises(FileExistsError):inputs.reconstruct(root)

    def test_archive_preflight_rejects_duplicate_wrong_size_and_symlink(self):
        value=inputs.fixture()
        rows=[SimpleNamespace(filename=value['zipPrefix']+n,file_size=r['bytes'],compress_size=r['bytes'],flag_bits=0,
            external_attr=0,is_dir=lambda:False) for n,r in value['members'].items()]
        class Archive:
            def infolist(self):return rows
            def getinfo(self,name):return next(r for r in rows if r.filename==name)
        self.assertEqual(len(inputs.preflight(Archive())),72)
        rows.append(rows[0])
        with self.assertRaises(WorkflowError):inputs.preflight(Archive())
        rows.pop();rows[0].file_size+=1
        with self.assertRaises(WorkflowError):inputs.preflight(Archive())
        rows[0].file_size-=1;rows[0].compress_size+=65537
        with self.assertRaises(WorkflowError):inputs.preflight(Archive())
        rows[0].compress_size-=65537;rows[0].external_attr=0o120777<<16
        with self.assertRaises(WorkflowError):inputs.preflight(Archive())

    def test_origin_requires_original_cancelled_job_not_manufactured_success(self):
        f=inputs.fixture();artifact=dict(id=f['artifact']['id'],size_in_bytes=f['artifact']['bytes'],
            digest='sha256:'+f['artifact']['sha256'],expired=False,
            workflow_run=dict(id=f['run'],head_sha=inputs.SOURCE))
        job=dict(id=f['job'],run_id=f['run'],head_sha=inputs.SOURCE,head_branch='development',
            name='TypeScript guest value and ownership boundary',status='completed',conclusion='cancelled')
        run=dict(id=f['run'],head_sha=inputs.SOURCE,head_branch='development',event='push',
            path='.github/workflows/typescript-guest.yml',status='completed',conclusion='cancelled')
        inputs.origin(artifact,job,run)
        for field,value in [('conclusion','success'),('head_sha',consumer.native.SOURCE),('head_branch','release')]:
            changed={**job,field:value}
            with self.assertRaises(WorkflowError):inputs.origin(artifact,changed,run)

    def test_historical_nodes_require_original_host_and_clean_physical_retirement(self):
        snapshot={'runtime':{'original':'a8'}}
        qualification={'binaries':{'latent':{'old':'cli'},'latentd':{'old':'node'}}}
        capture=dict(status='passed',nonce=inputs.fixture()['nonce'],peerPhysicallyReaped=True,
            originalPackagesUnavailableBeforeBuild=True)
        nodes={}
        for label in ['0','0-rebuild','1']:
            nodes[label]=dict(status='passed',language='typescript',source=snapshot['runtime'],
                binaries={'cli':qualification['binaries']['latent'],'node':qualification['binaries']['latentd']},
                invocations=[{'processReaped':True} for _ in range(30)],
                capturedNpmPrivate=dict(status='passed',cases=[dict(actualSignedTarget=True,freshState=True) for _ in range(3)],
                    nonce=capture['nonce'],removed=False,version='1.1.0' if label=='1' else '1.0.0',
                    condition='default' if label=='1' else 'enabled'),
                nodeShutdown={'reaped':True,'record':{'clean':True}})
        actual=inputs.historical(nodes,capture,qualification,snapshot)
        self.assertTrue(all(not r['newHostExecutionClaimed'] and r['runtimeHostSource']==inputs.SOURCE for r in actual))
        for mutate in [lambda n:n['1'].update(source={'new':'host'}),
                lambda n:n['0']['nodeShutdown'].update(reaped=False),
                lambda n:n['0-rebuild']['capturedNpmPrivate'].update(nonce='changed')]:
            changed=copy.deepcopy(nodes);mutate(changed)
            with self.assertRaises(WorkflowError):inputs.historical(changed,capture,qualification,snapshot)

    def test_remaining_outcome_requires_removed_nonce_cases_and_real_shutdown(self):
        probe={key:inputs.fixture()[key] for key in ['nonce','version','removed','condition']}
        node=dict(status='passed',language='typescript',invocations=[dict(processReaped=True) for _ in range(30)],
            capturedNpmPrivate=dict(status='passed',cases=[dict(actualSignedTarget=True,freshState=True) for _ in range(3)],**probe),
            nodeShutdown={'reaped':True,'record':{'clean':True}})
        consumer.outcome(node,probe)
        for mutate in [lambda n:n['capturedNpmPrivate'].update(removed=False),
                lambda n:n['capturedNpmPrivate'].update(nonce='changed'),
                lambda n:n['capturedNpmPrivate']['cases'].pop(),
                lambda n:n['invocations'].pop(),lambda n:n['nodeShutdown']['record'].update(clean=False)]:
            changed=copy.deepcopy(node);mutate(changed)
            with self.assertRaises(WorkflowError):consumer.outcome(changed,probe)


if __name__=='__main__':unittest.main()

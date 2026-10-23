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
    def test_fixed_members_keep_cancelled_guest_and_separate_host_origins(self):
        value = inputs.fixture()
        self.assertEqual(len(value['members']),67)
        self.assertEqual(sum(r['bytes'] for r in value['members'].values()),63463957)
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
        self.assertEqual(len(inputs.preflight(Archive())),67)
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

"""Positive runtime witnesses and original Java component identity fences."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import java_resource_runtime_node as runtime
from tools import qualify_java_resource_runtime as qualification
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest


def write_json(path,value):
    path.write_bytes((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode())


class JavaJoinedOwners(unittest.TestCase):
    @staticmethod
    def witness():
        inventory={'topology':{'available':True,'complete':True,'entries':[
            {'name':name,'activeCount':'1'} for name in runtime.LIVE]}}
        usage={'tenantUsage':{'scope':'tenant','unavailable':[],'counters':{'calls':'1','sessions':'1'}},
            'nodeUsage':{'scope':'node','unavailable':[],'counters':{'broker_calls':'1'}}}
        pages=[{'category':'success','outcomeKnown':True,'data':{'page':{'nextPageToken':None},
            'coverage':{'droppedObservations':'1'},'records':[]}}]
        stderr=runtime.observer.PREFIX+b'|pending|start-accepted|1|1|0|1\n'+runtime.observer.PREFIX+b'|pending|next-entered|2|1|1|1\n'
        return inventory,usage,pages,stderr

    def test_timer_and_fallback_wait_paths_require_actual_positive_host_wait_and_original_root(self):
        i,u,p,s=self.witness()
        timer=runtime.pending_witness(i,u,p,'node-stop-pending',s)
        self.assertEqual(timer['positiveTimer']['positivePoint'],'accepted runtime timer then begin_wait')
        wait=runtime.observer.PREFIX+b'|pending|wait-pending|1|1|1|1\n'
        self.assertEqual(runtime.pending_witness(i,u,p,'node-stop-pending',wait)['positiveTimer']['positivePoint'],
            'original wait-for Poll::Pending')
        for raw in (b'',s.splitlines()[0]+b'\n',s.splitlines()[1]+b'\n',
            s.replace(b'|2|1|1|1',b'|2|0|1|1'),wait.replace(b'|1|1|1|1',b'|1|0|1|1'),
            wait.replace(b'|1|1|1|1',b'|1|1|0|1'),wait.replace(b'pending',b'drain')):
            with self.subTest(raw=raw):
                try:self.assertIsNone(runtime.pending_witness(i,u,p,'node-stop-pending',raw))
                except WorkflowError:pass
        with self.assertRaises(WorkflowError):runtime.positive_timer(s+runtime.observer.PREFIX+b'|overflow\n','node-stop-pending')

    def test_audit_loss_never_replaces_native_physical_or_provider_retention(self):
        i,u,p,s=self.witness()
        self.assertTrue(runtime.pending_witness(i,u,p,'node-stop-pending',s)['audit']['explicitLoss'])
        for change in ('store','provider','zero-loss','incomplete'):
            inv,usage,pages=copy.deepcopy((i,u,p))
            if change=='store':inv['topology']['entries'][2]['activeCount']='0'
            elif change=='provider':usage['nodeUsage']['counters']['broker_calls']='0'
            elif change=='zero-loss':pages[0]['data']['coverage']['droppedObservations']='0'
            else:inv['topology']['complete']=False
            with self.subTest(change=change):
                if change=='incomplete':
                    with self.assertRaises(WorkflowError):runtime.pending_witness(inv,usage,pages,'node-stop-pending',s)
                else:self.assertIsNone(runtime.pending_witness(inv,usage,pages,'node-stop-pending',s))

    def test_closed_native_reader_rejects_unknown_duplicate_overflow_and_foreign_profile_counts(self):
        _i,_u,_p,s=self.witness();prefix=runtime.observer.PREFIX
        for raw in (s+s.splitlines()[0]+b'\n',s+prefix+b'|overflow\n',
            s.replace(b'next-entered',b'future-event'),s.replace(b'|2|1|1|1',b'|2|9|1|1'),
            s.replace(b'|2|1|1|1',b'|2|1|17|1'),s.replace(b'|2|1|1|1',b'|2|1|1|9')):
            with self.subTest(raw=raw),self.assertRaises(WorkflowError):runtime.positive_timer(raw,'node-stop-pending')
        self.assertEqual(runtime.observer.observe(b'x'*(runtime.observer.MAXIMUM_STDERR+1))['status'],'invalid-source')

    def test_current_mode_cannot_borrow_the_other_public_activation_pending_event(self):
        i,u,p,_s=self.witness()
        raw=runtime.observer.PREFIX+b'|drain|wait-pending|1|1|1|1\n'
        self.assertIsNone(runtime.pending_witness(i,u,p,'node-stop-pending',raw))
        self.assertTrue(runtime.pending_witness(i,u,p,'node-stop-drain',raw)['providerCallRetained'])

    def test_stale_before_invocation_observation_is_refused_and_read_deadline_restored(self):
        i,u,p,s=self.witness()
        def call(*args,**_kwargs):
            if args[0]=='audit':return p[0]
            if args[0]=='node':return {'data':{'inventory':i}}
            if args[0]=='capability':return {'data':u}
            self.fail('unexpected command')
        original=time.monotonic()+100
        client=SimpleNamespace(deadline=original,call=call,node=SimpleNamespace(drain=lambda:None,buffers=[b'',s]))
        pending=SimpleNamespace(owner=SimpleNamespace(exited=lambda:False),authoring_activation='node-stop-pending',
            authoring_started_unix_millis=1)
        with tempfile.TemporaryDirectory() as directory,patch.object(runtime.time,'sleep'),patch.object(runtime,'sample',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'pending-witness-attempts'):
                runtime.wait_pending(client,pending,None,{'name':'owned'},Path(directory),'stale',len(s))
            self.assertEqual(client.deadline,original)
            self.assertTrue(runtime.wait_pending(client,pending,None,{'name':'owned'},Path(directory),'fresh',0))

    def test_caught_callback_error_remains_a_success_value_and_root_trap_stays_terminal(self):
        component='sha256:'+'a'*64;revision={'releaseDigest':component}
        usage=dict.fromkeys(('outboundRequests','childCalls','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes'),'0')
        usage.update(cpuFuel='1',peakMemoryBytes='4194304',logBytes='32')
        row={'processReaped':True,'exitCode':0,'decoded':[{'ok':runtime.fixture.EXPECTED['callback-error']}],
            'response':{'outcomeKnown':True,'data':{'resolvedRevision':revision,'consumption':usage}}}
        runtime.checked_invocation(row,component,revision,'callback-error')
        trap=copy.deepcopy(row);trap['exitCode']=4;trap['response']['error']={'code':'guest-trap'}
        runtime.checked_invocation(trap,component,revision,'trap')
        with self.assertRaises(WorkflowError):runtime.checked_invocation(trap,component,revision,'callback-error')
        for change in ('unreaped','foreign','effects'):
            bad=copy.deepcopy(row)
            if change=='unreaped':bad['processReaped']=False
            elif change=='foreign':bad['response']['data']['resolvedRevision']={'releaseDigest':'sha256:'+'b'*64}
            else:bad['response']['data']['consumption']['outboundRequests']='1'
            with self.subTest(change=change),self.assertRaises(WorkflowError):runtime.checked_invocation(bad,component,revision,'callback-error')

    @staticmethod
    def build(directory):
        docs={'source-inputs.json':{},'recipe-inputs.json':{},'package-inputs.json':{},'source-origins.json':{},
            'coroutine-compiler-profile.json':{},'application-dependencies.json':{},'java-classpath.json':{},
            'runtime-profile.json':{'profile':qualification.FIBER_IO_PROFILE,'checkpointClasses':[
                'dev.latent.app.Capsule','outside.resourceruntime.Library','outside.resourceruntimedata.Data']},
            'bindings.json':{'immutableResources':{'profile':qualification.RESOURCE_PROFILE,
                'resourceInputs':json.loads(runtime.fixture.inventory(runtime.fixture.DATA)),
                'streamOwnership':'fresh-decoded-byte-array-per-open'}}}
        for name,data in docs.items():write_json(directory/name,data)
        component=b'controlled-component';(directory/'component.wasm').write_bytes(component)
        materials=[{'name':name,'digest':digest((directory/file).read_bytes()),'size':(directory/file).stat().st_size}
            for name,file in (('build-recipe','recipe-inputs.json'),('package-inputs','package-inputs.json'),
                ('java-runtime-profile','runtime-profile.json'),('java-source-origins','source-origins.json'),
                ('application-dependency-closure','application-dependencies.json'),('java-classpath-selection','java-classpath.json'))]
        observed={'componentDigest':digest(component),'componentSize':len(component),'materials':materials,
            'parameters':{'compiler':'teavm-c','entryPoint':'dev.latent.app.Capsule','target':'wasm32-wasip1',
                'bindings':'lsf-java-wit-v1','optimization':'O2','javaHeapBytes':4194304}}
        write_json(directory/'build-observation.json',observed)
        write_json(directory/'BUILD-COMPLETE.json',{'packageAssembled':True,'javaRuntimeProfile':qualification.FIBER_IO_PROFILE,
            'componentDigest':digest(component),'observationDigest':digest((directory/'build-observation.json').read_bytes()),
            'sourceDigest':digest((directory/'source-inputs.json').read_bytes())})

    def test_rehashed_profile_checkpoint_and_resource_substitution_cannot_borrow_observed_build(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(qualification,'package_identity',return_value={}):
            directory=Path(temporary);self.build(directory)
            self.assertEqual(qualification.build_evidence(directory)['package'],{})
            for change in ('profile','checkpoint','resource'):
                self.build(directory)
                name='bindings.json' if change=='resource' else 'runtime-profile.json'
                value=json.loads((directory/name).read_bytes())
                if change=='profile':value['profile']='teavm-activation-fibers-v1'
                elif change=='checkpoint':value['checkpointClasses'].remove('outside.resourceruntime.Library')
                else:value['immutableResources']['streamOwnership']='shared-stream'
                write_json(directory/name,value)
                observed=json.loads((directory/'build-observation.json').read_bytes())
                for material in observed['materials']:
                    if material['name']=='java-runtime-profile':
                        raw=(directory/'runtime-profile.json').read_bytes();material.update(digest=digest(raw),size=len(raw))
                write_json(directory/'build-observation.json',observed)
                marker=json.loads((directory/'BUILD-COMPLETE.json').read_bytes())
                marker['observationDigest']=digest((directory/'build-observation.json').read_bytes());write_json(directory/'BUILD-COMPLETE.json',marker)
                with self.subTest(change=change),self.assertRaises(WorkflowError):qualification.build_evidence(directory)


if __name__=='__main__':unittest.main()

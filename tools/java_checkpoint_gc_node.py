"""Two actual GC witness calls and fresh-state reuse on the original Java node profile."""
from __future__ import annotations
from pathlib import Path
import json
import tempfile
import time

from tools import java_checkpoint_gc_fixture as fixture, resource_tenant_node as tenants
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.java_http_release_preparation import prepare
from tools.java_resource_runtime_node import LIMITS, OPERATIONS, _grant
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign, signed_inputs, stop_observation_peer
from tools.resource_runtime_node import retire
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, call, configure, delete_all, deploy, sample, selected_revision
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.sdk_provider_scenario import close_failed_provider, start_provider

CASES = (('examples','gc'),('foreign','gc'),('examples','fresh'),('foreign','fresh'))


def configuration(settings, capsule):
    imports=capsule['imports']
    require(len(imports)==3 and {r['contract'] for r in imports}=={*fixture.CLOCKS,fixture.ACTIVATION}
        and all(r=={'contract':r['contract'],'optional':False} for r in imports),
        'java-checkpoint-only-two-clocks-and-activation')
    tenants.configure(settings,{**capsule,'imports':[r for r in imports if r['contract']!=fixture.ACTIVATION]},'java')
    providers=settings['providers']
    providers['activationRuntime']={'identity':{'id':'activation','tenant':'examples','service':'activation-host','epoch':1},
        'limits':dict(LIMITS)}
    providers['scalarAliases'].append({'source':'activation','identity':{
        'id':'activation-foreign','tenant':'foreign','service':'foreign-activation','epoch':1}})
    for tenant in tenants.TENANTS:
        providers['bindings'].append({'name':'activation-'+tenant,'tenant':tenant,'consumerService':'my-greeting',
            'providerService':'activation-host' if tenant=='examples' else 'foreign-activation',
            'contract':fixture.ACTIVATION,'providerBinding':'activation-'+tenant+'-installed'})
    return settings


def invoke(client,target,mode,label,component,*,diagnostic=None):
    revision=selected_revision(client,target)
    row=call(client,target,'greeting','greet',[mode],label)
    require(revision['releaseDigest']==component and row['processReaped']
        and row['response']['outcomeKnown'] and row['response']['data']['resolvedRevision']==revision,
        'java-checkpoint-actual-known-signed-revision')
    usage=row['response']['data']['consumption']
    matched = row['exitCode']==0 and row['decoded']==[{'ok':fixture.EXPECTED[mode]}]
    if not matched and diagnostic is not None:
        node, native, output = diagnostic
        from tools.java_checkpoint_gc_fault_frames import capture
        capture(node, native, component, output)
    require(matched
        and 0<int(usage['cpuFuel'])<=1000000000 and 0<int(usage['peakMemoryBytes'])<=67108864
        and all(int(usage[k])==0 for k in ('childCalls','outboundRequests','logBytes','effectCount',
            'stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
        'java-checkpoint-exact-observable-and-original-no-effect-budgets')
    return row


def execute(artifact,native,output,deadline,component,*,diagnostic=False):
    output=fresh(output)
    seconds=int(min(600,deadline-time.monotonic()))
    require(seconds>=120,'java-checkpoint-reserved-runtime-window')
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=seconds,command_seconds=120)
    record={'schemaVersion':'lsf.java.checkpoint-gc-node.v1','status':'incomplete','cases':[],
        'grantDenials':[],'fullTicketQualification':False,'garbageCollectionObserved':False,
        'nativeThreadsQualified':False,'networkCapabilityGranted':False}
    node=peer=None;clients={};stage='sign-only-existing-fresh-component'
    try:
        signed=output/'signed'
        commands.run(stage,native['capsule_authoring'],'demo-sign-neutral-resources',signed,artifact)
        release=signed_inputs(signed,component)
        with owned_cancellation() as cancellation,tempfile.TemporaryDirectory(prefix='lsf-java-checkpoint-') as temporary:
            work=Path(temporary)
            for name in ('examples','node','peer'):(work/name).mkdir(mode=0o700)
            client=RecordingClient(native['latent'],work/'examples',cancellation,commands.deadline,
                evidence=output/'examples-controls',invocation_timeout_millis=120000,control_timeout_millis=15000)
            clients['examples']=client;peer,port=start_provider(client,work/'peer',maximum_seconds=seconds)
            try:
                config,settings=configure(work/'node',signed,port,language='java')
                config.write_bytes((json.dumps(configuration(settings,read_json(artifact/'capsule.json')),
                    sort_keys=True,separators=(',',':'))+'\n').encode())
                stage='original-profile-node-startup'
                node=connect(client,native['latentd'],work/'node',config,'examples',0)
                clients['foreign']=client_for_foreign(client,node,work/'foreign',output/'foreign-controls')
                record['startup']=node.startup_record;probe=Probe(node,file_identity(native['latentd']))
                targets={};record['preparations']={}
                for tenant in tenants.TENANTS:
                    selected=clients[tenant]
                    published=selected.call('release','publish-package',signed/'my-greeting/package',
                        '--evidence',signed/'my-greeting/evidence/index.json','--operation-id','checkpoint-publish-'+tenant,
                        '--expected-generation','0')
                    require(published['outcomeKnown'] and published['data']['release']['digest']==component,
                        'java-checkpoint-admitted-component')
                    publication=published['data']['operation']['publication']['id']
                    record['preparations'][tenant]=prepare(selected,publication,tenant,component,output)
                    manifest=selected.directory/'deployment.json'
                    write_json(manifest,tenants.scoped_deployment(read_json(signed/'my-greeting/deployment.json'),tenant))
                    target=deploy(selected,manifest,publication)
                    target=tenants.install_grants(selected,node,manifest,publication,target,list(fixture.CLOCKS),'java',tenant)
                    denied=call(selected,target,'greeting','greet',['fresh'],'checkpoint-denied-'+tenant)
                    tenants.require_denied_before_guest(denied)
                    record['grantDenials'].append({'tenant':tenant,'invocation':denied,
                        'provider':tenants.provider_idle(selected,target)})
                    targets[tenant]=_grant(selected,node,manifest,publication,target,tenant,
                        capability=fixture.ACTIVATION,name='activation',profile='activation-owned-v1',kind='clock',
                        operations=OPERATIONS,service='activation-host' if tenant=='examples' else 'foreign-activation')
                    require({r['capability'] for r in targets[tenant]['grants']}=={*fixture.CLOCKS,fixture.ACTIVATION},
                        'java-checkpoint-no-implicit-or-network-grant')
                stage='signed-published-loop-and-monitor-programme'
                for index,(tenant,mode) in enumerate(CASES):
                    selected,target=clients[tenant],targets[tenant];label=f'checkpoint-{index}-{tenant}-{mode}'
                    context=(node,file_identity(native['latentd']),output) if diagnostic else None
                    row=invoke(selected,target,mode,label,component,diagnostic=context)
                    record['cases'].append({'tenant':tenant,'mode':mode,'invocation':row,
                        'retirement':retire(selected,probe,target,output,label)})
                    write_workflow_receipt(output/f'progress-{index}.json',record)
                for tenant in tenants.TENANTS:delete_all(clients[tenant],[targets[tenant]['name']])
                record['afterDeletes']=sample(client,probe,'checkpoint-after-deletes',0)
                clients['foreign'].node=None;stop(client,node);record['nodeShutdown']=stopped_record(node)
                record['peerShutdown']=stop_observation_peer(peer)
            finally:
                for selected in clients.values():selected.node=None
                if node is not None:node.close()
                if peer is not None:
                    if 'peerShutdown' not in record:record['peerFailure']=close_failed_provider(peer)
                    else:peer.close()
            cancellation.check()
        require(len(record['cases'])==4 and len(record['grantDenials'])==2
            and record['nodeShutdown']['reaped'] and record['nodeShutdown']['record']['clean']
            and time.monotonic()<commands.deadline and sum(c.calls for c in clients.values())<=256,
            'java-checkpoint-all-outcomes-and-physical-node-retirement')
        record.update(status='passed',garbageCollectionObserved=True,signedRelease=release,commands=commands.records)
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        write_workflow_receipt(output/'FAILED.json',record);raise

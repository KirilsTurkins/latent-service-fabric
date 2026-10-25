"""Actual finite Task.Wait results and root cancellation retain physical owners."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import time
from tools import dotnet_finite_wait_fixture as fixture
from tools import dotnet_task_runtime_probe as authority
from tools import dotnet_resource_runtime_node as witness
from tools import dotnet_resource_timer_observer as observer
from tools import resource_tenant_node as owners
from tools import guest_runtime_grants as clocks
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure, deploy, delete_all, call, start_call, finish_call, sample, selected_revision
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.sdk_provider_scenario import start_provider, close_failed_provider


def checked(row, component, revision, mode, *, selected_fixture=fixture):
    response=row['response'];used=response['data']['consumption']
    require(row['processReaped'] and response['outcomeKnown'] is True
        and revision['releaseDigest']==component and response['data']['resolvedRevision']==revision,
        'finite-wait-known-reaped-selected-component')
    require(0<int(used['cpuFuel'])<=1000000000 and 0<int(used['peakMemoryBytes'])<=134217728
        and all(int(used[k])==0 for k in ('outboundRequests','childCalls','effectCount','logBytes',
            'stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')), 'finite-wait-original-budget-no-effects')
    if mode in ('root-cancel','root-deadline'):
        require(row['exitCode']==4 and response['error']['code']=={
            'root-cancel':'cancelled','root-deadline':'deadline-exceeded'}[mode], 'finite-wait-root-terminal-not-success')
    else:
        require(row['exitCode']==0 and row['decoded']==[{'ok':selected_fixture.expected(mode)}],
            'finite-wait-exact-standard-library-result')


def pending(client, process, probe, target, output, label, offset):
    require(type(offset) is int and 0<=offset<=observer.MAXIMUM_STDERR, 'finite-wait-observer-offset')
    original=client.deadline;client.deadline=min(original,time.monotonic()+10)
    try:
        for attempt in range(16):
            require(time.monotonic()<client.deadline and not process.owner.exited(), 'finite-wait-live-before-terminal')
            pages=[];token=None
            for _ in range(4):
                args=('audit','query','--scope','tenant','--page-size','64','--from-unix-millis',
                    str(max(0,process.authoring_started_unix_millis-1)))
                if token is not None:args+=('--page-token',token)
                page=client.call(*args,codes=(0,4));pages.append(page)
                if page['category']!='success':break
                token=page['data']['page']['nextPageToken']
                if token is None:break
            inventory=client.call('node','get','operator-workflow-test')['data']['inventory']
            usage=client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']
            client.node.drain()
            value=witness.pending_witness(inventory,usage,pages,process.authoring_activation,bytes(client.node.buffers[1])[offset:])
            if value is not None:
                require(not process.owner.exited(), 'finite-wait-not-terminal-before-live-witness')
                record={'witness':value,'inventory':inventory,'providerUsage':usage,'auditPages':pages,
                    'physical':sample(client,probe,label,1,active=True),'attempts':attempt+1}
                write_json(output/('pending-'+label+'.json'),record);return record
            time.sleep(0.01)
        raise RuntimeError('finite-wait-pending-witness-attempts')
    finally:client.deadline=original


def run(artifact: Path,native: dict,output: Path, *, aggregate: bool=False):
    require(type(aggregate) is bool, 'finite-wait-closed-programme-selection')
    selected_fixture=fixture
    prefix='finite:'
    fresh_mode='infinite-join-regression'
    if aggregate:
        from tools import dotnet_aggregate_wait_fixture as selected_fixture
        prefix=selected_fixture.PREFIX
        fresh_mode=selected_fixture.FRESH
    output=fresh(output);component=file_identity(artifact/'component.wasm')
    before={k:file_identity(p) for k,p in native.items()}
    record={'schemaVersion':'latent.dotnet.finite-task-waits.node.v1','status':'incomplete',
        'cases':[],'attempts':[],'fullTicketQualification':False,'native':before,'component':component}
    if aggregate:
        record['schemaVersion']='latent.dotnet.aggregate-task-waits.node.v1'
        record['expectedCaseOrder']=[*selected_fixture.CASES,'root-cancel',fresh_mode,'root-deadline',fresh_mode]
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=360,command_seconds=120)
    peer=node=client=None;stage='normal-single-component-signing'
    def checkpoint():
        (output/'progress.json').write_bytes((json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode())
    try:
        signed=output/'signed';commands.run(stage,native['capsule_authoring'],'demo-sign',signed,artifact)
        release=read_json(signed/'release-set.json')['releases']
        require(len(release)==1 and release[0]['componentDigest']==component['sha256'],'finite-wait-one-original-component-signature')
        with owned_cancellation() as cancellation,tempfile.TemporaryDirectory(prefix='lsf-finite-task-waits-') as temporary:
            work=Path(temporary)
            for name in ('client','node','peer'):(work/name).mkdir(mode=0o700)
            client=RecordingClient(native['latent'],work/'client',cancellation,min(commands.deadline,time.monotonic()+300),
                evidence=output/'controls',invocation_timeout_millis=120000,control_timeout_millis=15000)
            peer,port=start_provider(client,work/'peer',maximum_seconds=300)
            try:
                config,settings=configure(work/'node',signed,port,language='dotnet',runtime_grants=True);authority.configure(settings)
                config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode())
                client.environment[observer.ENVIRONMENT]='1'
                stage='original-node-and-runtime-authority';node=connect(client,native['latentd'],work/'node',config,'examples',0)
                record['startup']=node.startup_record;probe=Probe(node,file_identity(native['latentd']))
                published=client.call('release','publish-package',signed/'my-greeting/package',
                    '--evidence',signed/'my-greeting/evidence/index.json','--operation-id','finite-wait-publish','--expected-generation','0')
                require(published['outcomeKnown'] is True and published['data']['release']['digest']==component['sha256'],
                    'finite-wait-normal-component-admission')
                publications={'greeting':published['data']['operation']['publication']['id']}
                targets={'greeting':deploy(client,signed/'my-greeting/deployment.json',publications['greeting'])}
                original={'invocations':[]}
                clocks.grant(client,node,signed,targets,publications,original,language='dotnet')
                authority.grant(client,node,signed,targets,publications,original)
                target=targets['greeting'];record['authority']=original
                record['afterGrants']={'provider':owners.provider_idle(client,target),
                    'physical':sample(client,probe,'finite-wait-after-grants',1)}
                def retire(label):
                    return {'provider':owners.provider_idle(client,target),'physical':sample(client,probe,label,1)}
                def invoke(mode,label):
                    revision=selected_revision(client,target)
                    row=call(client,target,'greeting','greet',[prefix+mode],label)
                    record['attempts'].append({'mode':mode,'invocation':row});checkpoint()
                    checked(row,component['sha256'],revision,mode,selected_fixture=selected_fixture)
                    record['cases'].append({'mode':mode,'invocation':row,'retirement':retire(label+'-retired')});checkpoint()
                for index,mode in enumerate(selected_fixture.CASES):
                    stage=mode;invoke(mode,'finite-wait-'+str(index))
                for mode,label in (('root-cancel','node-stop-pending'),('root-deadline','node-stop-drain')):
                    stage=mode;revision=selected_revision(client,target);node.drain();offset=len(node.buffers[1])
                    active=start_call(client,target,'greeting','greet',[prefix+'pending-root'],label,wall=3000 if mode=='root-deadline' else None)
                    try:
                        live=pending(client,active,probe,target,output,label,offset);ack=None
                        if mode=='root-cancel':
                            ack=client.call('activation','cancel',label,'--reason','Owned finite Task.Wait cancellation')
                            require(ack['outcomeKnown'] is True and ack['data']['disposition']=='accepted','finite-wait-root-cancel-accepted')
                        row=finish_call(client,active)
                        record['attempts'].append({'mode':mode,'invocation':row,'live':live,'cancelAcknowledgement':ack});checkpoint()
                        checked(row,component['sha256'],revision,mode,selected_fixture=selected_fixture)
                        record['cases'].append({'mode':mode,'invocation':row,'live':live,'cancelAcknowledgement':ack,
                            'retirement':retire(label+'-retired')});checkpoint()
                    finally:active.close()
                    invoke(fresh_mode,'finite-wait-fresh-after-'+mode)
                require(len(record['cases'])==len(selected_fixture.CASES)+4,'finite-wait-all-ordered-cases')
                if aggregate:
                    require([row['mode'] for row in record['cases']]==record['expectedCaseOrder'],
                        'aggregate-wait-fourteen-original-ordered-outcomes')
                delete_all(client,[target['name']]);record['afterDeletes']=sample(client,probe,'finite-wait-after-deletes',0)
                stop(client,node);record['nodeShutdown']=stopped_record(node);record['peerShutdown']=stop_observation_peer(peer)
                stderr=bytes(node.buffers[1]);(output/'node-stderr.txt').write_bytes(stderr)
                record['nativeWaitObservations']=observer.observe(stderr)
                require(record['nodeShutdown']['reaped'] and record['nodeShutdown']['record']['clean'], 'finite-wait-clean-node-shutdown')
            finally:
                client.node=None
                if node is not None:node.close();(output/'node-stderr.txt').write_bytes(bytes(node.buffers[1]))
                if peer is not None:
                    if 'peerShutdown' not in record:record['peerFailure']=close_failed_provider(peer)
                    else:peer.close()
            cancellation.check()
        require(before=={k:file_identity(p) for k,p in native.items()}
            and component==file_identity(artifact/'component.wasm') and client.calls<=384
            and time.monotonic()<commands.deadline,'finite-wait-final-native-component-and-deadline')
        record.update(status='passed',cliCalls=client.calls,commands=commands.records)
        write_json(output/'qualified.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage);write_json(output/'FAILED.json',record);raise

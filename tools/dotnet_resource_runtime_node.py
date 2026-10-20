"""Finite ordinary managed callbacks retaining immutable resources and owners."""
from __future__ import annotations
import json
import time

from tools import dotnet_resource_runtime_fixture as fixture
from tools import dotnet_resource_timer_observer as observer
from tools import resource_tenant_node as resources
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK, WALL, RANDOM, LOG
from tools.dotnet_task_runtime_probe import OPERATIONS
from tools.go_node_stop_probe import refused_observation
from tools.phase2_operator_process import require, write_json
from tools.resource_runtime_node import integer, LIVE, retire
from tools.rust_capsule_node import call, deploy, finish_call, sample, selected_revision, start_call

LIMITS={'tasks':8,'executors':2,'queuedWork':8,'waits':16,'timers':8,'results':8,'nativeOwners':8}
SCALARS=(CLOCK,WALL,RANDOM,LOG)
SERVICES={'examples':'activation-host','foreign':'foreign-activation'}
MODES={'node-stop-pending':'pending','node-stop-drain':'drain'}


def configure(settings,capsule):
    rows=capsule.get('imports')
    require(type(rows) is list and len(rows)==5
        and all(type(row) is dict and set(row)=={'contract','optional'} and row['optional'] is False for row in rows)
        and {row['contract'] for row in rows}=={ACTIVATION,*SCALARS},'resource-dotnet-exact-imports')
    resources.configure(settings,{**capsule,'imports':[row for row in rows if row['contract']!=ACTIVATION]},'dotnet')
    providers=settings['providers']
    providers['activationRuntime']={'identity':{'id':'activation','tenant':'examples','service':SERVICES['examples'],'epoch':1},
        'limits':dict(LIMITS)}
    providers['scalarAliases'].append({'source':'activation','identity':{'id':'activation-foreign',
        'tenant':'foreign','service':SERVICES['foreign'],'epoch':1}})
    for tenant in resources.TENANTS:
        providers['bindings'].append({'name':'activation-'+tenant,'tenant':tenant,'consumerService':'my-greeting',
            'providerService':SERVICES[tenant],'contract':ACTIVATION,'providerBinding':'activation-'+tenant+'-installed'})
    require(len(providers['bindings'])==11 and len(providers['scalarAliases'])==5,
        'resource-dotnet-original-provider-capacity')
    return settings


def call_mode(client,target,mode,label):
    return call(client,target,'greeting','greet',['resource-runtime:'+mode],label)


def grant(client,node,manifest,publication,target,tenant):
    target=resources.install_grants(client,node,manifest,publication,target,list(SCALARS),'dotnet',tenant)
    denied=call_mode(client,target,'fresh','resource-dotnet-'+tenant+'-without-runtime')
    resources.require_denied_before_guest(denied)
    identity='activation' if tenant=='examples' else 'activation-foreign'
    rows=[row for row in node.startup_record['providers'] if row['id']==identity]
    require(len(rows)==1 and rows[0]['tenant']==tenant and rows[0]['service']==SERVICES[tenant]
        and rows[0]['capability']==ACTIVATION and rows[0]['profile']=='activation-owned-v1'
        and rows[0]['configurationEpoch']=='1','resource-dotnet-exact-runtime-profile')
    binding_id,policy_id='activation-'+tenant+'-installed','resource-activation-'+tenant
    path=client.directory/(binding_id+'.json')
    write_json(path,{'formatVersion':1,'tenant':tenant,'capability':ACTIVATION,'providerProfile':'activation-owned-v1',
        'configurationDigest':rows[0]['configurationDigest'],'configurationEpoch':1,'restriction':{'operations':list(OPERATIONS)}})
    client.call('policy','--kind','provider-binding','apply','--id',binding_id,'--file',path,
        '--operation-id','resource-dotnet-install-runtime-'+tenant,'--expected-generation','0')
    path=client.directory/(policy_id+'.json')
    write_json(path,{'formatVersion':1,'tenant':tenant,'rules':[{'id':'ordinary-resource-callbacks','effect':'allow',
        'principals':[{'kind':'administrator','subject':resources.SUBJECTS[tenant]}],
        'services':[target['service']],'publications':[publication],'capability':ACTIVATION,
        'operations':list(OPERATIONS),'resources':{'kind':'clock'},
        'ceiling':{'operations':4096,'inputBytes':0,'outputBytes':32768,'wallTimeMillis':5000}}]})
    client.call('policy','apply','--id',policy_id,'--file',path,'--operation-id','resource-dotnet-grant-runtime-'+tenant,
        '--expected-generation','0')
    return deploy(client,manifest,publication,generation=str(target['generation']),
        grants=[*target['grants'],{'capability':ACTIVATION,'policy':policy_id}]),denied


def grant_secure(client,node,manifest,publication,target,tenant):
    """Add only the secure operation to this selected fixture's original budget."""
    provider='random' if tenant=='examples' else 'random-foreign'
    rows=[row for row in node.startup_record['providers'] if row['id']==provider]
    require(len(rows)==1 and rows[0]['tenant']==tenant and rows[0]['profile']=='system-random-v1'
        and rows[0]['capability']==RANDOM,'resource-dotnet-original-entropy-provider')
    binding_id='random-'+tenant+'-installed';policy_id='random-'+tenant+'-allow'
    path=client.directory/('resource-secure-binding-'+tenant+'.json')
    write_json(path,{'formatVersion':1,'tenant':tenant,'capability':RANDOM,'providerProfile':'system-random-v1',
        'configurationDigest':rows[0]['configurationDigest'],'configurationEpoch':1,
        'restriction':{'operations':['bytes','u64-value']}})
    client.call('policy','--kind','provider-binding','apply','--id',binding_id,'--file',path,
        '--operation-id','resource-dotnet-secure-binding-'+tenant,'--expected-generation','1')
    path=client.directory/('resource-secure-policy-'+tenant+'.json')
    write_json(path,{'formatVersion':1,'tenant':tenant,'rules':[{'id':'ordinary-resource-entropy','effect':'allow',
        'principals':[{'kind':'administrator','subject':resources.SUBJECTS[tenant]}],
        'services':[target['service']],'publications':[publication],'capability':RANDOM,
        'operations':['bytes','u64-value'],'resources':{'kind':'random'},
        'ceiling':{'operations':16,'inputBytes':8,'outputBytes':4096,'wallTimeMillis':5000}}]})
    client.call('policy','apply','--id',policy_id,'--file',path,'--operation-id','resource-dotnet-secure-policy-'+tenant,
        '--expected-generation','1')
    return deploy(client,manifest,publication,generation=str(target['generation']),grants=target['grants'])


def positive_timer(stderr,activation):
    require(activation in MODES,'resource-dotnet-closed-observer-activation')
    value=observer.observe(stderr)
    require(value['status'] in {'not-observed','observed'},'resource-dotnet-valid-observer')
    pair=[row for row in value['records'] if row['mode']==MODES[activation]]
    if len(pair)<2:return None
    require(len(pair)==2 and [row['event'] for row in pair]==['start-accepted','next-entered']
        and pair[0]['sequence']<pair[1]['sequence']
        and pair[0]['timers']==pair[1]['timers']==1 and pair[0]['waits']==0 and pair[1]['waits']==1
        and all(0<row['tasks']<=LIMITS['tasks'] for row in pair),'resource-dotnet-real-timer-wait')
    return {'activation':activation,'records':pair,'nativeObserver':value,
        'positivePoint':'RuntimeTimer::begin_wait after exact returned timer token lookup'}


def pending_witness(inventory,usage,pages,activation,stderr):
    topology=inventory['topology']
    require(topology['available'] and topology['complete'],'resource-dotnet-live-topology')
    rows={row['name']:row for row in topology['entries']}
    require(len(rows)==len(topology['entries']) and set(LIVE)<=rows.keys(),'resource-dotnet-named-live-owners')
    if any(integer(rows[name]['activeCount'])!=1 for name in LIVE):return None
    require(usage['tenantUsage']['scope']=='tenant' and usage['nodeUsage']['scope']=='node'
        and not usage['tenantUsage']['unavailable'] and not usage['nodeUsage']['unavailable'],
        'resource-dotnet-available-provider-owners')
    if min(integer(usage['tenantUsage']['counters']['calls']),integer(usage['tenantUsage']['counters']['sessions']),
        integer(usage['nodeUsage']['counters']['broker_calls']))<1:return None
    require(type(pages) is list and 0<len(pages)<=4,'resource-dotnet-bounded-audit')
    if pages[0].get('category')!='success':
        require(len(pages)==1,'resource-dotnet-one-refused-audit-read');audit={'readRefusal':refused_observation(pages[0])}
    else:
        require(pages[-1]['data']['page']['nextPageToken'] is None,'resource-dotnet-complete-audit-page')
        starts=[];waits=[];identities=set();epochs=set()
        for page in pages:
            require(page['category']=='success' and page['outcomeKnown'],'resource-dotnet-audit-success')
            for row in page['data']['records']:
                require(type(row['epoch']) is str and len(row['epoch'])==32
                    and all(c in '0123456789abcdef' for c in row['epoch']),'resource-dotnet-audit-epoch')
                key=(row['epoch'],integer(row['sequence']))
                require(key[1]>0 and key not in identities,'resource-dotnet-distinct-audit-record');identities.add(key)
                observed=row.get('data',{}).get('observation',{});identity=observed.get('identities',{}).get('capability',{})
                if identity.get('activation')!=activation or identity.get('capability')!=ACTIVATION:continue
                require(identity['rootActivation']==activation and identity['providerProfile']=='activation-owned-v1',
                    'resource-dotnet-original-activation-provider');epochs.add(row['epoch'])
                if observed['kind']=='PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME' and identity['operation']=='timer-start' \
                    and identity.get('providerOutcome')=='AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED':starts.append(key[1])
                if observed['kind']=='PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED' and identity['operation']=='timer-next' \
                    and observed['outcome']=='AUDIT_OBSERVATION_OUTCOME_SUCCEEDED':waits.append(key[1])
        dropped=[integer(page['data']['coverage']['droppedObservations']) for page in pages]
        correlated=bool(starts and waits and max(waits)>max(starts))
        if not correlated and not any(dropped):return None
        require(len(epochs)<=1 and (not correlated or len(epochs)==1),'resource-dotnet-single-audit-epoch')
        audit={'timerLabelsCorrelated':correlated,'droppedObservations':dropped,'explicitLoss':not correlated}
    positive=positive_timer(stderr,activation)
    if positive is None:return None
    return {'activation':activation,'physicalOwners':{name:1 for name in LIVE},'providerCallRetained':True,
        'positiveTimer':positive,'audit':audit,'auditAloneIsBarrierEvidence':False}


def wait_pending(client,pending,probe,target,output,label,offset):
    require(type(offset) is int and 0<=offset<=observer.MAXIMUM_STDERR,'resource-dotnet-observer-offset')
    original=client.deadline;deadline=min(original,time.monotonic()+10);client.deadline=deadline
    try:
        for attempt in range(16):
            require(time.monotonic()<deadline and not pending.owner.exited(),'resource-dotnet-actual-pending-before-terminal')
            client.node.drain();pages=[];token=None
            for _ in range(4):
                command=('audit','query','--scope','tenant','--page-size','64',
                    '--from-unix-millis',str(max(0,pending.authoring_started_unix_millis-1)))
                if token is not None:command+=('--page-token',token)
                page=client.call(*command,codes=(0,4));pages.append(page)
                if page['category']!='success':break
                token=page['data']['page']['nextPageToken']
                if token is None:break
            inv=client.call('node','get','operator-workflow-test')['data']['inventory']
            usage=client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']
            client.node.drain();witness=pending_witness(inv,usage,pages,pending.authoring_activation,bytes(client.node.buffers[1])[offset:])
            if witness is not None:
                require(not pending.owner.exited(),'resource-dotnet-ended-before-witness')
                value={'witness':witness,'inventory':inv,'providerUsage':usage,'auditPages':pages,
                    'physical':sample(client,probe,label,2,active=True),'attempts':attempt+1}
                write_json(output/('pending-'+label+'.json'),value);return value
            time.sleep(0.01)
        raise RuntimeError('resource-dotnet-pending-witness-attempts')
    finally:client.deadline=original


def checked_invocation(row,component,revision,mode):
    response=row['response'];usage=response['data']['consumption']
    require(row['processReaped'] and response['outcomeKnown'] and revision['releaseDigest']==component
        and response['data']['resolvedRevision']==revision,'resource-dotnet-selected-known-reaped')
    require(0<int(usage['cpuFuel'])<=1000000000 and 0<int(usage['peakMemoryBytes'])<=134217728
        and 0<=int(usage['logBytes'])<=16384 and all(int(usage[key])==0 for key in
            ('outboundRequests','childCalls','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
        'resource-dotnet-original-budgets-no-effects')
    terminal={'trap':'guest-trap','callback-error':'guest-trap','cancel':'cancelled','deadline':'deadline-exceeded'}.get(mode)
    if terminal:
        require(row['exitCode']==4 and response['error']['code']==terminal,'resource-dotnet-exact-terminal')
        if mode!='trap':require(int(usage['logBytes'])>0,'resource-dotnet-callback-or-pending-log-reached')
    else:
        require(row['exitCode']==0 and row['decoded']==[{'ok':fixture.EXPECTED[mode]}] and int(usage['logBytes'])>0,
            'resource-dotnet-exact-library-result-and-log')


def programme(clients,targets,probe,output,component):
    value={'status':'incomplete','cases':[],'attempts':[],'fullTicketQualification':False,
        'nativeThreadsQualified':False,'threadLocalQualified':False,'asyncFlushQueuePresent':False,
        'lateWakeAttemptObserved':False,'concurrencyKind':'original-managed-TaskPool-and-TimerQueue'}
    def checkpoint():
        (output/'programme-progress.json').write_bytes((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode())
    def invoke(tenant,mode,label):
        client,target=clients[tenant],targets[tenant];revision=selected_revision(client,target)
        row=call_mode(client,target,mode,label);value['attempts'].append({'tenant':tenant,'mode':mode,'invocation':row});checkpoint()
        checked_invocation(row,component,revision,mode)
        value['cases'].append({'tenant':tenant,'mode':mode,'invocation':row,
            'retirement':retire(client,probe,target,output,label),'callbackOriginProven':False});checkpoint()
    invoke('examples','parallel','resource-dotnet-parallel')
    invoke('foreign','fresh','resource-dotnet-foreign-fresh')
    invoke('examples','clear','resource-dotnet-clear')
    invoke('examples','trap','resource-dotnet-root-trap')
    invoke('foreign','fresh','resource-dotnet-foreign-after-trap')
    for mode in ('cancel','deadline'):
        client,target=clients['examples'],targets['examples'];label='node-stop-pending' if mode=='cancel' else 'node-stop-drain'
        revision=selected_revision(client,target);client.node.drain();offset=len(client.node.buffers[1])
        pending=start_call(client,target,'greeting','greet',['resource-runtime:pending'],label,wall=3000 if mode=='deadline' else None)
        try:
            live=wait_pending(client,pending,probe,target,output,label,offset);ack=None
            if mode=='cancel':
                ack=client.call('activation','cancel',label,'--reason','Owned managed resource callback cancellation')
                require(ack['outcomeKnown'] and ack['data']['disposition']=='accepted','resource-dotnet-root-cancel-accepted')
            row=finish_call(client,pending);value['attempts'].append({'tenant':'examples','mode':mode,'invocation':row,
                'live':live,'cancelAcknowledgement':ack});checkpoint();checked_invocation(row,component,revision,mode)
            value['cases'].append({'tenant':'examples','mode':mode,'invocation':row,'live':live,
                'cancelAcknowledgement':ack,'retirement':retire(client,probe,target,output,label)});checkpoint()
        finally:pending.close()
        invoke('foreign','fresh','resource-dotnet-foreign-after-'+mode)
    invoke('foreign','callback-error','resource-dotnet-callback-error')
    invoke('examples','fresh','resource-dotnet-fresh-after-callback-error')
    require(len(value['cases'])==11,'resource-dotnet-eleven-joined-outcomes')
    value['status']='passed';write_json(output/'programme.json',value);return value

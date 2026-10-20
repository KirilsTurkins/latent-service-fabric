"""Original Java fiber-I/O owners with explicit resource/facility authority."""
from __future__ import annotations
import json
import time

from tools import java_resource_timer_observer as observer
from tools.go_node_stop_probe import refused_observation
from tools.resource_runtime_node import integer, LIVE, retire

from tools import java_resource_runtime_fixture as fixture
from tools import resource_tenant_node as resources
from tools.phase2_operator_process import require,write_json
from tools.rust_capsule_node import call,deploy,finish_call,sample,selected_revision,start_call

CLOCK,WALL,RANDOM,LOG,ACTIVATION=fixture.CAPABILITIES
SCALARS=(CLOCK,WALL,RANDOM,LOG)
OPERATIONS=['register','park','wake','settle','close','observe','wait-for',
    'wait-until','timer-start','timer-next','timer-stop']
# The already maintained Java fiber-I/O profile, not a new scheduler capacity.
LIMITS={'tasks':8,'executors':2,'queuedWork':8,'waits':16,'timers':8,'results':8,'nativeOwners':8}
SERVICES={'examples':'activation-host','foreign':'foreign-activation'}


def configure(settings,capsule):
    rows=capsule.get('imports')
    require(type(rows) is list and len(rows)==5
        and all(type(row) is dict and set(row)=={'contract','optional'} and row['optional'] is False for row in rows)
        and {row['contract'] for row in rows}==set(fixture.CAPABILITIES),'resource-java-exact-imports')
    resources.configure(settings,{**capsule,'imports':[row for row in rows if row['contract']!=ACTIVATION]},'java')
    providers=settings['providers']
    providers['activationRuntime']={'identity':{'id':'activation','tenant':'examples','service':SERVICES['examples'],'epoch':1},
        'limits':dict(LIMITS)}
    providers['scalarAliases'].append({'source':'activation','identity':{'id':'activation-foreign',
        'tenant':'foreign','service':SERVICES['foreign'],'epoch':1}})
    for tenant in resources.TENANTS:
        providers['bindings'].append({'name':'activation-'+tenant,'tenant':tenant,'consumerService':'my-greeting',
            'providerService':SERVICES[tenant],'contract':ACTIVATION,'providerBinding':'activation-'+tenant+'-installed'})
    require(len(providers['bindings'])==11 and len(providers['scalarAliases'])==5,'resource-java-original-provider-capacity')
    return settings


def call_mode(client,target,mode,label):
    return call(client,target,'greeting','greet',['resource-runtime:'+mode],label)


def _grant(client,node,manifest,publication,target,tenant,*,capability,name,profile,kind,operations,service):
    provider=name if tenant=='examples' else name+'-foreign'
    rows=[row for row in node.startup_record['providers'] if row['id']==provider]
    require(len(rows)==1 and rows[0]['tenant']==tenant and rows[0]['service']==service
        and rows[0]['capability']==capability and rows[0]['profile']==profile
        and rows[0]['configurationEpoch']=='1','resource-java-exact-installed-provider')
    binding_id=name+'-'+tenant+'-installed';policy_id='resource-'+name+'-'+tenant
    path=client.directory/(binding_id+'.json')
    write_json(path,{'formatVersion':1,'tenant':tenant,'capability':capability,'providerProfile':profile,
        'configurationDigest':rows[0]['configurationDigest'],'configurationEpoch':1,
        'restriction':{'operations':list(operations)}})
    client.call('policy','--kind','provider-binding','apply','--id',binding_id,'--file',path,
        '--operation-id','resource-java-install-'+name+'-'+tenant,'--expected-generation','0')
    path=client.directory/(policy_id+'.json')
    write_json(path,{'formatVersion':1,'tenant':tenant,'rules':[{'id':'ordinary-resource-callbacks','effect':'allow',
        'principals':[{'kind':'administrator','subject':resources.SUBJECTS[tenant]}],
        'services':[target['service']],'publications':[publication],'capability':capability,
        'operations':list(operations),'resources':{'kind':kind},
        'ceiling':{'operations':4096,'inputBytes':8 if kind=='random' else 0,
            'outputBytes':32768,'wallTimeMillis':5000}}]})
    client.call('policy','apply','--id',policy_id,'--file',path,
        '--operation-id','resource-java-grant-'+name+'-'+tenant,'--expected-generation','0')
    return deploy(client,manifest,publication,generation=str(target['generation']),
        grants=[*target['grants'],{'capability':capability,'policy':policy_id}])


def grants(client,node,manifest,publication,target,tenant):
    # Java SecureRandom uses the existing byte-result backend. Do not grant the
    # unrelated scalar operation or label a Java campaign as another language.
    target=resources.install_grants(client,node,manifest,publication,target,[CLOCK,WALL,LOG],'java',tenant)
    target=_grant(client,node,manifest,publication,target,tenant,capability=RANDOM,name='random',
        profile='system-random-v1',kind='random',operations=('bytes',),
        service='runtime-host' if tenant=='examples' else 'foreign-runtime')
    denied=call_mode(client,target,'fresh','resource-java-'+tenant+'-without-runtime')
    resources.require_denied_before_guest(denied)
    target=_grant(client,node,manifest,publication,target,tenant,capability=ACTIVATION,name='activation',
        profile='activation-owned-v1',kind='clock',operations=OPERATIONS,service=SERVICES[tenant])
    require({row['capability'] for row in target['grants']}==set(fixture.CAPABILITIES),
        'resource-java-only-five-explicit-grants')
    return target,denied


MODES={'node-stop-pending':'pending','node-stop-drain':'drain'}


def positive_timer(stderr,activation):
    require(activation in MODES,'resource-java-closed-observer-activation')
    value=observer.observe(stderr)
    require(value['status'] in {'not-observed','observed'},'resource-java-valid-observer')
    rows=[row for row in value['records'] if row['mode']==MODES[activation]]
    if not rows:return None
    require(len(rows)<=8 and all(1<=row['tasks']<=LIMITS['tasks'] for row in rows),
        'resource-java-original-root-task-and-recorder-bounds')
    # Activation.waitFor selects a matching TimerLease, otherwise wait-for.
    # Both paths must reach their actual host wait; preparation is insufficient.
    waits=[row for row in rows if row['event']=='wait-pending'
        and row['waits']>=1 and row['timers']>=1]
    starts=[row for row in rows if row['event']=='start-accepted' and row['timers']>=1]
    entered=[row for row in rows if row['event']=='next-entered'
        and row['waits']>=1 and row['timers']>=1]
    pair=any(start['sequence']<wait['sequence'] for start in starts for wait in entered)
    if not waits and not pair:return None
    return {'activation':activation,'records':rows,'nativeObserver':value,
        'positivePoint':'original wait-for Poll::Pending' if waits else 'accepted runtime timer then begin_wait',
        'auditAloneIsBarrierEvidence':False,'goProgrammeExecutionClaimed':False}


def pending_witness(inventory,usage,pages,activation,stderr):
    topology=inventory['topology']
    require(topology['available'] and topology['complete'],'resource-java-live-topology')
    rows={row['name']:row for row in topology['entries']}
    require(len(rows)==len(topology['entries']) and set(LIVE)<=rows.keys(),'resource-java-named-live-owners')
    if any(integer(rows[name]['activeCount'])!=1 for name in LIVE):return None
    require(usage['tenantUsage']['scope']=='tenant' and usage['nodeUsage']['scope']=='node'
        and not usage['tenantUsage']['unavailable'] and not usage['nodeUsage']['unavailable'],
        'resource-java-available-provider-owners')
    if min(integer(usage['tenantUsage']['counters']['calls']),integer(usage['tenantUsage']['counters']['sessions']),
        integer(usage['nodeUsage']['counters']['broker_calls']))<1:return None
    require(type(pages) is list and 0<len(pages)<=4,'resource-java-bounded-audit')
    if pages[0].get('category')!='success':
        require(len(pages)==1,'resource-java-one-refused-audit-read');audit={'readRefusal':refused_observation(pages[0])}
    else:
        require(pages[-1]['data']['page']['nextPageToken'] is None,'resource-java-complete-audit-page')
        waits=[];identities=set();epochs=set()
        for page in pages:
            require(page['category']=='success' and page['outcomeKnown'],'resource-java-audit-success')
            for row in page['data']['records']:
                require(type(row['epoch']) is str and len(row['epoch'])==32
                    and all(c in '0123456789abcdef' for c in row['epoch']),'resource-java-audit-epoch')
                key=(row['epoch'],integer(row['sequence']))
                require(key[1]>0 and key not in identities,'resource-java-distinct-audit-record');identities.add(key)
                observed=row.get('data',{}).get('observation',{});identity=observed.get('identities',{}).get('capability',{})
                if identity.get('activation')!=activation or identity.get('capability')!=ACTIVATION:continue
                require(identity['rootActivation']==activation and identity['providerProfile']=='activation-owned-v1',
                    'resource-java-original-activation-provider');epochs.add(row['epoch'])
                if observed['kind']=='PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED' and identity['operation'] in {'wait-for','timer-next'} \
                    and observed['outcome']=='AUDIT_OBSERVATION_OUTCOME_SUCCEEDED':waits.append(key[1])
        dropped=[integer(page['data']['coverage']['droppedObservations']) for page in pages]
        correlated=bool(waits)
        if not correlated and not any(dropped):return None
        require(len(epochs)<=1 and (not correlated or len(epochs)==1),'resource-java-single-audit-epoch')
        audit={'runtimeWaitGrantCorrelated':correlated,'droppedObservations':dropped,'explicitLoss':not correlated}
    positive=positive_timer(stderr,activation)
    if positive is None:return None
    return {'activation':activation,'physicalOwners':{name:1 for name in LIVE},'providerCallRetained':True,
        'positiveTimer':positive,'audit':audit,'auditAloneIsBarrierEvidence':False}


def wait_pending(client,pending,probe,target,output,label,offset):
    require(type(offset) is int and 0<=offset<=observer.MAXIMUM_STDERR,'resource-java-observer-offset')
    original=client.deadline;deadline=min(original,time.monotonic()+10);client.deadline=deadline
    try:
        for attempt in range(16):
            require(time.monotonic()<deadline and not pending.owner.exited(),'resource-java-actual-pending-before-terminal')
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
                require(not pending.owner.exited(),'resource-java-ended-before-witness')
                value={'witness':witness,'inventory':inv,'providerUsage':usage,'auditPages':pages,
                    'physical':sample(client,probe,label,2,active=True),'attempts':attempt+1}
                write_json(output/('pending-'+label+'.json'),value);return value
            time.sleep(0.01)
        raise RuntimeError('resource-java-pending-witness-attempts')
    finally:client.deadline=original


def checked_invocation(row,component,revision,mode):
    response=row['response'];usage=response['data']['consumption']
    require(row['processReaped'] and response['outcomeKnown'] and revision['releaseDigest']==component
        and response['data']['resolvedRevision']==revision,'resource-java-selected-known-reaped')
    require(0<int(usage['cpuFuel'])<=1000000000 and 0<int(usage['peakMemoryBytes'])<=67108864
        and 0<=int(usage['logBytes'])<=256 and all(int(usage[key])==0 for key in
            ('outboundRequests','childCalls','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
        'resource-java-original-budgets-no-effects')
    terminal={'trap':'guest-trap','cancel':'cancelled','deadline':'deadline-exceeded'}.get(mode)
    if terminal:
        require(row['exitCode']==4 and response['error']['code']==terminal,'resource-java-exact-terminal')
        if mode!='trap':require(int(usage['logBytes'])>0,'resource-java-callback-or-pending-log-reached')
    else:
        require(row['exitCode']==0 and row['decoded']==[{'ok':fixture.EXPECTED[mode]}] and int(usage['logBytes'])>0,
            'resource-java-exact-library-result-and-log')


def programme(clients,targets,probe,output,component):
    value={'status':'incomplete','cases':[],'attempts':[],'fullTicketQualification':False,
        'nativeThreadsQualified':False,'nativeThreadLocalQualified':False,'asyncFlushQueuePresent':False,
        'lateWakeAttemptObserved':False,'concurrencyKind':'original-Java-activation-fibers-and-Timer-workers'}
    def checkpoint():
        (output/'programme-progress.json').write_bytes((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode())
    def invoke(tenant,mode,label):
        client,target=clients[tenant],targets[tenant];revision=selected_revision(client,target)
        row=call_mode(client,target,mode,label);value['attempts'].append({'tenant':tenant,'mode':mode,'invocation':row});checkpoint()
        checked_invocation(row,component,revision,mode)
        value['cases'].append({'tenant':tenant,'mode':mode,'invocation':row,
            'retirement':retire(client,probe,target,output,label),'callbackOriginProven':False});checkpoint()
    invoke('examples','parallel','resource-java-parallel')
    invoke('foreign','fresh','resource-java-foreign-fresh')
    invoke('examples','clear','resource-java-clear')
    invoke('examples','trap','resource-java-root-trap')
    invoke('foreign','fresh','resource-java-foreign-after-trap')
    for mode in ('cancel','deadline'):
        client,target=clients['examples'],targets['examples'];label='node-stop-pending' if mode=='cancel' else 'node-stop-drain'
        revision=selected_revision(client,target);client.node.drain();offset=len(client.node.buffers[1])
        pending=start_call(client,target,'greeting','greet',['resource-runtime:pending'],label,wall=3000 if mode=='deadline' else None)
        try:
            live=wait_pending(client,pending,probe,target,output,label,offset);ack=None
            if mode=='cancel':
                ack=client.call('activation','cancel',label,'--reason','Owned Java resource callback cancellation')
                require(ack['outcomeKnown'] and ack['data']['disposition']=='accepted','resource-java-root-cancel-accepted')
            row=finish_call(client,pending);value['attempts'].append({'tenant':'examples','mode':mode,'invocation':row,
                'live':live,'cancelAcknowledgement':ack});checkpoint();checked_invocation(row,component,revision,mode)
            value['cases'].append({'tenant':'examples','mode':mode,'invocation':row,'live':live,
                'cancelAcknowledgement':ack,'retirement':retire(client,probe,target,output,label)});checkpoint()
        finally:pending.close()
        invoke('foreign','fresh','resource-java-foreign-after-'+mode)
    invoke('foreign','callback-error','resource-java-callback-error')
    invoke('examples','fresh','resource-java-fresh-after-callback-error')
    require(len(value['cases'])==11,'resource-java-eleven-joined-outcomes')
    value['status']='passed';write_json(output/'programme.json',value);return value

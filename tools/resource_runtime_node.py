"""Finite resource/callback lifecycle integration using the original node owners."""
from __future__ import annotations
import json
import time

from tools import resource_tenant_node as resources
from tools import typescript_resource_runtime_fixture as fixture
from tools import go_node_stop_timer_observer as timer_observer
from tools.phase2_operator_process import require
from tools.rust_capsule_node import call, deploy, finish_call, sample, selected_revision, start_call
from tools.rust_capsule_project import read_json, write_json

ACTIVATION = 'latent:runtime/activation@0.1.0'
OPERATIONS = ['register', 'park', 'wake', 'settle', 'close', 'timer-start', 'timer-next', 'timer-stop']
LIMITS = {'tasks':16, 'executors':2, 'queuedWork':16, 'waits':8, 'timers':8, 'results':8, 'nativeOwners':64}
SCALARS = ('latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0', 'latent:log/log@0.1.0')
SERVICE = 'my-greeting'
LIVE = ('execution-cell-leases', 'guest-invocations', 'guest-stores', 'guest-host-states', 'guest-component-instances')
PENDING_MODES = {'node-stop-pending':'pending', 'node-stop-drain':'drain'}


def integer(value):
    require(type(value) is int and 0 <= value < 2**64 or type(value) is str and value.isascii()
            and value.isdecimal() and len(value) <= 20 and int(value) < 2**64,
            'resource-runtime-unsigned-observation')
    return int(value)


def configure(settings, capsule):
    imports = capsule.get('imports')
    require(type(imports) is list and len(imports) == 4
            and all(type(r) is dict and set(r) == {'contract','optional'} and r['optional'] is False for r in imports)
            and {r['contract'] for r in imports} == {ACTIVATION,*SCALARS},
            'resource-runtime-exact-declared-imports')
    resources.configure(settings, {**capsule, 'imports':[r for r in imports if r['contract'] != ACTIVATION]}, 'typescript')
    providers = settings['providers']
    providers['activationRuntime'] = {'identity':{'id':'activation','tenant':'examples','service':'runtime-host','epoch':1},
                                      'limits':dict(LIMITS)}
    providers['scalarAliases'].append({'source':'activation', 'identity':{
        'id':'activation-foreign','tenant':'foreign','service':'foreign-runtime','epoch':1}})
    for tenant in resources.TENANTS:
        providers['bindings'].append({'name':'activation-'+tenant,'tenant':tenant,'consumerService':SERVICE,
            'providerService':'runtime-host' if tenant == 'examples' else 'foreign-runtime',
            'contract':ACTIVATION,'providerBinding':'activation-'+tenant+'-installed'})
    require(len(providers['bindings']) == 9 and len(providers['scalarAliases']) == 4,
            'resource-runtime-original-provider-capacity')
    return settings


def grant(client, node, manifest, publication, target, tenant):
    target = resources.install_grants(client,node,manifest,publication,target,list(SCALARS),'typescript',tenant)
    denied = call(client,target,'resource-runtime','run',['parallel'],'resource-'+tenant+'-without-runtime')
    resources.require_denied_before_guest(denied)
    identity = 'activation' if tenant == 'examples' else 'activation-foreign'
    rows = [r for r in node.startup_record['providers'] if r['id'] == identity]
    require(len(rows) == 1 and rows[0]['tenant'] == tenant and rows[0]['capability'] == ACTIVATION
            and rows[0]['profile'] == 'activation-owned-v1' and rows[0]['configurationEpoch'] == '1',
            'resource-runtime-exact-installed-profile')
    binding_id, policy_id = 'activation-'+tenant+'-installed', 'resource-activation-'+tenant
    binding = client.directory/(binding_id+'.json')
    write_json(binding, {'formatVersion':1,'tenant':tenant,'capability':ACTIVATION,
        'providerProfile':'activation-owned-v1','configurationDigest':rows[0]['configurationDigest'],'configurationEpoch':1,
        'restriction':{'operations':OPERATIONS}})
    client.call('policy','--kind','provider-binding','apply','--id',binding_id,'--file',binding,
        '--operation-id','install-resource-activation-'+tenant,'--expected-generation','0')
    policy = client.directory/(policy_id+'.json')
    write_json(policy, {'formatVersion':1,'tenant':tenant,'rules':[{'id':'resource-runtime','effect':'allow',
        'principals':[{'kind':'administrator','subject':resources.SUBJECTS[tenant]}],
        'services':[target['service']],'publications':[publication],'capability':ACTIVATION,'operations':OPERATIONS,
        'resources':{'kind':'clock'},'ceiling':{'operations':4096,'inputBytes':0,'outputBytes':32768,'wallTimeMillis':5000}}]})
    client.call('policy','apply','--id',policy_id,'--file',policy,
        '--operation-id','grant-resource-activation-'+tenant,'--expected-generation','0')
    return deploy(client,manifest,publication,generation=str(target['generation']),
                  grants=target['grants']+[{'capability':ACTIVATION,'policy':policy_id}]), denied


def positive_timer(stderr, activation):
    require(activation in PENDING_MODES, 'resource-runtime-closed-observer-activation')
    observation = timer_observer.observe(stderr)
    require(observation['status'] in ('not-observed', 'observed'), 'resource-runtime-valid-bounded-timer-observer')
    selected = [r for r in observation['records'] if r['mode'] == PENDING_MODES[activation]]
    if len(selected) < 2:return None
    require(len(selected) == 2 and [r['event'] for r in selected] == ['start-accepted','next-entered'],
            'resource-runtime-exact-accepted-then-entered-timer')
    start, waiting = selected
    require(start['sequence'] < waiting['sequence'] and start['timers'] == waiting['timers'] == 1
            and start['waits'] == 0 and waiting['waits'] == 1
            and 0 < start['tasks'] <= 16 and 0 < waiting['tasks'] <= 16,
            'resource-runtime-one-real-runtime-timer-and-wait')
    return {'nativeObserver':observation, 'activation':activation,
            'positivePoint':'RuntimeTimer::begin_wait after exact returned timer token lookup',
            'goProgrammeExecutionClaimed':False}


def pending_witness(inventory, usage, pages, activation, stderr):
    topology = inventory['topology']
    require(topology['available'] and topology['complete'], 'resource-runtime-complete-live-topology')
    rows = {r['name']:r for r in topology['entries']}
    require(len(rows) == len(topology['entries']) and all(name in rows for name in LIVE),
            'resource-runtime-named-live-owners')
    if any(integer(rows[name]['activeCount']) != 1 for name in LIVE):return None
    require(not usage['tenantUsage']['unavailable'] and not usage['nodeUsage']['unavailable'],
            'resource-runtime-available-live-provider-owners')
    require(usage['tenantUsage']['scope'] == 'tenant' and usage['nodeUsage']['scope'] == 'node',
            'resource-runtime-provider-observation-scopes')
    if min(integer(usage['tenantUsage']['counters']['calls']),integer(usage['tenantUsage']['counters']['sessions']),
           integer(usage['nodeUsage']['counters']['broker_calls'])) < 1:return None
    require(type(pages) is list and 0 < len(pages) <= 4 and pages[-1]['data']['page']['nextPageToken'] is None,
            'resource-runtime-complete-bounded-audit-page')
    starts, waits, identities, epochs = [], [], set(), set()
    for page in pages:
        require(page['category'] == 'success' and page['outcomeKnown'], 'resource-runtime-audit-success')
        for row in page['data']['records']:
            require(type(row['epoch']) is str and len(row['epoch']) == 32 and all(c in '0123456789abcdef' for c in row['epoch']),
                    'resource-runtime-audit-epoch')
            sequence = integer(row['sequence']);require(sequence > 0,'resource-runtime-audit-positive-sequence')
            key = (row['epoch'],sequence);require(key not in identities,'resource-runtime-audit-duplicate');identities.add(key)
            observed = row.get('data',{}).get('observation',{})
            identity = observed.get('identities',{}).get('capability',{})
            if identity.get('activation') != activation or identity.get('capability') != ACTIVATION:continue
            require(identity['rootActivation'] == activation and identity['providerProfile'] == 'activation-owned-v1',
                    'resource-runtime-original-activation-identity')
            epochs.add(row['epoch'])
            if observed['kind'] == 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME' and identity['operation'] == 'timer-start' \
                    and identity.get('providerOutcome') == 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED':starts.append(sequence)
            if observed['kind'] == 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED' and identity['operation'] == 'timer-next' \
                    and observed['outcome'] == 'AUDIT_OBSERVATION_OUTCOME_SUCCEEDED':waits.append(sequence)
    if not starts or not waits or max(waits) <= max(starts):return None
    require(len(epochs) == 1,'resource-runtime-single-activation-audit-epoch')
    positive = positive_timer(stderr, activation)
    if positive is None:return None
    return {'activation':activation,'physicalOwners':{name:1 for name in LIVE},
            'completedTimerStarts':starts,'laterTimerWaitAdmissions':waits,'retainedProviderCall':True,
            'positiveTimer':positive, 'auditEventsAloneProveTypedSuccess':False,
            'auditDroppedObservations':[p['data']['coverage']['droppedObservations'] for p in pages]}


def wait_pending(client, pending, probe, target, output, label):
    deadline = min(client.deadline,time.monotonic()+10)
    for attempt in range(16):
        require(time.monotonic() < deadline and not pending.owner.exited(),'resource-runtime-real-pending-before-terminal')
        client.node.drain()
        pages=[];token=None
        for _ in range(4):
            command=('audit','query','--scope','tenant','--page-size','64',
                     '--from-unix-millis',str(max(0,pending.authoring_started_unix_millis-1)))
            if token is not None:command+=('--page-token',token)
            page=client.call(*command);pages.append(page);token=page['data']['page']['nextPageToken']
            if token is None:break
        inventory=client.call('node','get','operator-workflow-test')['data']['inventory']
        usage=client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']
        client.node.drain()
        witness=pending_witness(inventory,usage,pages,pending.authoring_activation,bytes(client.node.buffers[1]))
        if witness is not None:
            require(not pending.owner.exited(),'resource-runtime-pending-ended-before-witness')
            record={'witness':witness,'inventory':inventory,'providerUsage':usage,'auditPages':pages,
                    'physical':sample(client,probe,label,2,active=True),'attempts':attempt+1}
            write_json(output/('pending-'+label+'.json'),record);return record
        time.sleep(0.01)
    raise RuntimeError('resource-runtime-pending-witness-attempts')


def retire(client, probe, target, output, label):
    idle=resources.provider_idle(client,target);physical=sample(client,probe,label,2)
    value={'provider':idle,'physical':physical};write_json(output/('retired-'+label+'.json'),value);return value


def programme(clients, targets, probe, output, component):
    result={'status':'incomplete','cases':[],'attempts':[],'concurrencyKind':'interleaved-runtime-owned-logical-tasks',
            'nativeThreadsQualified':False,'consoleFlushQueuePresent':False,'lateWakeAttemptObserved':False,
            'fullTicketQualification':False}
    def checkpoint():
        (output/'programme-progress.json').write_bytes((json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
    def invoke(tenant, mode, label, terminal=None):
        client,target=clients[tenant],targets[tenant];revision=selected_revision(client,target)
        row=call(client,target,'resource-runtime','run',[mode],label)
        result['attempts'].append({'tenant':tenant,'mode':mode,'invocation':row});checkpoint()
        require(row['processReaped'] and row['response']['outcomeKnown'] and revision['releaseDigest'] == component
                and row['response']['data']['resolvedRevision'] == revision,'resource-runtime-original-revision-and-terminal')
        usage=row['response']['data']['consumption']
        require(0<int(usage['cpuFuel'])<=target['budget']['cpuFuel'] and 0<int(usage['peakMemoryBytes'])<=target['budget']['memoryBytes']
                and all(int(usage[k])==0 for k in ('outboundRequests','childCalls','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
                'resource-runtime-original-budgets-no-external-effects')
        if terminal:
            require(row['exitCode']==4 and row['response']['error']['code']==terminal,'resource-runtime-exact-trap')
            if mode=='callback-error':require(0<int(usage['logBytes'])<=16384,'resource-runtime-callback-log-reached')
        else:require(row['exitCode']==0 and row['decoded']==[fixture.EXPECTED[mode]] and 0<int(usage['logBytes'])<=16384,
                     'resource-runtime-exact-resource-callback-value-and-log')
        result['cases'].append({'tenant':tenant,'mode':mode,'invocation':row,
            'retirement':retire(client,probe,target,output,label),'callbackOriginProven':False})
        checkpoint()
    invoke('examples','parallel','resource-callback-parallel')
    invoke('foreign','fresh','resource-callback-foreign-fresh')
    invoke('examples','clear','resource-callback-clear')
    invoke('examples','trap','resource-callback-root-trap','guest-trap')
    invoke('foreign','fresh','resource-callback-foreign-after-trap')
    for mode in ('cancel','deadline'):
        client,target=clients['examples'],targets['examples'];label='node-stop-pending' if mode=='cancel' else 'node-stop-drain'
        revision=selected_revision(client,target)
        pending=start_call(client,target,'resource-runtime','run',['pending'],label,wall=3000 if mode=='deadline' else None)
        try:
            live=wait_pending(client,pending,probe,target,output,label)
            cancellation=None
            if mode=='cancel':
                cancellation=client.call('activation','cancel',label,'--reason','Owned resource callback cancellation')
                require(cancellation['outcomeKnown'] and cancellation['data']['disposition']=='accepted',
                        'resource-runtime-root-cancel-accepted')
            row=finish_call(client,pending)
            result['attempts'].append({'tenant':'examples','mode':mode,'invocation':row,'live':live,
                                       'cancelAcknowledgement':cancellation});checkpoint()
            require(row['processReaped'] and row['response']['outcomeKnown'] and row['exitCode']==4
                    and row['response']['error']['code']==('cancelled' if mode=='cancel' else 'deadline-exceeded')
                    and row['response']['data']['resolvedRevision']==revision and revision['releaseDigest']==component,
                    'resource-runtime-original-cancel-or-deadline')
            usage=row['response']['data']['consumption']
            require(0<int(usage['cpuFuel'])<=target['budget']['cpuFuel']
                    and 0<int(usage['peakMemoryBytes'])<=target['budget']['memoryBytes']
                    and 0<int(usage['logBytes'])<=target['budget']['logBytes']
                    and all(int(usage[k])==0 for k in ('outboundRequests','childCalls','effectCount',
                        'stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
                    'resource-runtime-pending-original-budgets-and-post-start-log')
            result['cases'].append({'tenant':'examples','mode':mode,'invocation':row,'live':live,
                'cancelAcknowledgement':cancellation,'retirement':retire(client,probe,target,output,label)})
            checkpoint()
        finally:pending.close()
        invoke('foreign','fresh','resource-foreign-after-'+mode)
    invoke('foreign','callback-error','resource-callback-error','guest-trap')
    invoke('examples','fresh','resource-fresh-after-callback-error')
    require(len(result['cases'])==11,'resource-runtime-eleven-actual-outcomes')
    result['status']='passed';write_json(output/'programme.json',result);return result

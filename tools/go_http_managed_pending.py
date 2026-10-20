"""Positive managed Go timer/task ownership while ordinary HTTP is pending.

This only consumes the existing fixed-ID observer in the authenticated native
products. It never changes the production runtime, its errors or its ceilings.
"""
from __future__ import annotations

import re
import time

from tools.go_node_stop_timer_observer import ENVIRONMENT, PREFIX, MAXIMUM_STDERR
from tools.phase2_operator_process import require, write_json
from tools.go_node_stop_probe import integer, LIVE_ROWS as LIVE
from tools.rust_capsule_node import start_call, finish_call

LIMITS = {'tasks':16, 'waits':16, 'timers':8}
MODES = {'node-stop-pending':'pending','node-stop-drain':'drain'}
EVENTS = {'start-accepted','next-entered','wait-pending','root-close'}


def cases(domain):
    return (
        ('examples','sling-context-while-http-pending',4,'/conformance/hold/headers','cancelled',1),
        ('foreign','requests-context-while-http-pending',104,'/conformance/hold/headers','cancelled',1),
        ('examples','fresh-private-worker-after-both-deadlines',0,'/conformance/json',domain,1),
    )


def observe(stderr):
    value={'status':'not-observed','records':[],'partialRecord':False,'limits':dict(LIMITS),
        'nativeObserverOnly':True,'nativeRuntimeChanged':False}
    require(type(stderr) is bytes and len(stderr)<=MAXIMUM_STDERR,'go-http-managed-native-stderr-bound')
    if stderr and not stderr.endswith(b'\n'):
        tail=stderr.rsplit(b'\n',1)[-1]
        if tail.startswith(PREFIX) or PREFIX.startswith(tail):
            require(len(tail)<=128,'go-http-managed-native-partial-record-bound')
            stderr=stderr[:-len(tail)];value['partialRecord']=True
    counts=dict.fromkeys(MODES.values(),0);seen=set();markers=0
    for line in stderr.splitlines():
        if not line.startswith(PREFIX):continue
        markers+=1
        require(markers<=16 and len(line)<=128 and line!=PREFIX+b'|overflow',
            'go-http-managed-native-record-or-overflow-bound')
        fields=line.split(b'|')
        require(len(fields)==7 and fields[0]==PREFIX and fields[1] in {b'pending',b'drain'}
            and fields[2] in {event.encode() for event in EVENTS}
            and all(re.fullmatch(rb'0|[1-9][0-9]{0,1}',field) for field in fields[3:]),
            'go-http-managed-closed-native-record')
        sequence,tasks,waits,timers=map(int,fields[3:]);mode=fields[1].decode()
        require(1<=sequence<=15 and sequence not in seen and counts[mode]<8
            and tasks<=16 and waits<=16 and timers<=8,'go-http-managed-native-owner-limits')
        seen.add(sequence);counts[mode]+=1
        value['records'].append({'mode':mode,'event':fields[2].decode(),'sequence':sequence,
            'tasks':tasks,'waits':waits,'timers':timers})
    value['records'].sort(key=lambda row:row['sequence'])
    require([row['sequence'] for row in value['records']]==list(range(1,len(value['records'])+1)),
        'go-http-managed-complete-native-sequence')
    if value['records']:value['status']='observed'
    return value


def positive(stderr,activation):
    require(activation in MODES,'go-http-managed-fixed-public-observer-activation')
    value=observe(stderr)
    selected=[row for row in value['records'] if row['mode']==MODES[activation]]
    require(not any(row['event']=='root-close' for row in selected),'go-http-managed-root-already-closed')
    starts=[row for row in selected if row['event']=='start-accepted']
    entered=[row for row in selected if row['event']=='next-entered']
    waits=[row for row in selected if row['event']=='wait-pending']
    if value['partialRecord'] or len(starts)!=1 or not entered or not waits:return None
    last=entered[-1]
    # In v5 the private worker's ordinary Sleep uses wait-for, not timer-start.
    # Its real Poll::Pending precedes the separately accepted context timer.
    # That timer's actual next retains maintenance plus application Tasks.
    if not any(row['sequence']<starts[0]['sequence'] and 9<=row['tasks']<=16
        and row['timers']==1 for row in waits):return None
    if last['sequence']<=starts[0]['sequence'] or not (9<=last['tasks']<=16
        and 1<=last['waits']<=16 and last['timers']==1):return None
    return {'nativeObserver':value,'activation':activation,'lastEntered':last,
        'maintenanceTasks':8,'applicationTasksAtLeast':last['tasks']-8,
        'positivePoint':'timer-next after successful owned RuntimeTimer.begin_wait'}


def live(inventory,usage,stderr,activation):
    timer=positive(stderr,activation)
    if timer is None:return None
    topology=inventory['topology']
    require(topology['available'] is True and topology['complete'] is True,'go-http-managed-complete-live-topology')
    rows={row['name']:row for row in topology['entries']}
    require(len(rows)==len(topology['entries']) and set(LIVE)<=rows.keys(),'go-http-managed-named-original-owners')
    if any(integer(rows[name]['activeCount'])!=1 for name in LIVE):return None
    require(integer(inventory['queueDepth'])==0,'go-http-managed-no-hidden-root-queue')
    tenant,node=usage['tenantUsage'],usage['nodeUsage']
    require(usage['nextPageToken'] is None and tenant['scope']=='tenant' and node['scope']=='node'
        and not tenant['unavailable'] and not node['unavailable'],'go-http-managed-available-provider-usage')
    required=('broker_calls','pool_active_connections','pool_running_requests')
    if min(integer(tenant['counters']['calls']),integer(tenant['counters']['sessions']),
        *(integer(node['counters'][name]) for name in required))<1:return None
    return {'positiveTimer':timer,'physicalOwners':{name:1 for name in LIVE},
        'providerOwners':{name:node['counters'][name] for name in required},
        'tenantCalls':tenant['counters']['calls'],'tenantSessions':tenant['counters']['sessions'],
        'hostCompletedUsedAsTimerProof':False,'postRetirementOnlyProof':False}


def invoke(client,target,which,address,activation,output):
    require((which,activation) in {(4,'node-stop-pending'),(104,'node-stop-drain')},
        'go-http-managed-closed-client-and-observer-mode')
    pending=start_call(client,target,'go-standard-http','run',[which,address],activation)
    original=client.deadline;client.deadline=min(original,time.monotonic()+2)
    try:
        for attempt in range(16):
            require(time.monotonic()<client.deadline and not pending.owner.exited(),
                'go-http-managed-request-ended-before-positive-live-witness')
            client.node.drain();stderr=bytes(client.node.buffers[1]);timer=positive(stderr,activation)
            entry={'attempt':attempt+1,'timerObserver':observe(stderr),'witness':None}
            if timer is not None:
                inventory=client.call('node','get','operator-workflow-test')['data']['inventory']
                usage=client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']
                client.node.drain()
                entry.update(inventory=inventory,providerUsage=usage,
                    witness=live(inventory,usage,bytes(client.node.buffers[1]),activation))
            write_json(output/(activation+'-live-'+str(attempt+1)+'.json'),entry)
            require(not pending.owner.exited(),'go-http-managed-request-ended-during-live-observation')
            if entry['witness'] is not None:
                client.deadline=original
                row=finish_call(client,pending)
                client.node.drain();terminal=observe(bytes(client.node.buffers[1]))
                require(any(event['mode']==MODES[activation] and event['event']=='root-close'
                    for event in terminal['records']),'go-http-managed-real-root-close-after-context')
                return row,{'live':entry,'terminalTimerObserver':terminal}
            time.sleep(.01)
        raise RuntimeError('go-http-managed-positive-observation-attempt-bound')
    finally:
        client.deadline=original
        try:
            pending.drain();client.node.drain()
            for index,name in enumerate(('stdout','stderr')):
                (output/(activation+'.'+name+'.log')).write_bytes(bytes(pending.buffers[index]))
            stderr=bytes(client.node.buffers[1])
            require(len(stderr)<=MAXIMUM_STDERR,'go-http-managed-native-stderr-bound')
            (output/'native-timer-observer.stderr.log').write_bytes(stderr)
        finally:pending.close()


def peer_outcome(value,tenant,domain):
    from tools.standard_http.observations import validate
    validate(value)
    expected=[row for row in cases(domain) if row[0]==tenant]
    require(value['acceptedConnections']==value['startedRequests']==len(expected)
        and value['openConnections']==value['rejectedRequests']==value['connectionBoundRejections']==value['committedMutations']==0
        and [(row['role'],row.get('vector')) for row in value['requests']]==[
            ('primary','pending-headers' if row[2] in (4,104) else 'domain-json') for row in expected],
        'go-http-managed-exact-own-client-contacts')
    require(all(row.get('authorizationPresent') is True and row.get('cookiePresent') is False
        and row.get('proxyAuthorizationPresent') is False for row in value['requests']),
        'go-http-managed-original-credential-isolation')
    held={row['request'] for row in value['requests'] if row.get('vector')=='pending-headers'}
    require(len(held)==1 and {row['request'] for row in value['events']
        if row['kind']=='gate-pending' and row.get('phase')=='headers'}==held
        and not any(row['kind']=='gate-released' for row in value['events'])
        and all(row['responseBytesWritten']==0 for row in value['requests'] if row['request'] in held),
        'go-http-managed-context-ended-request-without-peer-release-or-response')

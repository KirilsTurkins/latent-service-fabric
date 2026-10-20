"""Strict live-work and shutdown evidence; neither a sleep nor handle drop is proof."""
from tools.phase2_operator_process import require

ACTIVATION = 'latent:runtime/activation@0.1.0'
PROFILE = 'activation-owned-v1'
# The exact original finite Go synchronization/admission profile, not TS limits.
OWNER_LIMITS = {'tasks': 16, 'executors': 2, 'queuedWork': 2, 'waits': 4,
                'timers': 2, 'results': 2, 'nativeOwners': 2}
OPERATIONS = ['register', 'park', 'wake', 'settle', 'close', 'timer-start', 'timer-next', 'timer-stop']
ZERO_FIELDS = ('activeConnections', 'activeRpcs', 'activeControlJobs', 'activeActivations',
    'cancellationRegistrations', 'observerCorrelations', 'quotaReservations', 'queuedReservations',
    'reservedCpuFuel', 'reservedMemoryBytes', 'activeLeases', 'queuedActivations', 'quarantinedCells',
    'activeBackendInvocations', 'instanceReservations', 'preparingComponents', 'preparingSourceBytes',
    'preparingMetadataBytes', 'liveStores', 'liveHostStates', 'liveInstances', 'liveTemporaryBuffers',
    'liveCancellationProbes')
LIVE_ROWS = ('execution-cell-leases', 'guest-invocations', 'guest-stores',
             'guest-host-states', 'guest-component-instances')


def integer(value):
    require(type(value) is int and value >= 0 or type(value) is str and value.isascii()
            and value.isdecimal() and len(value) <= 20, 'Go-node-stop-finite-observation')
    result = int(value)
    require(result < 2**64, 'Go-node-stop-finite-observation')
    return result


def barrier(inventory, pages, activation, mode, *, provider_usage):
    """Require named positive timer witnesses and actual retained provider/Store work."""
    require(mode in ('pending', 'drain'), 'Go-node-stop-closed-mode')
    topology = inventory['topology']
    require(topology['available'] is True and topology['complete'] is True,
            'Go-node-stop-complete-topology')
    rows = {row['name']: row for row in topology['entries']}
    require(len(rows) == len(topology['entries']) and all(name in rows for name in LIVE_ROWS),
            'Go-node-stop-physical-owner-observation')
    if any(integer(rows[name]['activeCount']) != 1 for name in LIVE_ROWS):
        return None
    require(integer(inventory['queueDepth']) == 0, 'Go-node-stop-no-hidden-root-queue')
    tenant, node = provider_usage['tenantUsage'], provider_usage['nodeUsage']
    require(tenant['scope'] == 'tenant' and node['scope'] == 'node', 'Go-node-stop-provider-usage-scope')
    sessions, calls, node_calls = (integer(tenant['counters']['sessions']),
        integer(tenant['counters']['calls']), integer(node['counters']['broker_calls']))
    if min(sessions, calls, node_calls) == 0:
        return None
    require(0 < len(pages) <= 4, 'Go-node-stop-audit-page-bound')
    events = {}
    dropped = []
    for page in pages:
        require(page['category'] == 'success' and page['outcomeKnown'] is True,
                'Go-node-stop-audit-unavailable')
        coverage = page['data']['coverage']
        # Optional capture uses try_lock and can drop unrelated observations.
        # Retain loss honestly; only the named positives below authorize stop.
        dropped.append(integer(coverage['droppedObservations']))
        records = page['data']['records']
        require(type(records) is list and len(records) <= 64, 'Go-node-stop-audit-record-bound')
        for row in records:
            identity = (integer(row['epoch']), integer(row['sequence']))
            require(identity not in events, 'Go-node-stop-duplicate-audit')
            events[identity] = row
    require(pages[-1]['data']['page']['nextPageToken'] is None, 'Go-node-stop-incomplete-audit')
    allowed = []
    timer_next_sequences = []
    completed_timers = []
    for row in events.values():
        observation = row.get('data', {}).get('observation')
        if not observation:
            continue
        capability = observation.get('identities', {}).get('capability')
        if not capability or capability.get('activation') != activation:
            continue
        if capability['capability'] != ACTIVATION:
            continue
        require(capability['rootActivation'] == activation and capability['providerProfile'] == PROFILE,
                'Go-node-stop-exact-activation-provider')
        if observation['kind'] == 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_GRANT_ALLOWED':
            require(observation['outcome'] == 'AUDIT_OBSERVATION_OUTCOME_SUCCEEDED',
                    'Go-node-stop-allowed-outcome')
            allowed.append(capability['operation'])
            if capability['operation'] == 'timer-next':
                timer_next_sequences.append(integer(row['sequence']))
        if observation['kind'] == 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME' and capability['operation'] == 'timer-start':
            if capability.get('providerOutcome') == 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED':
                completed_timers.append(integer(row['sequence']))
    # One initializer timer precedes the one/two actual long-lived body timers.
    # timer-next must also be dispatched after those checked start results.
    # HostCompleted alone also permits a typed error. The immutable fixture's
    # runtime checks each start result before a later timer-next can be reached.
    # Real ProviderCall ownership must additionally remain live in this sample.
    minimum = 3 if mode == 'pending' else 2
    if len(completed_timers) < minimum or allowed.count('timer-next') < 2:
        return None
    if max(timer_next_sequences) <= max(completed_timers):
        return None
    if mode == 'drain' and 'close' not in allowed:
        return None
    return {'mode': mode, 'activation': activation, 'livePhysicalRows': {name: 1 for name in LIVE_ROWS},
            'hostCompletedTimerStarts': len(completed_timers), 'allowedTimerNext': allowed.count('timer-next'),
            'rootCloseObserved': 'close' in allowed, 'droppedObservations': max(dropped),
            'observationCoverage': 'named-positive-witnesses-only', 'diagnosticStreamComplete': False,
            'retainedProviderUsage': {'tenantSessions': sessions, 'tenantCalls': calls, 'nodeCalls': node_calls},
            'actualNodeSignalSent': False}


def shutdown(stopped):
    require(stopped['reaped'] is True and stopped['record']['event'] == 'stopped'
            and stopped['record']['clean'] is True, 'Go-node-stop-actual-reaped-shutdown')
    report = stopped['record']['report']
    require(report['clean'] is True and all(name in report and integer(report[name]) == 0 for name in ZERO_FIELDS)
            and report['telemetryFlushed'] is True and report['epochHelperJoined'] is True,
            'Go-node-stop-all-original-owners-retired')
    return {'reaped': True, 'clean': True, 'zeroOwners': {name: 0 for name in ZERO_FIELDS},
            'telemetryFlushed': True, 'epochHelperJoined': True}


def interrupted(row):
    require(row['processReaped'] is True and row['exitCode'] in (4, 5) and row['decoded'] is None
            and type(row['response']['outcomeKnown']) is bool, 'Go-node-stop-no-fake-success')
    response = row['response']
    code = response['error']['code']
    require(code in {'cancelled', 'deadline-exceeded', 'guest-trap', 'guest-runtime-error', 'rpc-failed', 'unavailable'},
            'Go-node-stop-closed-terminal-outcome')
    return {'exitCode': row['exitCode'], 'outcomeKnown': response['outcomeKnown'], 'errorCode': code,
            'physicalRetirementSource': 'actual-node-shutdown-report',
            'cancellationAcknowledgementInferred': False}

"""Require real native timer admission plus original live owners before SIGTERM.

The observer is a closed, default-off source hook. Audit dispatch/completion,
elapsed time and a live Store alone cannot substitute for its success points.
"""
from __future__ import annotations

import time

from tools import go_node_stop_probe as oracle
from tools import go_node_stop_timer_observer as observer
from tools.phase2_operator_process import require
from tools.rust_capsule_project import write_json


def capture(stderr):
    require(type(stderr) is bytes and len(stderr) <= observer.MAXIMUM_STDERR,
            'Go-node-stop-positive-native-source-bound')
    # A live pipe read may split one fixed record between writes. Retain the
    # complete prefix and refuse readiness until that same tail is complete;
    # do not treat an in-flight fragment as a lost/invalid completed record.
    partial = False
    if stderr and not stderr.endswith(b'\n'):
        tail = stderr.rsplit(b'\n', 1)[-1]
        if tail.startswith(observer.PREFIX) or observer.PREFIX.startswith(tail):
            require(len(tail) <= 128, 'Go-node-stop-positive-native-record-bound')
            stderr = stderr[:-len(tail)]
            partial = True
    return {**observer.observe(stderr), 'partialRecord': partial}


def barrier(inventory, stderr, activation, mode, *, provider_usage):
    require(mode in ('pending', 'drain') and activation == 'node-stop-' + mode,
            'Go-node-stop-positive-exact-public-activation')
    native = capture(stderr)
    require(native['status'] in ('not-observed', 'observed'),
            'Go-node-stop-positive-incomplete-native-observer')
    records = native['records']
    require([row['sequence'] for row in records] == list(range(1, len(records) + 1)),
            'Go-node-stop-positive-lost-native-record')
    require(all(row['mode'] == mode for row in records),
            'Go-node-stop-positive-foreign-mode')
    if native['partialRecord']:
        return None
    starts = [row for row in records if row['event'] == 'start-accepted']
    entered = [row for row in records if row['event'] == 'next-entered']
    closed = [row for row in records if row['event'] == 'root-close']
    minimum = 3 if mode == 'pending' else 2
    # The immutable ordinary fixture has one short initializer timer, followed
    # by two pending body timers or one draining body timer. A current successful
    # begin_wait must observe those original timer owners still charged.
    if len(starts) < minimum or len(entered) < minimum:
        return None
    current = entered[-1]
    if (current['sequence'] <= starts[-1]['sequence'] or current['tasks'] < 2
            or current['waits'] < 1 or current['timers'] != minimum - 1):
        return None
    if mode == 'drain' and len(closed) != 1:
        return None
    require(mode != 'pending' or not closed,
            'Go-node-stop-positive-pending-root-already-closed')
    topology = inventory['topology']
    require(topology['available'] is True and topology['complete'] is True,
            'Go-node-stop-complete-topology')
    rows = {row['name']: row for row in topology['entries']}
    require(len(rows) == len(topology['entries']) and all(name in rows for name in oracle.LIVE_ROWS),
            'Go-node-stop-physical-owner-observation')
    if any(oracle.integer(rows[name]['activeCount']) != 1 for name in oracle.LIVE_ROWS):
        return None
    require(oracle.integer(inventory['queueDepth']) == 0, 'Go-node-stop-no-hidden-root-queue')
    tenant, node = provider_usage['tenantUsage'], provider_usage['nodeUsage']
    require(tenant['scope'] == 'tenant' and node['scope'] == 'node',
            'Go-node-stop-provider-usage-scope')
    sessions, calls, node_calls = (oracle.integer(tenant['counters']['sessions']),
        oracle.integer(tenant['counters']['calls']), oracle.integer(node['counters']['broker_calls']))
    if min(sessions, calls, node_calls) == 0:
        return None
    return {'mode': mode, 'activation': activation,
            'livePhysicalRows': {name: 1 for name in oracle.LIVE_ROWS},
            'acceptedTimerStarts': len(starts), 'enteredTimerWaits': len(entered),
            'rootCloseObserved': bool(closed), 'lastEnteredTimerOwners': dict(current),
            'readinessSource': 'closed-native-success-points-and-current-original-owners',
            'auditCompletionUsedAsTimerSuccess': False,
            'retainedProviderUsage': {'tenantSessions': sessions, 'tenantCalls': calls, 'nodeCalls': node_calls},
            'actualNodeSignalSent': False}


def wait_live(client, node, pending, mode):
    original = client.deadline
    client.deadline = min(original, time.monotonic() + 10)
    try:
        for attempt in range(16):
            require(time.monotonic() < client.deadline, 'Go-node-stop-live-barrier-deadline')
            require(not pending.owner.exited(), 'Go-node-stop-guest-completed-before-signal')
            node.drain()
            inventory = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']
            providers = client.call('capability', 'list', '--deployment', 'my-greeting', '--include-node-usage')['data']
            require(providers['nextPageToken'] is None, 'Go-node-stop-provider-page-bound')
            node.drain()
            stderr = bytes(node.buffers[1])
            observed = barrier(inventory, stderr, pending.authoring_activation, mode, provider_usage=providers)
            native = capture(stderr)
            write_json(client.evidence / ('positive-timer-' + str(attempt + 1) + '.json'),
                       {'attempt': attempt + 1, 'timerObserver': native, 'barrier': observed})
            require(not pending.owner.exited(), 'Go-node-stop-guest-completed-before-signal')
            require(time.monotonic() < client.deadline, 'Go-node-stop-live-barrier-deadline')
            if observed is not None:
                return {'observation': observed, 'inventory': inventory, 'providerUsage': providers,
                        'timerObserver': native, 'attempts': attempt + 1}
            time.sleep(0.01)
        raise RuntimeError('Go-node-stop-live-barrier-attempts')
    finally:
        client.deadline = original

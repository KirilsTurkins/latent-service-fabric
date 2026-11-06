"""Run one signed combined-client witness using existing peer and owner APIs.

The caller must already have built, authenticated, signed, installed and
granted the actual combined component. This code supplies none of those steps.
"""
from pathlib import Path
import time

from tools.phase2_operator_process import WorkflowError, require, write_json
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import finish_call, sample, selected_revision, start_call
from tools.rust_thread_http_sibling_gate import decision
from tools.rust_wasi_http_runtime_node import PHYSICAL, unsigned, usage

EXPECTED = ('thread-http:fresh:waki:200:domain:7:caf\u00e9:first|\u03bb:'
            ':fresh:golem:repeat:200:domain:7:caf\u00e9:first|\u03bb:')


def current(observation, offset):
    require(type(offset) is int and offset >= 0, 'rust-thread-http-peer-offset')
    rows = [row for row in observation['requests'] if row['request'] > offset]
    events = [row for row in observation['events'] if row.get('request', 0) > offset]
    return {**observation, 'requests': rows, 'events': events}


def active_owner(client, probe, target):
    physical = sample(client, probe, 'rust-thread-http-pending', 1, active=True)
    topology = physical['inventory']['topology']
    rows = {row['name']: row for row in topology['entries']}
    require(topology['available'] is True and topology['complete'] is True
            and len(rows) == len(topology['entries'])
            and all(name in rows and unsigned(rows[name]['activeCount']) == 1 for name in PHYSICAL),
            'rust-thread-http-five-physical-owners')
    counters = usage(client, target)
    tenant = counters['tenantUsage']
    require(tenant['scope'] == 'tenant' and tenant['unavailable'] == []
            and all(unsigned(tenant['counters'][name]) >= 1 for name in ('calls', 'sessions'))
            and all(unsigned(counters['nodeUsage']['counters'][name]) >= 1
                    for name in ('broker_calls', 'pool_active_connections', 'pool_running_requests')),
            'rust-thread-http-real-pending-provider-work')
    return {'physical': physical, 'providerUsage': counters}


def decision_with_failure_evidence(observation, gates, output: Path, *, body_released):
    """Retain only the bounded controlled-peer observation if the gate refuses."""
    try:
        return decision(observation, gates, body_released=body_released)
    except WorkflowError:
        try:
            write_json(output / 'rust-thread-http-peer-refusal.json',
                       {'observation': observation, 'bodyReleased': body_released})
        except (OSError, TypeError, ValueError, WorkflowError):
            # A recording failure must not replace the original refusal.
            pass
        raise



def retain_refused_call(client, node, peer, process, output: Path, deadline):
    """Observe the existing call after a refusal without releasing gates or retrying.

    The original guest deadline remains authoritative. Only a bounded terminal
    observation is attempted; its failure cannot replace the causal refusal.
    """
    try:
        deadline = min(deadline, client.deadline, time.monotonic() + 6)
        while not process.owner.exited():
            require(time.monotonic() < deadline, 'rust-thread-http-refusal-observation-deadline')
            process.drain()
            node.drain()
            peer.poll(.005)
        row = finish_call(client, process)
        write_json(output / 'rust-thread-http-terminal.json', row)
    except (OSError, TypeError, ValueError, WorkflowError):
        pass


def invoke(client, node, target, peer, probe, output: Path, component_digest: str):
    budget = target['budget']
    require(budget['outboundRequests'] == 8 and budget['memoryBytes'] == 16_777_216
            and budget['cpuFuel'] == 1_000_000_000 and budget['wallTimeLimitMillis'] == 5000,
            'rust-thread-http-original-budget')
    require(not peer.gates() and type(component_digest) is str
            and component_digest.startswith('sha256:'), 'rust-thread-http-clean-peer')
    selected = selected_revision(client, target)
    require(selected['releaseDigest'] == component_digest, 'rust-thread-http-exact-signed-component')
    before = peer.observation()
    offset = before['acceptedConnections']
    origin = peer.origin()
    endpoint = f"{origin['scheme']}://{origin['host']}:{origin['port']}"
    process = start_call(client, target, 'greeting', 'greet', ['thread-http|' + endpoint],
                         'rust-thread-http-sibling')
    body_released = original_released = False
    pending = causal = None
    try:
        deadline = min(client.deadline, time.monotonic() + 125)
        while not process.owner.exited():
            require(time.monotonic() < deadline, 'rust-thread-http-owner-deadline')
            process.drain()
            node.drain()
            peer.poll(.005)
            observed = current(peer.observation(), offset)
            gates = [gate for gate in peer.gates() if gate.request > offset]
            if not original_released:
                step = decision_with_failure_evidence(observed, gates, output, body_released=body_released)
                if step is not None and step['action'] == 'release-sibling-body':
                    require(not body_released, 'rust-thread-http-duplicate-body-release')
                    pending = {'peer': observed, 'owner': active_owner(client, probe, target)}
                    write_json(output / 'rust-thread-http-pending.json', pending)
                    peer.release(step['gate'])
                    body_released = True
                elif step is not None and step['action'] == 'release-original-headers':
                    require(body_released and pending is not None,
                            'rust-thread-http-sibling-without-pending-owner')
                    causal = {key: value for key, value in step.items() if key != 'gate'}
                    causal['peer'] = observed
                    causal['owner'] = active_owner(client, probe, target)
                    write_json(output / 'rust-thread-http-sibling-before-release.json', causal)
                    peer.release(step['gate'])
                    original_released = True
        row = finish_call(client, process)
        write_json(output / 'rust-thread-http-terminal.json', row)
    except WorkflowError:
        retain_refused_call(client, node, peer, process, output, deadline)
        raise
    finally:
        process.close()
    require(body_released and original_released and pending is not None and causal is not None,
            'rust-thread-http-positive-sibling-order-missing')
    require(row['processReaped'] is True and row['exitCode'] == 0
            and row['response']['outcomeKnown'] is True and row['response']['requestDispatched'] is True
            and row['response']['data']['resolvedRevision'] == selected
            and row['decoded'] == [{'ok': EXPECTED}], 'rust-thread-http-exact-ordinary-client-result')
    consumed = row['response']['data']['consumption']
    require(unsigned(consumed['outboundRequests']) == 4
            and 0 < unsigned(consumed['cpuFuel']) <= budget['cpuFuel']
            and 0 < unsigned(consumed['peakMemoryBytes']) <= budget['memoryBytes'],
            'rust-thread-http-original-budget-consumption')
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0:
            break
    require(peer.observation()['openConnections'] == 0 and not peer.gates(),
            'rust-thread-http-peer-not-retired')
    retired = sample(client, probe, 'rust-thread-http-retired', 1)
    counters = usage(client, target)
    require(all(unsigned(counters['nodeUsage']['counters'][name]) == 0 for name in ACTIVE_COUNTERS),
            'rust-thread-http-provider-not-retired')
    result = {'status': 'passed', 'component': component_digest, 'selectedRevision': selected,
              'invocation': row, 'pending': pending, 'siblingBeforeOriginalRelease': causal,
              'retired': retired, 'providerUsage': counters, 'peer': current(peer.observation(), offset),
              'independentPools': 2, 'applicationYieldInserted': False}
    write_json(output / 'rust-thread-http-sibling.json', result)
    return result

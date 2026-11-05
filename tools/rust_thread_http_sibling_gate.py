"""Finite peer-side gate decisions for the actual Rust HTTP sibling witness.

This observes only the existing controlled peer. It does not manufacture an
invocation result, grant authority, run an executor or establish qualification.
The caller owns the real node, pending invocation, deadlines and retirement.
"""
from tools.phase2_operator_process import require
from tools.standard_http.peer import Gate


def decision(observation, gates, *, body_released):
    require(type(observation) is dict and observation.get('failure') is None
            and type(observation.get('generation')) is str
            and type(observation.get('requests')) is list
            and type(observation.get('events')) is list
            and type(body_released) is bool,
            'rust-thread-http-peer-observation')
    rows, events = observation['requests'], observation['events']
    require(len(rows) <= 4 and len(events) <= 512 and len(gates) <= 2,
            'rust-thread-http-peer-bounds')
    require(all(type(row) is dict and type(row.get('request')) is int
                and row.get('role') == 'primary'
                and (row.get('vector') in {'pending-headers', 'partial-body', 'domain-json'}
                     or row.get('vector') is None and row.get('state') == 'accepted')
                for row in rows), 'rust-thread-http-peer-request-shape')
    identities = [row['request'] for row in rows]
    require(len(identities) == len(set(identities)), 'rust-thread-http-peer-request-duplicate')
    require(all(type(event) is dict and type(event.get('sequence')) is int and event['sequence'] > 0
                for event in events)
            and all(left['sequence'] < right['sequence'] for left, right in zip(events, events[1:])),
            'rust-thread-http-peer-event-order')
    require(all(type(gate) is Gate and gate.generation == observation['generation'] and gate.request in identities
                for gate in gates), 'rust-thread-http-peer-stale-gate')

    def row(vector):
        selected = [item for item in rows if item.get('vector') == vector]
        require(len(selected) <= 1, 'rust-thread-http-peer-ambiguous-gate')
        return selected[0] if selected else None

    def event(kind, request, *, phase=None):
        selected = [item['sequence'] for item in events
                    if item.get('kind') == kind and item.get('request') == request
                    and (phase is None or item.get('phase') == phase)]
        require(len(selected) <= 1, 'rust-thread-http-peer-ambiguous-event')
        return selected[0] if selected else None

    held, partial = row('pending-headers'), row('partial-body')
    json_rows = [item for item in rows if item.get('vector') == 'domain-json']
    require(len(json_rows) <= 2, 'rust-thread-http-peer-extra-sibling')
    if held is None or partial is None:
        require(not body_released, 'rust-thread-http-peer-missing-release-preimage')
        return None
    hold_gate = next((gate for gate in gates if gate.request == held['request']), None)
    body_gate = next((gate for gate in gates if gate.request == partial['request']), None)
    hold_pending = event('gate-pending', held['request'], phase='headers')
    body_pending = event('gate-pending', partial['request'], phase='body')
    require(hold_gate is not None and hold_gate.phase == 'headers' and hold_pending is not None
            and held.get('responseBytesWritten') == 0
            and event('gate-released', held['request'], phase='headers') is None,
            'rust-thread-http-original-http-not-held')
    if not body_released:
        if body_gate is None or body_pending is None:
            return None
        require(body_gate.phase == 'body' and partial.get('responseBytesWritten', 0) > 0
                and event('gate-released', partial['request'], phase='body') is None,
                'rust-thread-http-sibling-body-not-held')
        return {'action': 'release-sibling-body', 'gate': body_gate}

    body_release = event('gate-released', partial['request'], phase='body')
    require(body_gate is None and body_pending is not None and body_release is not None
            and body_pending < body_release,
            'rust-thread-http-sibling-body-release-missing')
    if len(json_rows) < 2:
        return None
    first, second = json_rows
    first_done = event('response-write-complete', first['request'])
    second_start = event('request-started', second['request'])
    if first_done is None or second_start is None:
        return None
    require(body_release < first_done < second_start and hold_pending < second_start,
            'rust-thread-http-sibling-not-after-original-pending')
    # The second ordinary request can only be issued after the unchanged
    # developer crate receives, parses and validates the first JSON response.
    return {'action': 'release-original-headers', 'gate': hold_gate,
            'pendingSequence': hold_pending, 'firstResponseSequence': first_done,
            'secondRequestSequence': second_start}

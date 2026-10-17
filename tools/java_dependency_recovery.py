"""Finite failure and fresh-invocation controls for actual captured Java code."""
from __future__ import annotations

import time

from tools.phase2_operator_process import require
from tools.qualify_java_annotation_processors import observe_idle
from tools.rust_capsule_node import assert_value, call, finish_call, start_call


def failed(observed, code, detail=None):
    response = observed['response']
    require(observed['exitCode'] == 4 and observed['processReaped']
            and response['outcomeKnown'] and response['category'] == 'platform-failure'
            and response['error']['code'] == code
            and response['data']['terminalState'] == code.replace('-', '_'), 'java-library-failure-result')
    if detail is not None:
        require(any(row['kind'] == detail for row in response['error']['details']),
                'java-library-failure-dimension')


def recover(client, target, evidence):
    records = []

    def next_invocation(name, observed):
        observe_idle(client, evidence, name + '-retired')
        fresh = call(client, target, 'greeting', 'greet', ['SDK'], name + '-fresh')
        assert_value(client, fresh, [{'ok': '42/53444b/KDS'}], 0)
        require(fresh['processReaped'], 'java-library-recovery-process-owner')
        observe_idle(client, evidence, name + '-fresh-retired')
        records.append({'case': name, 'failure': observed, 'freshInvocation': fresh})

    heap = call(client, target, 'greeting', 'greet', ['heap'], 'library-java-heap-limit')
    failed(heap, 'guest-trap', 'activation.guest-trap-kind')
    require(int(heap['response']['data']['consumption']['peakMemoryBytes']) <= target['budget']['memoryBytes'],
            'java-library-heap-exceeded-wasm-owner')
    next_invocation('uncaught-java-heap-exhaustion', heap)

    exception = call(client, target, 'greeting', 'greet', ['throw'], 'library-uncaught-exception')
    failed(exception, 'guest-trap', 'activation.guest-trap-kind')
    next_invocation('uncaught-exception', exception)

    memory = call(client, target, 'greeting', 'greet', ['SDK'], 'library-memory-limit', memory=65536)
    failed(memory, 'resource-exhausted')
    next_invocation('wasm-memory-limit', memory)

    limited = {**target, 'budget': {**target['budget'], 'cpuFuel': 10_000_000}}
    require(limited['budget']['cpuFuel'] <= target['budget']['cpuFuel'], 'java-library-fuel-elevation')
    fuel = call(client, limited, 'greeting', 'greet', ['spin'], 'library-fuel-limit')
    failed(fuel, 'resource-exhausted')
    require(int(fuel['response']['data']['consumption']['cpuFuel']) == limited['budget']['cpuFuel'],
            'java-library-fuel-limit-not-consumed')
    next_invocation('fuel-exhaustion', fuel)

    activation = 'library-observed-cancellation'
    process = start_call(client, target, 'greeting', 'greet', ['spin'], activation)
    observations = []
    try:
        deadline = min(client.deadline, time.monotonic() + 20)
        for _attempt in range(128):
            state = client.call('activation', 'get', activation, codes=(0, 6))
            observations.append(state)
            if state['category'] == 'success':
                data = state['data']
                require(state['outcomeKnown'] and data['activationId'] == activation,
                        'java-library-cancellation-identity')
                require(data.get('terminalState') is None, 'java-library-terminal-before-cancel')
                if data.get('phase') == 'running':
                    break
            require(time.monotonic() < deadline, 'java-library-cancellation-running-deadline')
            time.sleep(.025)
        else:
            raise RuntimeError('java-library-cancellation-read-count')
        cancelled = client.call('activation', 'cancel', activation, '--reason', 'Captured Java library cancellation')
        require(cancelled['outcomeKnown'] and cancelled['data']['activationId'] == activation
                and cancelled['data']['disposition'] == 'accepted', 'java-library-cancel-unconfirmed-no-replay')
        result = finish_call(client, process)
        failed(result, 'cancelled')
        require(result['response']['data']['terminalState'] == 'cancelled', 'java-library-cancellation-terminal')
    finally:
        process.close()
    next_invocation('observed-cancellation', {'runningObservations': observations, 'cancelCalls': 1,
                                           'cancelReceipt': cancelled, 'invocation': result})
    return records

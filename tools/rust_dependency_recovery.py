"""Finite actual captured Rust panic/drop/resource and fresh-invocation controls."""
from __future__ import annotations

import time

from tools.phase2_operator_process import require
from tools.rust_capsule_node import assert_value, call, finish_call, sample, start_call


def failed(observed: dict, code: str, maximum_memory: int) -> None:
    response = observed['response']
    require(observed['exitCode'] == 4 and observed['processReaped']
            and response['outcomeKnown'] and response['category'] == 'platform-failure'
            and response['error']['code'] == code
            and response['data']['terminalState'] == code.replace('-', '_'),
            'rust-library-failure-result')
    require(int(response['data']['consumption']['peakMemoryBytes']) <= maximum_memory,
            'rust-library-guest-memory-bound')


def recover(client, target: dict, probe, evidence: dict, population: int) -> list[dict]:
    records = []

    def fresh(name: str, observed: dict) -> None:
        evidence['samples'].append(sample(client, probe, name + '-retired', population))
        invoked = call(client, target, 'greeting', 'greet', ['SDK'], name + '-fresh')
        # The unchanged external crate also checks normal Drop, included UTF-8
        # and binary resource bytes, and zero prior activation-local calls.
        assert_value(client, invoked, [{'ok': 'Hello, SDK!'}])
        require(invoked['processReaped'], 'rust-library-recovery-process-owner')
        evidence['samples'].append(sample(client, probe, name + '-fresh-retired', population))
        records.append({'case': name, 'failure': observed, 'freshInvocation': invoked})

    for mode, code in (('panic', 'guest-trap'), ('memory', 'resource-exhausted')):
        observed = call(client, target, 'greeting', 'greet', [mode], 'rust-library-' + mode)
        failed(observed, code, target['budget']['memoryBytes'])
        fresh('rust-library-' + mode, observed)

    limited = {**target, 'budget': {**target['budget'], 'cpuFuel': 10_000_000}}
    require(limited['budget']['cpuFuel'] <= target['budget']['cpuFuel'], 'rust-library-fuel-elevation')
    fuel = call(client, limited, 'greeting', 'greet', ['fuel'], 'rust-library-fuel-limit')
    failed(fuel, 'resource-exhausted', limited['budget']['memoryBytes'])
    require(int(fuel['response']['data']['consumption']['cpuFuel']) == limited['budget']['cpuFuel'],
            'rust-library-fuel-limit-not-consumed')
    fresh('rust-library-fuel', fuel)

    activation = 'rust-library-observed-cancellation'
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
                        'rust-library-cancellation-identity')
                require(data.get('terminalState') is None, 'rust-library-terminal-before-cancel')
                if data.get('phase') == 'running':
                    break
            require(time.monotonic() < deadline, 'rust-library-cancellation-running-deadline')
            time.sleep(.025)
        else:
            raise RuntimeError('rust-library-cancellation-read-count')
        cancelled = client.call('activation', 'cancel', activation, '--reason', 'Captured Rust library cancellation')
        require(cancelled['outcomeKnown'] and cancelled['data']['activationId'] == activation
                and cancelled['data']['disposition'] == 'accepted', 'rust-library-cancel-unconfirmed-no-replay')
        observed = finish_call(client, process)
        failed(observed, 'cancelled', target['budget']['memoryBytes'])
    finally:
        process.close()
    fresh('rust-library-cancel', {'runningObservations': observations, 'cancelCalls': 1,
        'cancelReceipt': cancelled, 'invocation': observed})
    return records

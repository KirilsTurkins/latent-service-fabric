"""Finite actual captured .NET exception/finally/resource and fresh-invocation controls."""
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
            'dotnet-library-failure-result')
    require(0 <= int(response['data']['consumption']['peakMemoryBytes']) <= maximum_memory,
            'dotnet-library-guest-memory-bound')


def recover(client, target: dict, probe, evidence: dict, population: int) -> list[dict]:
    records = []

    def fresh(name: str, observed: dict) -> None:
        evidence['samples'].append(sample(client, probe, name + '-retired', population))
        invoked = call(client, target, 'greeting', 'greet', ['SDK'], name + '-fresh')
        # The unchanged external module also checks normal catch/finally, embedded UTF-8
        # and binary resource bytes, and zero prior activation-local calls.
        assert_value(client, invoked, [{'ok': 'Hello, SDK!'}])
        require(invoked['processReaped'], 'dotnet-library-recovery-process-owner')
        evidence['samples'].append(sample(client, probe, name + '-fresh-retired', population))
        records.append({'case': name, 'failure': observed, 'freshInvocation': invoked})

    for mode, code in (('exception', 'guest-trap'), ('memory', 'resource-exhausted')):
        observed = call(client, target, 'greeting', 'greet', [mode], 'dotnet-library-' + mode)
        failed(observed, code, target['budget']['memoryBytes'])
        fresh('dotnet-library-' + mode, observed)

    # NativeAOT startup itself consumes fuel: use the immediately preceding actual
    # successful calls, keeping the fault allowance strictly below the original limit.
    startup_fuel = max(int(row['freshInvocation']['response']['data']['consumption']['cpuFuel'])
        for row in records)
    fault_fuel = max(10_000_000, startup_fuel * 2)
    require(0 < startup_fuel < fault_fuel < target['budget']['cpuFuel'],
            'dotnet-library-fuel-insufficient-startup-margin')
    limited = {**target, 'budget': {**target['budget'], 'cpuFuel': fault_fuel}}
    fuel = call(client, limited, 'greeting', 'greet', ['fuel'], 'dotnet-library-fuel-limit')
    failed(fuel, 'resource-exhausted', limited['budget']['memoryBytes'])
    require(int(fuel['response']['data']['consumption']['cpuFuel']) == limited['budget']['cpuFuel'],
            'dotnet-library-fuel-limit-not-consumed')
    fresh('dotnet-library-fuel', fuel)
    records[-1].update(startupBaselineFuel=startup_fuel, faultFuelBudget=fault_fuel,
        originalFuelBudget=target['budget']['cpuFuel'])

    activation = 'dotnet-library-observed-cancellation'
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
                        'dotnet-library-cancellation-identity')
                require(data.get('terminalState') is None, 'dotnet-library-terminal-before-cancel')
                if data.get('phase') == 'running':
                    break
            require(time.monotonic() < deadline, 'dotnet-library-cancellation-running-deadline')
            time.sleep(.025)
        else:
            raise RuntimeError('dotnet-library-cancellation-read-count')
        cancelled = client.call('activation', 'cancel', activation, '--reason', 'Captured .NET library cancellation')
        require(cancelled['outcomeKnown'] and cancelled['data']['activationId'] == activation
                and cancelled['data']['disposition'] == 'accepted', 'dotnet-library-cancel-unconfirmed-no-replay')
        observed = finish_call(client, process)
        failed(observed, 'cancelled', target['budget']['memoryBytes'])
    finally:
        process.close()
    fresh('dotnet-library-cancel', {'runningObservations': observations, 'cancelCalls': 1,
        'cancelReceipt': cancelled, 'invocation': observed})
    return records

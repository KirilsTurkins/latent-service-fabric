"""Explicit log admission and synchronous ordinary Console lifecycle controls."""
from tools.dotnet_guest.runtime import CLOCK, LOG
from tools.dotnet_standard_console_fixture import CASES, EXPECTED, PHASES, PHASE_EXPECTED
from tools.phase2_operator_process import require, write_json


def configure(settings):
    providers = settings['providers']
    require('log' not in providers and len(providers['bindings']) < 16,
            'dotnet-console-provider-already-present-or-binding-bound')
    providers['log'] = {'identity': {'id': 'log', 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1}}
    providers['bindings'].append({'name': 'log-greeting', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'runtime-host',
        'contract': LOG, 'providerBinding': 'log-installed'})


def grant(client, node, fixture, targets, publications, result):
    from tools.rust_capsule_node import call, deploy, provider_idle
    target = targets['greeting']
    require(CLOCK in {row['capability'] for row in target['grants']}
            and LOG not in {row['capability'] for row in target['grants']},
            'dotnet-console-preserve-existing-runtime-grants')
    denied = []
    for ordinal, name in enumerate(('console:initializer', 'Ada')):
        row = call(client, target, 'greeting', 'greet', [name], 'dotnet-console-denied-' + str(ordinal))
        result['invocations'].append(row)
        response = row['response']; data = response['data']; consumption = data['consumption']
        require(row['exitCode'] == 4 and row['processReaped'] and response['outcomeKnown'] is True
                and response['error']['code'] == 'permission-denied' and data['terminalState'] == 'rejected'
                and int(consumption['cpuFuel']) == int(consumption['peakMemoryBytes']) == 0
                and consumption['effectCount'] == 0, 'dotnet-console-missing-grant-before-guest')
        denied.append(row)
        result['providerIdle'].append(provider_idle(client))
    installed = [row for row in node.startup_record['providers'] if row['id'] == 'log']
    require(len(installed) == 1 and installed[0]['capability'] == LOG
            and installed[0]['profile'] == 'activation-log-v1' and installed[0]['tenant'] == 'examples'
            and installed[0]['service'] == 'runtime-host' and installed[0]['configurationEpoch'] == '1',
            'dotnet-console-provider-identity')
    descriptor = installed[0]
    binding = client.directory / 'dotnet-console-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': LOG,
        'providerProfile': descriptor['profile'], 'configurationDigest': descriptor['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['write']}})
    client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'log-installed', '--file', binding,
                '--operation-id', 'install-dotnet-console', '--expected-generation', '0')
    specification = {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'console', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']], 'capability': LOG,
        'operations': ['write'], 'resources': {'kind': 'log', 'levels': ['info', 'error']},
        'ceiling': {'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000}}]}
    policy = client.directory / 'dotnet-console-policy.json'; write_json(policy, specification)
    client.call('policy', 'apply', '--id', 'dotnet-console', '--file', policy,
                '--operation-id', 'grant-dotnet-console', '--expected-generation', '0')
    selected = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[*target['grants'], {'capability': LOG, 'policy': 'dotnet-console'}])
    targets['greeting'] = selected
    result['dotnetStandardConsoleAuthority'] = {'denied': denied, 'provider': descriptor,
        'policy': specification, 'preservedGrants': target['grants']}


def probe(client, target, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    def completed(row, *, logged=True):
        require(row['processReaped'], 'dotnet-console-invocation-process')
        consumption = row['response']['data']['consumption']
        actual_log = int(consumption['logBytes'])
        require((0 < actual_log <= target['budget']['logBytes'] if logged else actual_log == 0)
                and int(consumption['outboundRequests']) == 0
                and int(consumption['peakMemoryBytes']) <= target['budget']['memoryBytes'],
                'dotnet-console-charged-log-and-no-network')
        return consumption
    rows, recovery, baseline = [], [], None
    phases = []
    for mode in PHASES:
        row = call(client, target, 'greeting', 'greet', ['console-phase:' + mode], 'dotnet-console-phase-' + mode)
        result['invocations'].append(row)
        # A caught closed exception label still fails this original positive
        # expectation. Diagnostic observations never become acceptance skips.
        assert_value(client, row, [{'ok': PHASE_EXPECTED[mode]}])
        completed(row, logged=mode == 'write')
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'dotnet-console-phase-' + mode + '-retired', population))
        phases.append({'case': mode, 'invocation': row})
    result['dotnetStandardConsolePhases'] = phases
    for ordinal, mode in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['console:' + mode], 'dotnet-console-' + str(ordinal))
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': EXPECTED[mode]}])
        consumption = completed(row)
        if mode == 'initializer': baseline = int(consumption['cpuFuel'])
        rows.append({'case': mode, 'activation': row['activation'], 'decoded': row['decoded'],
                     'consumption': consumption})
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'dotnet-console-' + mode + '-retired', population))
    require(type(baseline) is int and 0 < baseline * 2 < target['budget']['cpuFuel'],
            'dotnet-console-startup-fuel-margin')
    for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
        bounded = target if mode == 'trap' else {
            **target, 'budget': {**target['budget'], 'cpuFuel': baseline * 2}}
        failed = call(client, bounded, 'greeting', 'greet', ['console:' + mode], 'dotnet-console-' + mode)
        result['invocations'].append(failed)
        require(failed['exitCode'] == 4 and failed['processReaped'] and failed['response']['outcomeKnown']
                and failed['response']['error']['code'] == code
                and failed['response']['data']['terminalState'] == code.replace('-', '_'),
                'dotnet-console-failure-shape')
        consumed = failed['response']['data']['consumption']
        require(int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and 0 < int(consumed['logBytes']) <= target['budget']['logBytes'], 'dotnet-console-failure-bounds')
        if mode == 'fuel':
            require(int(consumed['cpuFuel']) == bounded['budget']['cpuFuel'], 'dotnet-console-original-fuel-bound')
        result['samples'].append(sample(client, accounting, 'dotnet-console-' + mode + '-retired', population))
        fresh = call(client, target, 'greeting', 'greet', ['console:initializer'], 'dotnet-console-' + mode + '-fresh')
        result['invocations'].append(fresh)
        assert_value(client, fresh, [{'ok': EXPECTED['initializer']}])
        completed(fresh)
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'dotnet-console-' + mode + '-fresh-retired', population))
        recovery.append({'case': mode, 'failure': failed, 'freshInvocation': fresh,
                         'startupBaselineFuel': baseline, 'faultFuelBudget': bounded['budget']['cpuFuel']})
    result['dotnetStandardConsoleCases'] = rows
    result['dotnetStandardConsoleRecovery'] = recovery

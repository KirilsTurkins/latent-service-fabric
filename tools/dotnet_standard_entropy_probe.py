"""Explicit standard RNG authority, typed denial and fresh activation receipts."""
from tools.dotnet_guest import entropy_grants as noncrypto
from tools.dotnet_guest.runtime import CLOCK, RANDOM
from tools.dotnet_standard_entropy_fixture import CASES, expected
from tools.phase2_operator_process import require, write_json


def grant(client, node, fixture, targets, publications, result):
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle
    target = targets['greeting']
    require({row['capability'] for row in target['grants']} == {CLOCK, RANDOM},
            'dotnet-secure-entropy-existing-authority')
    # The existing bytes-only hash-seed policy cannot authorize secure u64 draws.
    denied = call(client, target, 'greeting', 'greet', ['entropy:denied'], 'dotnet-entropy-u64-denied')
    assert_value(client, denied, [{'ok': expected('denied')}])
    require(denied['processReaped'] and denied['response']['data']['consumption']['effectCount'] == 0,
            'dotnet-secure-entropy-denial-cleanup')
    result['invocations'].append(denied)
    result['providerIdle'].append(provider_idle(client))
    installed = [row for row in node.startup_record['providers'] if row['id'] == noncrypto.PROVIDER]
    require(len(installed) == 1 and installed[0]['profile'] == noncrypto.PROFILE,
            'dotnet-secure-entropy-provider-identity')
    descriptor = installed[0]
    binding = client.directory / 'secure-entropy-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': RANDOM,
        'providerProfile': noncrypto.PROFILE, 'configurationDigest': descriptor['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['bytes', 'u64-value']}})
    client.call('policy', '--kind', 'provider-binding', 'apply', '--id', noncrypto.BINDING,
        '--file', binding, '--operation-id', 'secure-entropy-binding', '--expected-generation', '1')
    policy = {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'explicit-standard-entropy', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']],
        'capability': RANDOM, 'operations': ['bytes', 'u64-value'], 'resources': {'kind': 'random'},
        'ceiling': {'operations': 4096, 'inputBytes': 8, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]}
    path = client.directory / 'secure-entropy-policy.json'
    write_json(path, policy)
    client.call('policy', 'apply', '--id', 'secure-entropy-allow', '--file', path,
        '--operation-id', 'secure-entropy-policy', '--expected-generation', '0')
    grants = [row for row in target['grants'] if row['capability'] != RANDOM]
    grants.append({'capability': RANDOM, 'policy': 'secure-entropy-allow'})
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=grants)
    result['dotnetStandardEntropyAuthority'] = {'operationDenied': denied, 'policy': policy,
        'requiredDeclaration': RANDOM, 'additionalProviderBindings': 0,
        'providerAggregateBytes': 65536, 'defaultLanguageProfilesChanged': False,
        'transactionalEntropySupport': False, 'fipsCertification': False}


def probe(client, target, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    rows, recovery = [], []
    def bounded(row):
        consumed = row['response']['data']['consumption']
        require(row['processReaped'] and row['response']['outcomeKnown'] is True
                and 0 < int(consumed['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumed['outboundRequests']) == int(consumed['logBytes']) == int(consumed['effectCount']) == 0,
                'dotnet-secure-entropy-consumption-or-reaping')
    def fresh(mode, label):
        row = call(client, target, 'greeting', 'greet', ['entropy:' + mode], label)
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': expected(mode)}])
        bounded(row)
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, label + '-retired', population))
        return row
    for mode in CASES:
        rows.append({'mode': mode, 'invocation': fresh(mode, 'dotnet-entropy-' + mode)})
    # A successful bounded denial also has to leave the next activation usable.
    recovery.append({'mode': 'budget', 'freshInvocation': fresh('wide', 'dotnet-entropy-budget-fresh')})
    for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
        row = call(client, target, 'greeting', 'greet', ['entropy:' + mode], 'dotnet-entropy-' + mode)
        result['invocations'].append(row)
        require(row['exitCode'] == 4 and row['response']['error']['code'] == code
                and row['response']['data']['terminalState'] == code.replace('-', '_'),
                'dotnet-secure-entropy-terminal-shape')
        bounded(row)
        if mode == 'fuel':
            require(int(row['response']['data']['consumption']['cpuFuel']) == target['budget']['cpuFuel'],
                    'dotnet-secure-entropy-original-fuel-bound')
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'dotnet-entropy-' + mode + '-retired', population))
        recovery.append({'mode': mode, 'failure': row,
                         'freshInvocation': fresh('initializer', 'dotnet-entropy-' + mode + '-fresh')})
    result['dotnetStandardEntropy'] = {'status': 'passed', 'cases': rows, 'recovery': recovery,
        'rawEntropyPayloadRetained': False, 'statisticalQualityTest': False,
        'concurrencyQualified': False, 'transactionalReplayQualified': False}

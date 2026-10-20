"""Default-off signed Rust entropy, typed refusal and fresh retirement cases."""
from tools.phase2_operator_process import require, write_json
from tools.rust_standard_entropy_fixture import CASES, expected

RANDOM = 'latent:random/random@0.1.0'
PROVIDER = 'rust-random'
ALLOW = 'rust-random-allow'
DENY = 'rust-random-zero-input'


def configure(settings):
    providers = settings['providers']
    require('random' not in providers and len(providers['bindings']) < 16,
            'rust-entropy-existing-provider-or-binding-bound')
    providers['random'] = {'identity': {'id': PROVIDER, 'tenant': 'examples',
                                     'service': 'entropy-host', 'epoch': 1}}
    providers['bindings'].append({'name': PROVIDER, 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'entropy-host',
        'contract': RANDOM, 'providerBinding': PROVIDER + '-installed'})
    # Same finite audit capacity used by the existing scalar runtime campaigns.
    settings['audit'].update(records=4096, diskBytes=67108864)


def grant(client, node, fixture, targets, publications, result):
    from tools.rust_capsule_node import call, deploy, provider_idle
    from tools.c_standard_facilities_probe import require_denied_before_guest
    target = targets['greeting']
    require(not any(row['capability'] == RANDOM for row in target['grants']), 'rust-entropy-no-implicit-grant')
    denied = []
    for argument, label in (('Ada', 'ordinary'), ('entropy:one', 'library')):
        row = call(client, target, 'greeting', 'greet', [argument], 'rust-entropy-no-grant-' + label)
        require_denied_before_guest(row)
        require(row['processReaped'], 'rust-entropy-denied-process-not-reaped')
        result['invocations'].append(row)
        result['providerIdle'].append(provider_idle(client))
        denied.append(row)
    installed = [row for row in node.startup_record['providers'] if row['id'] == PROVIDER]
    require(len(installed) == 1 and installed[0]['capability'] == RANDOM
            and installed[0]['profile'] == 'system-random-v1', 'rust-entropy-provider-identity')
    descriptor = installed[0]
    binding = client.directory / 'rust-entropy-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': RANDOM,
        'providerProfile': descriptor['profile'], 'configurationDigest': descriptor['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['u64-value']}})
    client.call('policy', '--kind', 'provider-binding', 'apply', '--id', PROVIDER + '-installed',
                '--file', binding, '--operation-id', 'rust-entropy-binding', '--expected-generation', '0')
    policies = []
    for identity, input_bytes in ((ALLOW, 8), (DENY, 0)):
        policy = {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'ordinary-entropy', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [publications['greeting']],
            'capability': RANDOM, 'operations': ['u64-value'], 'resources': {'kind': 'random'},
            'ceiling': {'operations': 4096, 'inputBytes': input_bytes, 'outputBytes': 8, 'wallTimeMillis': 5000}}]}
        path = client.directory / (identity + '.json')
        write_json(path, policy)
        client.call('policy', 'apply', '--id', identity, '--file', path,
                    '--operation-id', identity, '--expected-generation', '0')
        policies.append(policy)
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[*target['grants'], {'capability': RANDOM, 'policy': ALLOW}])
    result['rustStandardEntropyAuthority'] = {'deniedBeforeGuest': denied, 'policies': policies,
        'providerAggregateBytes': 65536, 'aggregateExhaustionClaimed': False,
        'ordinaryProfilesChanged': False, 'additionalProviderBindings': 1}


def probe(client, fixture, targets, publications, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle, sample
    target = targets['greeting']
    rows, recovery = [], []

    def observe(row, label):
        consumed = row['response']['data']['consumption']
        require(row['processReaped'] and row['response']['outcomeKnown'] is True
                and 0 < int(consumed['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumed['outboundRequests']) == int(consumed['logBytes']) == int(consumed['effectCount']) == 0,
                'rust-entropy-consumption-or-reaping')
        result['invocations'].append(row)
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, label + '-retired', population))

    def completed(mode, label):
        row = call(client, target, 'greeting', 'greet', ['entropy:' + mode], label)
        observe(row, label)
        assert_value(client, row, [{'ok': expected(mode)}])
        return row

    def failed(mode, code):
        label = 'rust-entropy-' + mode
        row = call(client, target, 'greeting', 'greet', ['entropy:' + mode], label)
        observe(row, label)
        require(row['exitCode'] == 4 and row['response']['error']['code'] == code
                and row['response']['data']['terminalState'] == code.replace('-', '_'),
                'rust-entropy-terminal-shape')
        if mode == 'fuel':
            require(int(row['response']['data']['consumption']['cpuFuel']) == target['budget']['cpuFuel'],
                    'rust-entropy-original-fuel-bound')
        return row

    for mode in CASES:
        rows.append({'mode': mode, 'invocation': completed(mode, 'rust-entropy-' + mode)})
    allowed_grants = target['grants']
    denied_grants = [{**row, 'policy': DENY} if row['capability'] == RANDOM else row for row in allowed_grants]
    target = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
                    generation=str(target['generation']), grants=denied_grants)
    typed = completed('denied', 'rust-entropy-typed-budget-denial')
    standard = failed('std-denied', 'guest-trap')
    target = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
                    generation=str(target['generation']), grants=allowed_grants)
    recovery.append({'mode': 'policy-budget', 'typedFailure': typed, 'standardFailure': standard,
                     'freshInvocation': completed('wide', 'rust-entropy-budget-fresh')})
    for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
        row = failed(mode, code)
        recovery.append({'mode': mode, 'failure': row,
                         'freshInvocation': completed('one', 'rust-entropy-' + mode + '-fresh')})
    targets['greeting'] = target
    result['rustStandardEntropy'] = {'status': 'passed', 'cases': rows, 'recovery': recovery,
        'rawEntropyRetained': False, 'aggregateExhaustionClaimed': False,
        'transactionalReplayQualified': False, 'concurrencyQualified': False, 'fipsCertification': False}

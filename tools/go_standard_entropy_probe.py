"""Ordinary Go entropy admission and terminal/fresh-Store evidence, default off."""
from tools.dev_workflow.common import require
from tools.go_standard_entropy_fixture import CASES, expected

RANDOM = 'latent:random/random@0.1.0'
CLOCKS = {'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'}


def admission(client, fixture, targets, publications, result):
    from tools.c_standard_facilities_probe import require_denied_before_guest
    from tools.rust_capsule_node import call, deploy, provider_idle
    target = targets['greeting']
    grants = target['grants']
    require({row['capability'] for row in grants} == CLOCKS | {RANDOM}
            and len(grants) == 3, 'go-entropy-original-runtime-grants')
    restricted = [row for row in grants if row['capability'] != RANDOM]
    selected = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=restricted)
    denied = []
    for ordinal, argument in enumerate(('Ada', 'entropy:read-one')):
        row = call(client, selected, 'greeting', 'greet', [argument], 'go-entropy-no-random-' + str(ordinal))
        result['invocations'].append(row)
        require(row['processReaped'] and row['response']['data']['consumption']['effectCount'] == 0,
                'go-entropy-pre-admission-process-or-effects')
        require_denied_before_guest(row)
        result['providerIdle'].append(provider_idle(client))
        denied.append(row)
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(selected['generation']), grants=grants)
    result['goStandardEntropyAuthority'] = {'denied': denied, 'preservedGrants': grants,
        'additionalProviderBindings': 0, 'policyChanged': False}


def probe(client, target, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    rows, recovery = [], []
    def bounded(row):
        require(row['processReaped'], 'go-entropy-process-not-reaped')
        consumed = row['response']['data']['consumption']
        require(0 < int(consumed['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumed['outboundRequests']) == int(consumed['logBytes']) == 0,
                'go-entropy-original-consumption-bounds')
        return consumed
    def fresh(mode, label):
        row = call(client, target, 'greeting', 'greet', ['entropy:' + mode], label)
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': expected(mode)}])
        bounded(row)
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, label + '-retired', population))
        return row
    for mode in CASES:
        rows.append({'mode': mode, 'invocation': fresh(mode, 'go-entropy-' + mode)})
    for mode, code in (('budget', 'guest-trap'), ('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
        row = call(client, target, 'greeting', 'greet', ['entropy:' + mode], 'go-entropy-' + mode)
        result['invocations'].append(row)
        require(row['exitCode'] == 4 and row['response']['outcomeKnown'] is True
                and row['response']['error']['code'] == code
                and row['response']['data']['terminalState'] == code.replace('-', '_'), 'go-entropy-terminal-shape')
        consumed = bounded(row)
        if mode == 'fuel':
            require(int(consumed['cpuFuel']) == target['budget']['cpuFuel'], 'go-entropy-original-fuel-bound')
        result['samples'].append(sample(client, accounting, 'go-entropy-' + mode + '-retired', population))
        recovered = fresh('read-one', 'go-entropy-' + mode + '-fresh')
        recovery.append({'mode': mode, 'failure': row, 'freshInvocation': recovered})
    result['goStandardEntropy'] = {'status': 'passed', 'cases': rows, 'recovery': recovery,
        'randomPayloadRetained': False, 'statisticalQualityTest': False, 'fipsCertification': False,
        'concurrencyQualified': False, 'budgetFailure': 'original random operation/byte/wall ceiling; terminal runtime denial'}

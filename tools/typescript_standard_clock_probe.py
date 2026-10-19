"""Finite ordinary Date/performance authority and fresh-Store programme."""
from tools.phase2_operator_process import require
from tools.rust_capsule_project import write_json
from tools.typescript_standard_clock_fixture import TEXT

PROFILES = {
    'clockMonotonic': ('ts-clock-monotonic', 'latent:clock/monotonic@0.1.0', 'activation-monotonic-v1', 'now-nanos'),
    'clockWall': ('ts-clock-wall', 'latent:clock/wall@0.1.0', 'activation-wall-v1', 'now-unix-millis'),
}
UNDECLARED = ('now', 'function', 'function-args', 'construct', 'monotonic', 'origin')
SELECTED = ('entry', 'wall', 'explicit', 'monotonic', 'repeated', 'fresh')


def expected(mode):
    return 'clock:'+mode+'|'+TEXT+'|binary=00ff4180|fresh=1'


def configure(settings):
    providers = settings['providers']
    require(all(key not in providers for key in PROFILES) and len(providers['bindings']) <= 14,
            'typescript-clock-original-provider-capacity')
    for key, (identity, capability, _profile, _operation) in PROFILES.items():
        providers[key] = {'identity': {'id': identity, 'tenant': 'examples', 'service': 'clock-host', 'epoch': 1}}
        providers['bindings'].append({'name': identity+'-greeting', 'tenant': 'examples',
            'consumerService': 'examples/my-greeting', 'providerService': 'clock-host',
            'contract': capability, 'providerBinding': identity+'-installed'})


def grant(client, node, fixture, targets, publications, result):
    from tools.c_standard_facilities_probe import require_denied_before_guest
    from tools.rust_capsule_node import call, deploy, provider_idle
    original = targets['greeting']['grants']
    require(not original, 'typescript-clock-original-ungranted')
    denied = []

    def absent(label):
        row = call(client, targets['greeting'], 'greeting', 'greet', ['clock:entry'], label)
        result['invocations'].append(row)
        require_denied_before_guest(row)
        require(row['processReaped'], 'typescript-clock-denied-process')
        result['providerIdle'].append(provider_idle(client))
        denied.append(row)

    absent('ts-clock-both-missing')
    grants = []
    for _key, (identity, capability, profile, operation) in PROFILES.items():
        installed = [row for row in node.startup_record['providers'] if row['id'] == identity]
        require(len(installed) == 1 and installed[0]['capability'] == capability and installed[0]['profile'] == profile
                and installed[0]['tenant'] == 'examples' and installed[0]['service'] == 'clock-host',
                'typescript-clock-installed-source')
        descriptor = installed[0]
        binding = client.directory/(identity+'-binding.json')
        write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
            'providerProfile': profile, 'configurationDigest': descriptor['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': [operation]}})
        client.call('policy', '--kind', 'provider-binding', 'apply', '--id', identity+'-installed', '--file', binding,
            '--operation-id', 'install-'+identity, '--expected-generation', '0')
        policy = client.directory/(identity+'-policy.json')
        write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'clock', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [targets['greeting']['service']], 'publications': [publications['greeting']],
            'capability': capability, 'operations': [operation], 'resources': {'kind': 'clock'},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        client.call('policy', 'apply', '--id', identity+'-allow', '--file', policy,
            '--operation-id', 'grant-'+identity, '--expected-generation', '0')
        grants.append({'capability': capability, 'policy': identity+'-allow'})
    for present, missing in ((grants[:1], 'wall'), (grants[1:], 'monotonic')):
        targets['greeting'] = deploy(client, fixture/'my-greeting/deployment.json', publications['greeting'],
            generation=str(targets['greeting']['generation']), grants=present)
        absent('ts-clock-missing-'+missing)
    targets['greeting'] = deploy(client, fixture/'my-greeting/deployment.json', publications['greeting'],
        generation=str(targets['greeting']['generation']), grants=grants)
    result['typescriptClockAuthority'] = {'denials': denied, 'explicitGrants': grants,
        'providerBindingCount': 2, 'ambientClockGranted': False}


def probe(client, targets, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    rows, failures = [], []

    def observed(template, mode, label):
        target = targets[template]
        function = 'greet' if template == 'greeting' else 'count'
        row = call(client, target, template, function, ['clock:'+mode], label)
        result['invocations'].append(row)
        require(row['processReaped'], 'typescript-clock-process-retirement')
        used = row['response']['data']['consumption']
        require(0 < int(used['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(used['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and all(int(used[key]) == 0 for key in ('outboundRequests', 'childCalls', 'logBytes', 'effectCount')),
                'typescript-clock-original-budget-and-effects')
        return row

    def idle(label):
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, label+'-retired', population))

    for mode in (*(('undeclared:'+name) for name in UNDECLARED), 'explicit'):
        label = 'ts-clock-closed-'+mode.replace(':', '-')
        row = observed('word-count', mode, label)
        assert_value(client, row, [{'ok': 681}])
        idle(label)
        rows.append({'case': 'closed:'+mode, 'decoded': row['decoded'], 'activation': row['activation']})
    for mode in SELECTED:
        label = 'ts-clock-'+mode
        row = observed('greeting', mode, label)
        assert_value(client, row, [{'ok': expected(mode)}])
        idle(label)
        rows.append({'case': mode, 'decoded': row['decoded'], 'activation': row['activation']})
    for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
        label = 'ts-clock-'+mode
        row = observed('greeting', mode, label)
        require(row['exitCode'] == 4 and row['response']['outcomeKnown'] is True
                and row['response']['error']['code'] == code and row['response']['data']['terminalState'] == code.replace('-', '_'),
                'typescript-clock-terminal-shape')
        if mode == 'fuel':
            require(int(row['response']['data']['consumption']['cpuFuel']) == targets['greeting']['budget']['cpuFuel'],
                    'typescript-clock-unchanged-fuel-cap')
        idle(label)
        fresh = observed('greeting', 'fresh', label+'-fresh')
        assert_value(client, fresh, [{'ok': expected('fresh')}])
        idle(label+'-fresh')
        failures.append({'case': mode, 'failure': row, 'fresh': fresh})
    result['typescriptStandardClocks'] = {'status': 'passed', 'cases': rows, 'recovery': failures,
        'clockSource': 'existing-explicit-clock-providers', 'frozenDefaultTimeAccepted': False,
        'ordinaryOutsideLibrary': True, 'transitiveUtf8AndBinaryResources': True,
        'engineRebuilt': False, 'fullTicketQualification': False}

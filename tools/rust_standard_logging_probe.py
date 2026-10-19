"""Default-off real signed stdio campaign; no fake host/reference substitution."""
from tools.dev_workflow.common import require
from tools.rust_capsule_project import read_json, write_json
from tools.rust_standard_logging_inputs import CLOSED, PROFILE, LOG

CASES = ('formatted', 'stderr', 'utf8', 'vectors', 'invalid', 'incomplete',
         'too-large', 'too-many-vectors', 'empty', 'budget')
LOGGED = {'formatted', 'stderr', 'utf8', 'vectors', 'budget'}


def selected(fixture):
    value = read_json(fixture / 'stdio-probe.json')
    require(isinstance(value, dict) and set(value) == {'formatVersion', 'runtimeProfile'}
            and type(value['formatVersion']) is int and value['formatVersion'] == 1
            and isinstance(value['runtimeProfile'], str) and value['runtimeProfile'] in {CLOSED, PROFILE},
            'rust-stdio-signed-selector')
    return value['runtimeProfile']


def configure(settings, fixture):
    if selected(fixture) == CLOSED: return
    from tools.c_standard_logging_probe import configure as install_provider
    install_provider(settings)


def grant(client, node, fixture, targets, publications, result):
    if selected(fixture) == CLOSED: return
    from tools.c_standard_facilities_probe import require_denied_before_guest
    from tools.rust_capsule_node import call, deploy
    for name in ('Ada', 'stdio:formatted'):
        denied = call(client, targets['greeting'], 'greeting', 'greet', [name],
                      'rust-stdio-without-grant-' + ('ordinary' if name == 'Ada' else 'library'))
        result['invocations'].append(denied)
        require_denied_before_guest(denied)
    installed = [row for row in node.startup_record['providers'] if row['id'] == 'log']
    require(len(installed) == 1 and installed[0]['capability'] == LOG
            and installed[0]['profile'] == 'activation-log-v1' and installed[0]['tenant'] == 'examples'
            and installed[0]['service'] == 'runtime-host', 'rust-stdio-provider-identity')
    descriptor = installed[0]
    binding = client.directory / 'rust-stdio-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': LOG,
        'providerProfile': descriptor['profile'], 'configurationDigest': descriptor['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['write']}})
    client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'log-installed', '--file', binding,
                '--operation-id', 'rust-stdio-install', '--expected-generation', '0')
    target = targets['greeting']
    policy = client.directory / 'rust-stdio-policy.json'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'stdio', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']], 'capability': LOG,
        'operations': ['write'], 'resources': {'kind': 'log', 'levels': ['info', 'error']},
        'ceiling': {'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000}}]})
    client.call('policy', 'apply', '--id', 'rust-standard-stdio', '--file', policy,
                '--operation-id', 'rust-stdio-grant', '--expected-generation', '0')
    require(not any(row['capability'] == LOG for row in target['grants']), 'rust-stdio-grant-already-present')
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[*target['grants'], {'capability': LOG, 'policy': 'rust-standard-stdio'}])
    result['rustStandardStdioGrant'] = {'capability': LOG, 'policy': 'rust-standard-stdio'}


def probe(client, target, fixture, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    profile = selected(fixture)
    rows, recovery = [], []
    def completed(row, mode, logged):
        require(row['processReaped'], 'rust-stdio-process-not-reaped')
        consumed = row['response']['data']['consumption']
        require(int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumed['outboundRequests']) == 0, 'rust-stdio-consumption-bounds')
        actual = int(consumed['logBytes'])
        require(0 < actual <= target['budget']['logBytes'] if logged else actual == 0,
                'rust-stdio-log-consumption')
    def invoke(mode, label=None):
        row = call(client, target, 'greeting', 'greet', ['stdio:' + mode], label or 'rust-stdio-' + mode)
        result['invocations'].append(row)
        expected = 'ordinary-stdio:' + mode + '|resource=Gr\u00fc\u00dfe|fresh=1'
        assert_value(client, row, [{'ok': expected}])
        completed(row, mode, mode in LOGGED)
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, label or 'rust-stdio-' + mode + '-retired', population))
        rows.append({'mode': mode, 'expected': expected, 'invocation': row})
    if profile == CLOSED:
        for index in range(3): invoke('closed', 'rust-closed-stdio-fresh-' + str(index))
    else:
        for mode in CASES: invoke(mode)
        for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
            failed = call(client, target, 'greeting', 'greet', ['stdio:' + mode], 'rust-stdio-' + mode)
            result['invocations'].append(failed)
            require(failed['exitCode'] == 4 and failed['processReaped'] and failed['response']['outcomeKnown']
                    and failed['response']['error']['code'] == code
                    and failed['response']['data']['terminalState'] == code.replace('-', '_'), 'rust-stdio-fault-shape')
            completed(failed, mode, True)
            if mode == 'fuel':
                require(int(failed['response']['data']['consumption']['cpuFuel']) == target['budget']['cpuFuel'],
                        'rust-stdio-original-fuel-bound')
            result['samples'].append(sample(client, accounting, 'rust-stdio-' + mode + '-retired', population))
            invoke('utf8', 'rust-stdio-' + mode + '-fresh')
            recovery.append({'mode': mode, 'failure': failed, 'freshInvocation': rows[-1]['invocation']})
    result['rustStandardStdio'] = {'status': 'passed', 'runtimeProfile': profile,
                                   'cases': rows, 'recovery': recovery, 'concurrencyQualified': False}

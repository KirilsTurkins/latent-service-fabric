"""Explicit activation-only authority for the joined closed-filesystem control."""
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK
from tools.phase2_operator_process import require, write_json

OPERATIONS = ['register', 'park', 'wake', 'settle', 'close', 'observe', 'wait-for',
              'wait-until', 'timer-start', 'timer-next', 'timer-stop']
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
          'timers': 8, 'results': 8, 'nativeOwners': 8}


def configure(settings):
    settings['providers']['activationRuntime'] = {
        'identity': {'id': 'activation-filesystem', 'tenant': 'examples',
                     'service': 'activation-host', 'epoch': 1}, 'limits': dict(LIMITS)}
    settings['providers']['bindings'].append({'name': 'activation-filesystem-greeting', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'activation-host',
        'contract': ACTIVATION, 'providerBinding': 'activation-filesystem-installed'})
    require(len(settings['providers']['bindings']) <= 16, 'dotnet-filesystem-binding-bound')


def grant(client, node, fixture, targets, publications, result):
    from tools.rust_capsule_node import call, deploy
    target = targets['greeting']
    require([row['capability'] for row in target['grants']] == [CLOCK],
            'dotnet-filesystem-original-clock-only-grant')
    denied = call(client, target, 'greeting', 'greet', ['Ada'], 'dotnet-filesystem-activation-denied')
    response = denied['response']; consumed = response['data']['consumption']
    require(denied['processReaped'] is True and response['outcomeKnown'] is True
            and denied['exitCode'] == 4 and response['error']['code'] == 'permission-denied'
            and all(int(consumed[key]) == 0 for key in ('cpuFuel', 'peakMemoryBytes', 'outboundRequests',
                                                       'logBytes', 'effectCount')),
            'dotnet-filesystem-explicit-activation-required')
    result['invocations'].append(denied)
    installed = [row for row in node.startup_record['providers'] if row['id'] == 'activation-filesystem']
    require(len(installed) == 1 and installed[0]['capability'] == ACTIVATION,
            'dotnet-filesystem-installed-provider')
    provider = installed[0]
    binding = client.directory / 'activation-filesystem-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': ACTIVATION,
        'providerProfile': provider['profile'], 'configurationDigest': provider['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': OPERATIONS}})
    applied = client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'activation-filesystem-installed',
        '--file', binding, '--operation-id', 'install-filesystem-task-runtime', '--expected-generation', '0')
    require(applied['outcomeKnown'] is True and applied['category'] == 'success',
            'dotnet-filesystem-binding-apply')
    policy = client.directory / 'activation-filesystem-policy.json'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'joined-filesystem', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']],
        'capability': ACTIVATION, 'operations': OPERATIONS, 'resources': {'kind': 'clock'},
        'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
    applied = client.call('policy', 'apply', '--id', 'activation-filesystem-allow', '--file', policy,
        '--operation-id', 'allow-filesystem-task-runtime', '--expected-generation', '0')
    require(applied['outcomeKnown'] is True and applied['category'] == 'success',
            'dotnet-filesystem-policy-apply')
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[*target['grants'],
            {'capability': ACTIVATION, 'policy': 'activation-filesystem-allow'}])
    result['dotnetFilesystemRuntimeAuthority'] = {'denied': denied, 'provider': provider,
        'requiredDeclarations': [CLOCK, ACTIVATION], 'providerLimits': dict(LIMITS),
        'additionalWallEntropyOrHttpAuthority': False}

"""Explicit activation authority and ordinary managed-queue retirement controls."""
from tools.dotnet_guest import entropy_grants
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK, RANDOM, WALL
from tools.dotnet_task_runtime_fixture import CASES, expected
from tools.phase2_operator_process import require, write_json

OPERATIONS = ['register', 'park', 'wake', 'settle', 'close', 'observe', 'wait-for',
              'wait-until', 'timer-start', 'timer-next', 'timer-stop']


def configure(settings):
    entropy_grants.configure(settings)
    settings['providers']['clockWall'] = {'identity': {
        'id': 'wall-tasks', 'tenant': 'examples', 'service': 'task-clock-host', 'epoch': 1}}
    settings['providers']['bindings'].append({'name': 'wall-managed-tasks', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'task-clock-host',
        'contract': WALL, 'providerBinding': 'wall-tasks-installed'})
    settings['providers']['activationRuntime'] = {
        'identity': {'id': 'activation-tasks', 'tenant': 'examples', 'service': 'activation-host', 'epoch': 1},
        'limits': {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
                   'timers': 8, 'results': 8, 'nativeOwners': 8}}
    settings['providers']['bindings'].append({'name': 'activation-managed-tasks', 'tenant': 'examples',
        'consumerService': 'examples/my-greeting', 'providerService': 'activation-host',
        'contract': ACTIVATION, 'providerBinding': 'activation-tasks-installed'})
    require(len(settings['providers']['bindings']) <= 16, 'dotnet-tasks-binding-bound')


def grant(client, node, fixture, targets, publications, result):
    from tools.rust_capsule_node import call, deploy
    target = targets['greeting']
    require({row['capability'] for row in target['grants']} == {CLOCK}, 'dotnet-tasks-original-clock-only-grant')
    denied = call(client, target, 'greeting', 'greet', ['Ada'], 'dotnet-tasks-activation-denied')
    require(denied['processReaped'] and denied['response']['outcomeKnown'] is True
            and denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied',
            'dotnet-tasks-explicit-activation-required')
    result['invocations'].append(denied)
    installed = [row for row in node.startup_record['providers'] if row['id'] == 'activation-tasks']
    require(len(installed) == 1 and installed[0]['capability'] == ACTIVATION,
            'dotnet-tasks-installed-provider')
    provider = installed[0]
    binding = client.directory / 'activation-tasks-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': ACTIVATION,
        'providerProfile': provider['profile'], 'configurationDigest': provider['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': OPERATIONS}})
    applied = client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'activation-tasks-installed',
        '--file', binding, '--operation-id', 'install-managed-task-runtime', '--expected-generation', '0')
    require(applied['outcomeKnown'] is True and applied['category'] == 'success', 'dotnet-tasks-binding-apply')
    policy = client.directory / 'activation-tasks-policy.json'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'ordinary-tasks', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']],
        'capability': ACTIVATION, 'operations': OPERATIONS, 'resources': {'kind': 'clock'},
        'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
    applied = client.call('policy', 'apply', '--id', 'activation-tasks-allow', '--file', policy,
        '--operation-id', 'allow-managed-task-runtime', '--expected-generation', '0')
    require(applied['outcomeKnown'] is True and applied['category'] == 'success', 'dotnet-tasks-policy-apply')
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=target['grants'] + [
            {'capability': ACTIVATION, 'policy': 'activation-tasks-allow'}])
    targets['greeting'] = entropy_grants.grant(client, node, fixture / 'my-greeting/deployment.json',
        publications['greeting'], targets['greeting'], result)
    wall = [row for row in node.startup_record['providers'] if row['id'] == 'wall-tasks']
    require(len(wall) == 1 and wall[0]['capability'] == WALL
            and wall[0]['profile'] == 'activation-wall-v1', 'dotnet-tasks-installed-wall-provider')
    wall = wall[0]
    binding = client.directory / 'wall-tasks-binding.json'
    write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': WALL,
        'providerProfile': wall['profile'], 'configurationDigest': wall['configurationDigest'],
        'configurationEpoch': 1, 'restriction': {'operations': ['now-unix-millis']}})
    applied = client.call('policy', '--kind', 'provider-binding', 'apply', '--id', 'wall-tasks-installed',
        '--file', binding, '--operation-id', 'install-managed-task-wall', '--expected-generation', '0')
    require(applied['outcomeKnown'] is True and applied['category'] == 'success', 'dotnet-tasks-wall-binding-apply')
    policy = client.directory / 'wall-tasks-policy.json'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'timerqueue-static-initialization', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']],
        'capability': WALL, 'operations': ['now-unix-millis'], 'resources': {'kind': 'clock'},
        'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
    applied = client.call('policy', 'apply', '--id', 'wall-tasks-allow', '--file', policy,
        '--operation-id', 'allow-managed-task-wall', '--expected-generation', '0')
    require(applied['outcomeKnown'] is True and applied['category'] == 'success', 'dotnet-tasks-wall-policy-apply')
    current = targets['greeting']
    grants = [*current['grants'], {'capability': WALL, 'policy': 'wall-tasks-allow'}]
    missing_grants = []
    for ordinal, capability in enumerate((CLOCK, WALL, ACTIVATION, RANDOM)):
        current = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
            generation=str(current['generation']), grants=[row for row in grants if row['capability'] != capability])
        refused = call(client, current, 'greeting', 'greet', ['Ada'], 'dotnet-tasks-single-grant-denied-' + str(ordinal))
        response = refused['response']; consumption = response['data']['consumption']
        require(refused['processReaped'] and refused['exitCode'] == 4
                and response['outcomeKnown'] is True and response['error']['code'] == 'permission-denied'
                and all(int(consumption[key]) == 0 for key in ('cpuFuel', 'peakMemoryBytes', 'outboundRequests',
                                                              'logBytes', 'effectCount')),
                'dotnet-tasks-single-required-grant')
        result['invocations'].append(refused)
        missing_grants.append({'missingCapability': capability, 'invocation': refused})
    targets['greeting'] = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(current['generation']), grants=grants)
    result['dotnetTaskRuntimeAuthority'] = {'denied': denied, 'provider': provider,
        'requiredDeclarations': [CLOCK, WALL, ACTIVATION, RANDOM], 'httpAuthorityAdded': False,
        'wallProvider': wall, 'singleMissingGrantDenials': missing_grants,
        'entropyAuthority': result['noncryptoEntropyAuthority'],
        'entropyDenied': result['noncryptoEntropyGrantDenied'],
        'providerTaskLimit': 8, 'providerTimerLimit': 8}


def probe(client, target, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    rows = []
    for mode in CASES:
        label = 'dotnet-ordinary-tasks-' + mode
        row = call(client, target, 'greeting', 'greet', ['task:' + mode], label)
        assert_value(client, row, [{'ok': expected(mode)}])
        consumed = row['response']['data']['consumption']
        require(row['processReaped'] and row['response']['outcomeKnown'] is True
                and 0 < int(consumed['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumed['outboundRequests']) == int(consumed['logBytes']) == int(consumed['effectCount']) == 0,
                'dotnet-tasks-consumption-or-reaping')
        result['invocations'].append(row)
        result['providerIdle'].append(provider_idle(client))
        retired = sample(client, accounting, label + '-retired', population)
        result['samples'].append(retired)
        rows.append({'mode': mode, 'invocation': row, 'retirement': retired})
    result['dotnetTaskRuntime'] = {'status': 'passed', 'cases': rows,
        'applicationSchedulerReplacement': False, 'httpAuthorityAdded': False,
        'cpuPreemptionQualified': False, 'monitorWaitQualified': False,
        'threadLocalLogicalIsolationQualified': False, 'fullRuntimeQualification': False}

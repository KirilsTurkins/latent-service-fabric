"""Explicit activation authority and ordinary managed-queue retirement controls."""
from tools.dotnet_guest.runtime import ACTIVATION, CLOCK
from tools.dotnet_task_runtime_fixture import CASES, expected
from tools.phase2_operator_process import require, write_json

OPERATIONS = ['register', 'park', 'wake', 'settle', 'close', 'observe', 'wait-for',
              'wait-until', 'timer-start', 'timer-next', 'timer-stop']


def configure(settings):
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
    result['dotnetTaskRuntimeAuthority'] = {'denied': denied, 'provider': provider,
        'requiredDeclarations': [CLOCK, ACTIVATION], 'httpAuthorityAdded': False,
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

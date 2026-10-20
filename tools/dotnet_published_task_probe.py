"""Published default Polly retry/timer execution under original node retirement gates."""
from tools.dotnet_published_task_fixture import CASES, expected
from tools.phase2_operator_process import require


def probe(client, target, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    rows = []
    for mode in CASES:
        label = 'dotnet-published-tasks-' + mode
        row = call(client, target, 'greeting', 'greet', ['published:' + mode], label)
        assert_value(client, row, [{'ok': expected(mode)}])
        consumed = row['response']['data']['consumption']
        require(row['processReaped'] and row['response']['outcomeKnown'] is True
                and 0 < int(consumed['cpuFuel']) <= target['budget']['cpuFuel']
                and 0 < int(consumed['peakMemoryBytes']) <= target['budget']['memoryBytes']
                and int(consumed['outboundRequests']) == int(consumed['logBytes']) == int(consumed['effectCount']) == 0,
                'dotnet-published-tasks-consumption-or-reaping')
        result['invocations'].append(row)
        result['providerIdle'].append(provider_idle(client))
        retired = sample(client, accounting, label + '-retired', population)
        result['samples'].append(retired)
        rows.append({'mode': mode, 'invocation': row, 'retirement': retired})
    result['dotnetPublishedTasks'] = {'status': 'passed', 'cases': rows,
        'applicationSchedulerReplacement': False, 'httpAuthorityAdded': False,
        'cpuPreemptionQualified': False, 'monitorWaitQualified': False,
        'threadLocalLogicalIsolationQualified': False, 'fullRuntimeQualification': False}

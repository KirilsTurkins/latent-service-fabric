"""Exact original-component differential under independently finite queue caps."""
from tools.go_resource_runtime_fixture import EXPECTED
from tools.phase2_operator_process import require
from tools.resource_runtime_node import retire
from tools.rust_capsule_node import call, selected_revision
from tools.rust_capsule_project import write_json


def outcome(row, target, revision, mode, denied):
    require(type(denied) is bool and mode in ('fresh', 'parallel'), 'Go-queue-closed-case')
    require(row['processReaped'] and row['response']['outcomeKnown']
            and row['response']['data']['resolvedRevision'] == revision,
            'Go-queue-reaped-original-revision')
    usage = row['response']['data']['consumption']
    require(0 < int(usage['cpuFuel']) <= target['budget']['cpuFuel']
            and 0 < int(usage['peakMemoryBytes']) <= target['budget']['memoryBytes']
            and all(int(usage[key]) == 0 for key in ('outboundRequests','childCalls','effectCount',
                'stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
            'Go-queue-original-budgets-real-execution-no-effects')
    if denied:
        require(row['exitCode'] == 4 and row['response']['error']['code'] == 'guest-trap'
                and int(usage['logBytes']) == 0, 'Go-queue-admission-before-callback-or-log')
    else:
        require(row['exitCode'] == 0 and row['decoded'] == [{'ok':EXPECTED[mode]}]
                and 0 < int(usage['logBytes']) <= target['budget']['logBytes'],
                'Go-queue-exact-ordinary-result-and-log')


def programme(clients, targets, probe, output, component, ceiling):
    require(type(ceiling) is int and ceiling in (8,9), 'Go-queue-closed-independent-ceiling')
    cases = [('fresh',True)] if ceiling == 8 else [('fresh',False),('parallel',True),('fresh',False)]
    result = {'status':'incomplete', 'queueCeiling':ceiling, 'taskCeiling':16,
              'managedQueueReservations':8, 'cases':[], 'fullCostMatrixQualified':False,
              'physicalMemoryAccountingQualified':False, 'nativeThreadsQualified':False}
    try:
        for index, (mode, denied) in enumerate(cases):
            for tenant in ('examples','foreign'):
                client, target = clients[tenant], targets[tenant]
                revision = selected_revision(client,target)
                require(revision['releaseDigest'] == component, 'Go-queue-original-component')
                label = 'queue-' + str(ceiling) + '-' + str(index) + '-' + tenant
                row = call(client,target,'greeting','greet',['resource-runtime:'+mode],label)
                entry = {'tenant':tenant,'mode':mode,'expectedAdmissionDenial':denied,'invocation':row}
                result['cases'].append(entry)
                write_json(output/'queue-progress.json',result)
                outcome(row,target,revision,mode,denied)
                entry['retirement'] = retire(client,probe,target,output,label)
                write_json(output/'queue-progress.json',result)
        result['status'] = 'passed'
        write_json(output/'programme.json',result)
        return result
    except BaseException:
        result['status'] = 'failed'
        write_json(output/'queue-FAILED.json',result)
        raise

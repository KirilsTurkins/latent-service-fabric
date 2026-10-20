"""Finite ordinary resource observations; host retirement is checked separately."""
from tools.embedded_resource_fixture import EXPECTED
from tools.phase2_operator_process import require

PREFIX = 'embedded-resource-'


def probe(client, target, accounting, result, population, *, language):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    require(language in EXPECTED, 'embedded-resource-probe-language')
    rows = []

    def invoke(mode, label):
        row = call(client,target,'greeting','greet',['resources:'+mode],PREFIX+label)
        result['invocations'].append(row)
        usage = row['response']['data']['consumption']
        require(row['processReaped'] and row['response']['outcomeKnown'] is True
            and 0 < int(usage['cpuFuel']) <= target['budget']['cpuFuel']
            and 0 < int(usage['peakMemoryBytes']) <= target['budget']['memoryBytes']
            and all(int(usage[name]) == 0 for name in ('outboundRequests','logBytes','effectCount')),
            'embedded-resource-original-bounds-known-reaped')
        return row

    def retire(label):
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client,accounting,PREFIX+label+'-retired',population))

    for mode,expected in EXPECTED[language].items():
        row = invoke(mode,mode)
        assert_value(client,row,[{'ok':expected}])
        rows.append({'mode':mode,'invocation':row})
        retire(mode)
    trapped = invoke('trap','trap')
    require(trapped['exitCode'] == 4 and trapped['response']['error']['code'] == 'guest-trap'
        and trapped['response']['data']['terminalState'] == 'guest_trap', 'embedded-resource-explicit-trap')
    retire('trap')
    recovered = invoke('binary','fresh-after-trap')
    assert_value(client,recovered,[{'ok':EXPECTED[language]['binary']}])
    retire('fresh-after-trap')
    result['embeddedResourceConformance'] = {'status':'passed','language':language,'cases':rows,
        'explicitTrap':trapped,'freshAfterTrap':recovered,'newInvocations':len(rows)+2,
        'originalGrants':target['grants'],'additionalProviders':0,'scratchStorage':False,
        'resourceStreamClosureIsHostRetirement':False,'concurrentReadersQualified':False,
        'crossTenantQualification':False,'fullTicketQualification':False}

"""Require ordinary classpath bytes, fresh stream positions and clock longs."""
import re
import time

from tools.java_resource_fixture import EXPECTED
from tools.phase2_operator_process import require

CLOCK = re.compile(r'clock\|wall=([0-9]{1,19})\|first=([0-9]{1,19})\|second=([0-9]{1,19})\|fresh=1\Z')


def clock_values(decoded, before, after):
    require(type(decoded) is list and len(decoded) == 1 and type(decoded[0]) is dict
        and set(decoded[0]) == {'ok'} and type(decoded[0]['ok']) is str, 'java-resource-clock-result-shape')
    matched = CLOCK.fullmatch(decoded[0]['ok'])
    require(matched is not None, 'java-resource-clock-result-shape')
    wall, first, second = map(int, matched.groups())
    require(2**32 < wall < 2**63 and before <= wall <= after and 0 <= first <= second < 2**63,
            'java-resource-clock-value-or-width')
    return {'wallUnixMillis':wall, 'firstMonotonicNanos':first, 'secondMonotonicNanos':second,
        'wallBefore':before, 'wallAfter':after, 'wallExceedsU32':True,
        'monotonicSampleExceedsU32':second > 2**32, 'monotonicOrigin':'activation-local',
        'wallResolutionNanos':1_000_000, 'providerSleepOrClockOverride':False}


def probe(client, target, accounting, result, population):
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    require({row['capability'] for row in target['grants']} ==
        {'latent:clock/monotonic@0.1.0','latent:clock/wall@0.1.0'}, 'java-resource-original-clock-authority-only')
    cases = []

    def invoke(mode, *, identity=None):
        row = call(client, target, 'greeting', 'greet', ['resources:'+mode], 'java-resource-'+(identity or mode))
        result['invocations'].append(row)
        require(row['processReaped'] and row['response']['outcomeKnown'] is True, 'java-resource-known-reaped')
        usage = row['response']['data']['consumption']
        require(0 < int(usage['cpuFuel']) <= target['budget']['cpuFuel']
            and 0 < int(usage['peakMemoryBytes']) <= target['budget']['memoryBytes']
            and all(int(usage[name]) == 0 for name in ('outboundRequests','logBytes','effectCount')),
            'java-resource-original-bounds-zero-effects')
        return row

    def retired(mode):
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'java-resource-'+mode+'-retired', population))

    for mode, expected in EXPECTED.items():
        row = invoke(mode)
        assert_value(client, row, [{'ok':expected}])
        cases.append({'mode':mode,'invocation':row})
        retired(mode)
    before = time.time_ns()//1_000_000
    clock = invoke('clock')
    after = time.time_ns()//1_000_000
    require(clock['exitCode'] == 0, 'java-resource-clock-call-success')
    values = clock_values(clock.get('decoded'), before, after)
    retired('clock')
    failed = invoke('trap')
    require(failed['exitCode'] == 4 and failed['response']['error']['code'] == 'guest-trap'
        and failed['response']['data']['terminalState'] == 'guest_trap', 'java-resource-explicit-trap')
    retired('trap')
    fresh = invoke('binary', identity='fresh-after-trap')
    assert_value(client, fresh, [{'ok':EXPECTED['binary']}])
    retired('fresh-after-trap')
    result['javaResourceConformance'] = {'status':'passed', 'cases':cases, 'clock':values,
        'clockInvocation':clock, 'explicitTrap':failed, 'freshAfterTrap':fresh,
        'preservedRuntimeGrants':target['grants'], 'newInvocations':10,
        'streamCloseClaim':'Closing one byte-array stream preserves another open stream; close need not invalidate ByteArrayInputStream.',
        'fullTicketQualification':False, 'crossTenantQualification':False}

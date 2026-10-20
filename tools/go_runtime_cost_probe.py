"""Bounded ordinary-Go memory observations; parsing alone qualifies no costs."""
from tools.go_runtime_cost_fixture import HEAP_BYTES, STACK_BYTES
from tools.phase2_operator_process import require

FIELDS = ('beforeHeapAlloc', 'heapAlloc', 'beforeStackInuse', 'stackInuse',
          'heapSys', 'stackSys', 'sys', 'beforeNumGC', 'numGC', 'goroutines')
POSITIVE_MODES = ('baseline', 'stack-gc', 'heap-gc')
ZERO_EFFECTS = ('outboundRequests', 'childCalls', 'logBytes', 'effectCount',
                'blobReadBytes', 'blobWriteBytes', 'stateReadBytes', 'stateWriteBytes')


def integer(value):
    require(type(value) is int and value >= 0 or type(value) is str and value.isascii()
            and value.isdecimal() and 0 < len(value) <= 20, 'Go-cost-finite-consumption')
    result = int(value)
    require(result < 2**64, 'Go-cost-finite-consumption')
    return result


def observed(decoded, mode):
    require(mode in POSITIVE_MODES, 'Go-cost-no-exhaustion-success')
    require(type(decoded) is list and len(decoded) == 1 and type(decoded[0]) is dict
            and set(decoded[0]) == {'ok'} and type(decoded[0]['ok']) is str,
            'Go-cost-exact-typed-observation')
    value = decoded[0]['ok']
    require(value.isascii() and len(value) <= 2048, 'Go-cost-closed-observation-bound')
    parts = value.split('|')
    require(len(parts) == 14 and parts[:4] == ['cost', 'mode=' + mode, 'fresh=1', 'value=42'],
            'Go-cost-fresh-ordered-observation')
    row = {}
    for field, item in zip(FIELDS, parts[4:]):
        require(item.startswith(field + '='), 'Go-cost-exact-field-order')
        raw = item[len(field) + 1:]
        require(raw.isdecimal() and 0 < len(raw) <= 20, 'Go-cost-finite-field')
        number = int(raw)
        require(number < 2**64 and str(number) == raw, 'Go-cost-finite-field')
        row[field] = number
    require(row['goroutines'] > 0 and row['heapSys'] >= row['heapAlloc']
            and row['stackSys'] >= row['stackInuse'] and row['beforeNumGC'] <= row['numGC'] < 2**32,
            'Go-cost-consistent-live-memory')
    if mode == 'stack-gc':
        require(row['stackInuse'] >= row['beforeStackInuse'] + STACK_BYTES and row['numGC'] > row['beforeNumGC'],
                'Go-cost-real-stack-growth-and-GC-required')
    if mode == 'heap-gc':
        require(row['heapAlloc'] >= HEAP_BYTES and row['numGC'] > row['beforeNumGC'],
                'Go-cost-live-heap-and-GC-required')
    return {'mode': mode, 'memory': row, 'fresh': True,
            'physicalMemoryAccountingQualified': False, 'logicalUnusedKindsQualified': False}


def invocation(row, mode, budget, revision):
    require(row['processReaped'] is True and row['exitCode'] == 0
            and row['response']['outcomeKnown'] is True, 'Go-cost-real-known-reaped-success')
    result = observed(row['decoded'], mode)
    data = row['response']['data']
    require(data.get('resolvedRevision') == revision, 'Go-cost-exact-published-revision')
    consumption = data['consumption']
    fuel, memory, wall = (integer(consumption[key]) for key in
                           ('cpuFuel', 'peakMemoryBytes', 'wallTimeMicros'))
    require(0 < fuel <= budget['cpuFuel'] and 0 < memory <= budget['memoryBytes']
            and 0 < wall <= budget['wallTimeLimitMillis'] * 1000
            and all(integer(consumption[key]) == 0 for key in ZERO_EFFECTS),
            'Go-cost-original-admitted-budget-and-zero-effects')
    return {**result, 'consumption': {'cpuFuel': fuel, 'peakMemoryBytes': memory,
                                     'wallTimeMicros': wall},
            'sourceOfConsumption': 'actual-node-invocation-result',
            'physicalMemoryAccountingQualified': False, 'fullCostMatrixQualified': False}

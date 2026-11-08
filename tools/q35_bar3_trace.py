"""Bounded trace checks for the separately guarded, unimplemented BAR3 slice."""
from tools import q35_intx_trace as intx

GUARDS = tuple(
    f'lsf_q35_bar3_guard phase={phase} saved=0 wmask=0 w1cmask=0 region=0 mappings=stable bql=1'.encode()
    for phase in (4, 5)
)
MAPPINGS = (b'pci_update_mappings_add ', b'pci_update_mappings_del ')


def require(condition, reason):
    if not condition:
        raise ValueError('q35-bar3-trace-' + reason)


def inspect(raw, command, pin, line):
    prior = intx.inspect(raw, command, pin, line, bar3=True)
    lines = raw.splitlines()
    target = []
    for i, text in enumerate(lines):
        match = intx.PCI.fullmatch(text)
        if match and match.group(3, 4, 5) == (b'00', b'03', b'0'):
            target.append((i, match))
    def challenges(sequence):
        return [start for start in range(len(target)-len(sequence)+1)
            if all(row[1][1] == b'read' and
                (int(row[1][6], 16), int(row[1][8], 16)) == pair
                for row, pair in zip(target[start:start+len(sequence)], sequence))]
    starts, ends = challenges(intx.PREFIX), challenges(tuple(reversed(intx.PREFIX)))
    require(len(starts) == len(ends) == 1 and starts[0] < ends[0], 'challenge-window')
    window = target[starts[0]:ends[0]+len(intx.PREFIX)]
    bar = [(i, m) for i, m in window if int(m[6], 16) == 0x1c]
    require(tuple((m[1], int(m[8], 16)) for _, m in bar) ==
        ((b'read', 0), (b'write', 0xffffffff), (b'read', 0),
         (b'write', 0), (b'read', 0)), 'exact-bar3-read-write-sequence')
    guards = [(i, text) for i, text in enumerate(lines) if text.startswith(b'lsf_q35_bar3_guard')]
    require(len(guards) == 2 and tuple(text for _, text in guards) == GUARDS, 'exact-two-guards')
    for n in range(2):
        first, last = bar[1+2*n][0], bar[2+2*n][0]
        guard = guards[n][0]
        require(first < guard < last, 'guard-inside-write-callback')
        callback = lines[first+1:guard]
        require(not any(text.startswith(MAPPINGS) for text in callback), 'no-mapping-change')
        require(not any(text.startswith((b'pci_route_irq ', b'x86_gsi_interrupt '))
            for text in callback), 'no-interrupt-callback')
    return {'intx':prior, 'offset':0x1c, 'originalWord':0, 'probeWord':0xffffffff,
        'restoredWord':0, 'guardedWrites':2, 'qemuMappingChangesDuringWrites':0,
        'unimplementedInGuardedQemu':True, 'fullBarSizing':False,
        'physicalBankRetired':False, 'irqFundingQualified':False}

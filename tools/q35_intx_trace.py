"""Fail-closed parser for one loss-detecting, source-bound q35 trace.

The caller must independently authenticate the QEMU source derivation, trace
configuration, successful sink-failure control, process exit and full pipe
retirement. This parser alone never proves complete trace delivery.
"""
import re

MAX_TRACE = 4 * 1024 * 1024
DEVICE_PATH = b'/machine/peripheral/net0'
PREFIX = ((0x00, 0xf4), (0x01, 0x1a), (0x02, 0x41), (0x03, 0x10),
          (0x09, 0x00), (0x0a, 0x00), (0x0b, 0x02), (0x0a, 0x00))
PCI = re.compile(rb'^pci_cfg_(read|write) ([A-Za-z0-9_.-]{1,80}) '
                 rb'([0-9a-f]{2}):([0-9a-f]{2})\.([0-7]) @0x([0-9a-f]+) '
                 rb'(->|<-) 0x([0-9a-f]+)$')
ROUTE = re.compile(rb'^pci_route_irq IRQ ([0-3]) @([^ ]{1,160}) -> IRQ ([0-7]) @([^ ]{1,160})$')
GSI = re.compile(rb'^x86_gsi_interrupt GSI interrupt #([0-9]{1,2}) level:([01])$')
VIRTIO = re.compile(rb'^lsf_q35_virtio_guard old=0x([0-9a-f]+) new=0x([0-9a-f]+) '
                    rb'phase=([23]) status=0 isr=0 disabled=1 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=0 vga=0 peer=0 waiting=0 netVhost=0 queues=1 netStable=1 mappings=stable bql=1$')
ARMED = b'lsf_q35_intx_armed command=0x103'

def require(value, reason):
    if not value:
        raise ValueError('q35-intx-trace-'+reason)

def inspect(raw, command, pin, line):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_TRACE and raw.endswith(b'\n'), 'bounded-complete-lines')
    require(type(command) is int and command == 0x0103 and
            type(pin) is int and 1 <= pin <= 4 and type(line) is int and 0 <= line <= 0xff,
            'guest-observation-shape')
    lowered = raw.lower()
    require(b'trace event ' not in lowered and b'trace-event ' not in lowered,
            'trace-configuration-warning')
    events = []
    for text in raw.splitlines():
        m = PCI.fullmatch(text)
        if m:
            kind, name, bus, slot, function, offset, arrow, value = m.groups()
            require((kind == b'read' and arrow == b'->') or
                    (kind == b'write' and arrow == b'<-'), 'config-arrow')
            events.append(('pci', kind, name, int(bus, 16), int(slot, 16),
                           int(function), int(offset, 16), int(value, 16)))
        elif text.startswith((b'pci_cfg_read ', b'pci_cfg_write ')):
            raise ValueError('q35-intx-trace-malformed-config')
        else:
            m = ROUTE.fullmatch(text)
            if m:
                events.append(('route', int(m[1]), m[2], int(m[3]), m[4]))
            elif text.startswith(b'pci_route_irq '):
                raise ValueError('q35-intx-trace-malformed-route')
            else:
                m = GSI.fullmatch(text)
                if m:
                    events.append(('gsi', int(m[1]), int(m[2])))
                elif text.startswith(b'x86_gsi_interrupt '):
                    raise ValueError('q35-intx-trace-malformed-gsi')
                else:
                    m = VIRTIO.fullmatch(text)
                    if m:
                        events.append(('virtio', int(m[1], 16), int(m[2], 16), int(m[3])))
                    elif text.startswith(b'lsf_q35_virtio_guard '):
                        raise ValueError('q35-intx-trace-malformed-virtio-guard')
                    elif text == ARMED:
                        events.append(('armed',))
                    elif text.startswith(b'lsf_q35_intx_armed'):
                        raise ValueError('q35-intx-trace-malformed-arm')
    target = [(i, e) for i, e in enumerate(events) if e[0] == 'pci' and e[3:6] == (0, 3, 0)]
    def challenge_positions(sequence):
        return [i for i in range(len(target)-len(sequence)+1)
            if all(e[1] == b'read' and (e[6], e[7]) == pair
                   for (_, e), pair in zip(target[i:i+len(sequence)], sequence))]
    starts, ends = challenge_positions(PREFIX), challenge_positions(tuple(reversed(PREFIX)))
    require(len(starts) == len(ends) == 1 and starts[0]+len(PREFIX) <= ends[0], 'unique-challenge-window')
    arms = [i for i, event in enumerate(events) if event[0] == 'armed']
    require(len(arms) == 1 and target[starts[0]+6][0] < arms[0] < target[starts[0]+7][0],
            'unique-challenge-arm')
    begin, finish = target[starts[0]][0], target[ends[0]+len(PREFIX)-1][0]
    window = events[begin:finish+1]
    selected = [e for e in window if e[0] == 'pci' and e[3:6] == (0, 3, 0)]
    require(selected and len({e[2] for e in selected}) == 1, 'single-device-name')
    command_rows = [(i, e) for i, e in enumerate(window)
                    if e[0] == 'pci' and e[3:6] == (0, 3, 0) and e[6] == 4]
    expected = ((b'read', command), (b'read', command), (b'write', command ^ 0x400),
                (b'read', command ^ 0x400), (b'write', command), (b'read', command),
                (b'read', command))
    require(tuple((e[1], e[7]) for _, e in command_rows) == expected, 'exact-command-sequence')
    require([e[6] for e in selected if e[1] == b'write'] == [4, 4], 'no-other-selected-writes')
    for offset, expected_value in ((0x3d, pin), (0x3c, line)):
        reads = [e[7] for e in selected if e[1] == b'read' and e[6] == offset]
        require(len(reads) >= 3 and all(value == expected_value for value in reads), 'original-pin-line')
    pic_pairs = []
    for n in (2, 4):
        start, end = command_rows[n][0], command_rows[n+1][0]
        observed = [e for e in window[start+1:end] if e[0] in ('route', 'gsi')]
        guards = [e for e in window[start+1:end] if e[0] == 'virtio']
        require(guards == [('virtio', expected[n-1][1], expected[n][1], n//2+1)],
                'exact-virtio-guard')
        require(len(observed) == 12, 'complete-four-routes-and-eight-gsi')
        pic = []
        for i, parent in enumerate((7, 4, 5, 6)):
            route, apic, pic_event = observed[3*i:3*i+3]
            require(route == ('route', i, DEVICE_PATH, parent, b'root-complex'), 'selected-route')
            require(apic == ('gsi', 16+parent, 0), 'apic-level')
            require(pic_event[0] == 'gsi' and 0 <= pic_event[1] < 16 and pic_event[2] == 0,
                    'pic-level')
            pic.append(pic_event[1])
        pic_pairs.append(pic)
    require(pic_pairs[0] == pic_pairs[1], 'stable-shared-pic-routes')
    return {'selectedBdf': '0000:00:03.0', 'command': command, 'pin': pin, 'line': line,
            'busMasterEnabled': False,
            'selectedCommandWrites': 2, 'selectedRouteCallbacks': 8,
            'virtioGuardPasses': 2,
            'apicGsi': [23, 20, 21, 22], 'picGsi': pic_pairs[0],
            'observedGsiAssertionsDuringWrites': 0, 'traceDeliveryQualified': False,
            'irqFundingQualified': False, 'physicalBankRetired': False}

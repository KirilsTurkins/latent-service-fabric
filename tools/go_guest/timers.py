"""Captured pinned Go timer heap ownership and canonical readiness handoff."""
from tools.go_guest.runtime import checked_sources, replace_once


def runtime_sources(goroot, sources, sdk):
    sources.update(checked_sources(goroot, {
        'runtime/mheap.go': '848cedd74ae1d10af65eb3beed88ddd7d22d184a64a5a7477251c4886e8a459d'}))
    text = sources['runtime/time.go']
    text = replace_once(text, '\tisSending atomic.Int32\n}',
        '\tisSending atomic.Int32\n\tlsfToken [2]uint64\n\tlsfSlot uint32\n}')
    text = replace_once(text, '\tif lsfActivationActive { lsfFail("LSF Go timer API is not qualified by this profile") }',
        '\tlsfToken := lsfReserveTimer(when, period)')
    text = replace_once(text, '\tt.modify(when, period, f, arg, 0)',
        '\tlsfInstallTimer(&t.timer, lsfToken)\n\tt.modify(when, period, f, arg, 0)')
    text = replace_once(text, '\treturn t.stop()\n}',
        '\tstopped := t.stop()\n\ttoken := lsfRetireTimer(&t.timer)\n'
        '\tlsfActivationTimerFence(token[0], token[1])\n\treturn stopped\n}')
    text = replace_once(text, '\treturn t.reset(when, period)\n}',
        '\tactive := t.stop()\n\ttoken := lsfRetireTimer(&t.timer)\n\tlsfActivationTimerFence(token[0], token[1])\n'
        '\tnewToken := lsfReserveTimer(when, period)\n\tlsfInstallTimer(&t.timer, newToken)\n'
        '\tt.reset(when, period)\n\treturn active\n}')
    text = replace_once(text, '\tf(arg, seq, delay)\n',
        '\tlsfBeforeTimerCallback(t)\n\tf(arg, seq, delay)\n\tlsfAfterTimerCallback(t)\n')
    sources['runtime/time.go'] = text
    bridge = sources['runtime/os_wasip1.go']
    bridge = replace_once(bridge, '\tif parent.lsfOwner[1] != 0 { hasParent = 1 }\n'
        '\tlsfRegister(0, hasParent, int64(parent.lsfOwner[0]), int64(parent.lsfOwner[1]), unsafe.Pointer(&result))',
        '\tcontinuation := parent.lsfOwner\n\tif continuation[1] == 0 { continuation = lsfTimerParent }\n'
        '\tif continuation[1] != 0 { hasParent = 1 }\n'
        '\tlsfRegister(0, hasParent, int64(continuation[0]), int64(continuation[1]), unsafe.Pointer(&result))')
    bridge = replace_once(bridge, '\tif lsfActivationTasks == 1 && lsfActivationDrain != nil {',
        '\tif lsfActivationTasks == 1 && lsfTimerCallbacks == 0 && lsfActivationDrain != nil {')
    bridge = replace_once(bridge, '\tif lsfActivationTasks > 1 {',
        '\tlsfSweepCollectedTimers()\n\tif lsfActivationTasks > 1 || lsfTimerCallbacks != 0 {')
    bridge = replace_once(bridge, '\tif lsfActivationTasks != 1 { lsfFail("LSF result drain incomplete") }',
        '\tif lsfActivationTasks != 1 || lsfTimerCallbacks != 0 { lsfFail("LSF result drain incomplete") }\n'
        '\tlsfStopIdleChannelTimers()')
    sources['runtime/os_wasip1.go'] = bridge + '\n' + (sdk / 'runtime/timer_bridge.go.in').read_text()


def async_source(text, sdk):
    text = replace_once(text, '\tyielding    []chan unit', '\tyielding    []chan unit\n\ttimerWaits []*lsfTimerWait')
    text = replace_once(text, '\t\tnil,\n\t\truntime.Pinner{},', '\t\tnil,\n\t\tnil,\n\t\truntime.Pinner{},')
    text = replace_once(text, '\t\t\tcase STATUS_RETURNED:\n\t\t\t\twaitableJoin(event1, 0)',
        '\t\t\tcase STATUS_RETURNED:\n\t\t\t\tif lsfHandleTimerEvent(event1) { break }\n\t\t\t\twaitableJoin(event1, 0)')
    text = replace_once(text, '\t\t// Block this goroutine until the scheduler wakes us up.',
        '\t\tevent0 = EVENT_NONE\n\n\t\t// Block this goroutine until the scheduler wakes us up.')
    text = replace_once(text, '\t\t(<-state.channel)\n',
        '\t\t(<-state.channel)\n\t\trefreshTimers := lsfStartTimerWait()\n'
        '\t\tif refreshTimers || lsfRunnableActivationTasks() { runtime.Gosched(); continue }\n')
    if text.count('len(state.pending) == 0') != 2:
        raise ValueError('go-timer-dispatcher-pending-shape-drift')
    text = text.replace('len(state.pending) == 0', 'len(state.pending) + len(state.timerWaits) == 0')
    return text + '\n' + (sdk / 'runtime/timer_async.go.in').read_text()

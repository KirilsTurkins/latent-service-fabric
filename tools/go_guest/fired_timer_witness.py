"""Qualification-only probe at the authenticated Go timer fence match.

The ordinary runtime profile is unchanged. The resulting diagnostic SDK and
its source identity must be retained; this is not a byte-identical guest.
"""

GO_CHAN_SHA256 = 'dbe8d02ebb1b554b28263c8f34747c0b6d796b3e7040a2f6a625c472e9ce9a42'
GO_RUNTIME2_SHA256 = '7d66ed912f68b1259947807ca1bdf79ee7e54c6a61a716d88db663d570af66da'


def verified_runtime_sources(goroot):
    from tools.go_guest.runtime import checked_sources
    return checked_sources(goroot, {'runtime/chan.go': GO_CHAN_SHA256, 'runtime/runtime2.go': GO_RUNTIME2_SHA256})


DECLARATION = b'''// Diagnostic-only instrumentation: the host may treat this observation as
// a fence-match witness only in the explicitly selected signed activation.
//go:wasmimport latent:runtime/activation@0.1.0 observe
//go:noescape
func lsfFiredFenceObserve(result unsafe.Pointer)

var lsfFiredFirstStopped [2]uint64
var lsfFiredFenceRecorded bool
var lsfReturnedToken [2]uint64
var lsfReturnedFenceSeen bool

//go:linkname lsfReturnedTickerSelected runtime.lsfReturnedTickerSelected
func lsfReturnedTickerSelected(generation, id uint64) bool
//go:linkname lsfReturnedSetFenceChannel runtime.lsfReturnedSetFenceChannel
func lsfReturnedSetFenceChannel(channel unsafe.Pointer)

func lsfReturnedObserve() {
    var pinner runtime.Pinner
    defer pinner.Unpin()
    result := witRuntime.Allocate(&pinner, 72, 8)
    lsfFiredFenceObserve(result)
    if *(*uint32)(result) != 0 { panic("returned timer witness refused") }
}

func lsfReturnedBeforeDrop(wait *lsfTimerWait) {
    if wait.stopped || *(*byte)(wait.result) != 0 ||
       !lsfReturnedTickerSelected(wait.token[0], wait.token[1]) { return }
    if lsfReturnedToken[1] != 0 { panic("duplicate returned timer witness") }
    lsfReturnedToken = wait.token
    // This helper is reached only from the matching STATUS_RETURNED event,
    // before the canonical subtask is unjoined or dropped.
    lsfReturnedObserve()
    for attempts := 0; attempts < 64 && !lsfReturnedFenceSeen; attempts++ { runtime.Gosched() }
    if !lsfReturnedFenceSeen { panic("returned timer fence was not reached") }
    // Give the selected root a chance to park. The host independently requires
    // the real park before accepting the post-drop observation.
    runtime.Gosched()
}

func lsfReturnedAfterDrop(wait *lsfTimerWait) {
    if wait.token == lsfReturnedToken && lsfReturnedFenceSeen {
        lsfReturnedObserve()
        lsfReturnedSetFenceChannel(nil)
    }
}

func lsfFiredFenceWitness() {
    if lsfFiredFenceRecorded { return }
    lsfFiredFenceRecorded = true
    var pinner runtime.Pinner
    defer pinner.Unpin()
    result := witRuntime.Allocate(&pinner, 72, 8)
    lsfFiredFenceObserve(result)
    if *(*uint32)(result) != 0 { panic("fired timer fence witness refused") }
}

'''
SIGNATURE = b'//go:linkname lsfActivationTimerFence runtime.lsfActivationTimerFence\n'
STOPPED = b'''func lsfActivationTimerStopped(generation, id uint64) {
    if state == nil { return }
    for _, wait := range state.timerWaits {'''
INSTRUMENTED_STOPPED = b'''func lsfActivationTimerStopped(generation, id uint64) {
    if state == nil { return }
    if lsfFiredFirstStopped[1] == 0 { lsfFiredFirstStopped = [2]uint64{generation, id} }
    for _, wait := range state.timerWaits {'''
MATCH = b'''        if wait.token == [2]uint64{generation, id} {
            // Completion is durable even if it wins before this receive.'''
INSTRUMENTED = b'''        if wait.token == [2]uint64{generation, id} {
            if wait.token == lsfFiredFirstStopped { lsfFiredFenceWitness() }
            if wait.token == lsfReturnedToken {
                lsfReturnedSetFenceChannel(*(*unsafe.Pointer)(unsafe.Pointer(&wait.done)))
                lsfReturnedFenceSeen = true
            }
            // Completion is durable even if it wins before this receive.'''

EVENT = b'''        if !wait.started || wait.subtask != event { continue }
        waitableJoin(event, 0)
        subtaskDrop(event)'''
INSTRUMENTED_EVENT = b'''        if !wait.started || wait.subtask != event { continue }
        lsfReturnedBeforeDrop(wait)
        waitableJoin(event, 0)
        subtaskDrop(event)
        lsfReturnedAfterDrop(wait)'''

PARK_MATCH = b'''	if result.tag != 0 { lsfFail("LSF goroutine park denied") }
	gp.lsfParked = true'''
PARK_INSTRUMENTED = b'''	if result.tag != 0 { lsfFail("LSF goroutine park denied") }
	if lsfReturnedFenceChannel != nil && gp.waitreason == waitReasonChanReceive &&
	    gp.waiting != nil && gp.waiting.waitlink == nil &&
	    unsafe.Pointer(gp.waiting.c.get()) == lsfReturnedFenceChannel {
		var observation [72]byte
		lsfReturnedParkObserve(unsafe.Pointer(&observation[0]))
		if observation[0] != 0 { lsfFail("returned timer park observe denied") }
	}
	gp.lsfParked = true'''

PARK_DECLARATION = b'''
// Diagnostic-only exact channel identity. The selected dispatcher keeps the
// matching channel rooted through the park and clears this after subtask drop.
var lsfReturnedFenceChannel unsafe.Pointer
//go:linkname lsfReturnedSetFenceChannel
//go:nosplit
func lsfReturnedSetFenceChannel(channel unsafe.Pointer) { lsfReturnedFenceChannel = channel }
//go:wasmimport latent:runtime/activation@0.1.0 observe
//go:noescape
func lsfReturnedParkObserve(result unsafe.Pointer)
'''

BRIDGE = b'''
// Diagnostic-only selection of the unique periodic fixture owner. This uses
// the same single-threaded heap scan as lsfNextTimer and admits no host work.
//go:linkname lsfReturnedTickerSelected
//go:nosplit
func lsfReturnedTickerSelected(generation, id uint64) bool {
    for _, pp := range allp {
        for _, entry := range pp.timers.heap {
            t := entry.timer
            if t.lsfToken == ([2]uint64{generation, id}) && t.isChan && t.period == 251000000 { return true }
        }
    }
    return false
}
'''


def derive(source: bytes) -> bytes:
    if (source.count(SIGNATURE) != 1 or source.count(MATCH) != 1 or source.count(STOPPED) != 1
            or source.count(EVENT) != 1 or b'lsfReturnedToken' in source
            or b'lsfFiredFenceWitness' in source or b'lsfFiredFirstStopped' in source):
        raise ValueError('Go-fired-timer-fence-source-drift')
    return (source.replace(SIGNATURE, DECLARATION + SIGNATURE, 1)
                  .replace(STOPPED, INSTRUMENTED_STOPPED, 1).replace(MATCH, INSTRUMENTED, 1)
                  .replace(EVENT, INSTRUMENTED_EVENT, 1))


def derive_bridge(source: bytes) -> bytes:
    if source.count(b'func lsfNextTimer() (uint64, uint64) {') != 1 or b'lsfReturnedTickerSelected' in source:
        raise ValueError('Go-returned-timer-bridge-source-drift')
    return source + BRIDGE


def derive_activation_bridge(source: bytes) -> bytes:
    if source.count(PARK_MATCH) != 1 or b'lsfReturnedFenceChannel' in source:
        raise ValueError('Go-returned-timer-park-source-drift')
    return source.replace(PARK_MATCH, PARK_INSTRUMENTED, 1) + PARK_DECLARATION

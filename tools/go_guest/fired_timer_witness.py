"""Qualification-only probe at the authenticated Go timer fence match.

The ordinary runtime profile is unchanged. The resulting diagnostic SDK and
its source identity must be retained; this is not a byte-identical guest.
"""

DECLARATION = b'''// Diagnostic-only instrumentation: the host may treat this observation as
// a fence-match witness only in the explicitly selected signed activation.
//go:wasmimport latent:runtime/activation@0.1.0 observe
//go:noescape
func lsfFiredFenceObserve(result unsafe.Pointer)

var lsfFiredFirstStopped [2]uint64
var lsfFiredFenceRecorded bool

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
            // Completion is durable even if it wins before this receive.'''


def derive(source: bytes) -> bytes:
    if (source.count(SIGNATURE) != 1 or source.count(MATCH) != 1 or source.count(STOPPED) != 1
            or b'lsfFiredFenceWitness' in source or b'lsfFiredFirstStopped' in source):
        raise ValueError('Go-fired-timer-fence-source-drift')
    return (source.replace(SIGNATURE, DECLARATION + SIGNATURE, 1)
                  .replace(STOPPED, INSTRUMENTED_STOPPED, 1).replace(MATCH, INSTRUMENTED, 1))

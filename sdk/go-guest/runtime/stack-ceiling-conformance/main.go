package export_tests_caller_api

import (
    "runtime"
    "runtime/debug"
    "strconv"
    "time"
)

// The programme derives exactly one second source variant with depth96. It
// does not select initializer behavior through an application/host protocol.
const initializerDepth uint32 = 2

var initCalls uint32
var initialized = initializeStack()
var calls uint32
var liveStack uint64
var liveGC uint32

func initializeStack() uint64 {
    initCalls++
    return stackFrame(initializerDepth, 17, false)
}

// stack-frame-start
//go:noinline
func stackFrame(depth, seed uint32, collect bool) uint64 {
    var frame [8192]byte
    for index := range frame { frame[index] = byte(uint32(index) ^ seed) }
    var value uint64
    if depth == 0 {
        if collect {
            runtime.GC()
            var memory runtime.MemStats
            runtime.ReadMemStats(&memory)
            liveStack, liveGC = memory.StackInuse, memory.NumGC
            time.Sleep(time.Millisecond)
        }
    } else {
        value = stackFrame(depth-1, seed+1, collect)
    }
    // Each original array stays live through recursion, actual GC and a real
    // standard timer suspension. Range-by-value retains its ordinary copy.
    for _, item := range frame { value += uint64(item) }
    return value
}
// stack-frame-end

func Run(which uint32) string {
    calls++
    if calls != 1 || initCalls != 1 || initialized != 3133440 {
        panic("stack-initializer-or-fresh-state")
    }
    switch which {
    case 0:
        var before runtime.MemStats
        runtime.ReadMemStats(&before)
        if stackFrame(16, 29, true) != 17756160 ||
            liveStack < before.StackInuse+17*8192 || liveGC <= before.NumGC {
            panic("stack-GC-or-checksum-not-observed")
        }
        return "stack|fresh=1|init=3133440|checksum=17756160|before=" +
            strconv.FormatUint(before.StackInuse, 10) + "|live=" +
            strconv.FormatUint(liveStack, 10) + "|beforeGC=" +
            strconv.FormatUint(uint64(before.NumGC), 10) + "|gc=" +
            strconv.FormatUint(uint64(liveGC), 10)
    case 1:
        stackFrame(96, 29, false)
        panic("oversized-stack-was-not-refused")
    case 2:
        debug.SetMaxStack(1 << 30)
        stackFrame(96, 29, false)
        panic("raised-stack-was-not-refused")
    default:
        panic("stack-mode")
    }
}

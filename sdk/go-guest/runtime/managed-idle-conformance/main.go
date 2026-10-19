package export_tests_caller_api

import (
    "runtime"
    "sync"
    "time"
)

var initialized = initialize()
var calls uint32

func initialize() uint32 {
    done := make(chan uint32)
    go func() { time.Sleep(time.Millisecond); done <- 42 }()
    return <-done
}

func collect() {
    // Exercise real runtime GC workers and pinned heap state. Application
    // finalizer/cleanup callbacks remain outside this finite profile.
    values := make([][]byte, 32)
    for index := range values { values[index] = make([]byte, 2048) }
    var pinned runtime.Pinner
    pinned.Pin(&values[0][0])
    runtime.GC()
    pinned.Unpin()
    runtime.KeepAlive(values)
}

func Run(which uint32) uint32 {
    calls++
    if calls != 1 || initialized != 42 { panic("fresh runtime state") }
    switch which {
    case 0:
        collect()
    case 1:
        var workers sync.WaitGroup
        workers.Add(2)
        for index := 0; index < 2; index++ {
            go func() { defer workers.Done(); collect(); time.Sleep(time.Millisecond) }()
        }
        workers.Wait()
    case 2:
        // An accepted application sibling must drain before maintenance
        // reservations may retire, even if the exported result is ready.
        go func() { collect(); time.Sleep(30 * time.Millisecond) }()
    case 3:
        collect()
        time.Sleep(10 * time.Second)
    case 4:
        collect()
        panic("terminal original activation")
    case 5:
        collect()
        runtime.AddCleanup(new(uint32), func(uint32) {}, uint32(1))
    case 6:
        collect()
        go func() { select {} }()
    default:
        panic("unknown qualification mode")
    }
    return 42
}

package export_tests_caller_api

import (
    "runtime"
    "sync"
    "time"
)

var initialized = initializeValue()
var order []uint32
var invocationCount uint32
var requests = make(chan uint32)
var responses = make(chan uint32)
var stop = make(chan struct{})
var stopped = make(chan struct{})

func initializeValue() uint32 {
    var mutex sync.Mutex
    condition := sync.NewCond(&mutex)
    var value uint32
    go func(){
        time.Sleep(10 * time.Millisecond)
        mutex.Lock()
        value = 42
        condition.Signal()
        mutex.Unlock()
    }()
    mutex.Lock()
    for value == 0 { condition.Wait() }
    mutex.Unlock()
    return value
}

func init() {
    order = append(order, 1)
    ready := make(chan struct{})
    go func(){
        ticker := time.NewTicker(time.Hour)
        defer ticker.Stop()
        defer close(stopped)
        close(ready)
        for {
            select {
            case value := <-requests: responses <- value
            case <-ticker.C:
            case <-stop: return
            }
        }
    }()
    <-ready
}

func init() {
    <-time.After(time.Millisecond)
    order = append(order, 2)
}

func Run(which uint32) uint32 {
    invocationCount++
    if invocationCount != 1 || initialized != 42 || len(order) != 2 || order[0] != 1 || order[1] != 2 {
        panic("initializer order or fresh state")
    }
    switch which {
    case 1:
        // The owned initializer worker is still waiting for future work. Its
        // ordinary ticker does not authorize classifying it as managed idle.
        return 42
    case 2:
        time.Sleep(10 * time.Second)
    case 3:
        runtime.LockOSThread()
    }
    requests <- 42
    result := <-responses
    close(stop)
    <-stopped
    return result
}

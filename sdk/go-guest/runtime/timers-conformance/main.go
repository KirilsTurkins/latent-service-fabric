package export_tests_caller_api

import (
    "context"
    "runtime"
    "sync"
    "sync/atomic"
    "time"
)

var invocationCount uint32

func Run(which uint32) uint32 {
    invocationCount++
    if invocationCount != 1 { panic("cross-invocation state") }
    switch which {
    case 0:
        timer := time.NewTimer(10 * time.Millisecond)
        defer timer.Stop()
        if cap(timer.C) != 0 { panic("timer channel capacity") }
        <-timer.C
        if timer.Reset(time.Millisecond) { panic("reset expired timer") }
        <-timer.C
        if timer.Stop() { panic("stop delivered timer") }
    case 1:
        timer := time.NewTimer(time.Hour)
        if !timer.Stop() || timer.Stop() { panic("stop active timer") }
        if timer.Reset(time.Millisecond) { panic("reset stopped timer") }
        <-timer.C
        if timer.Reset(time.Hour) { panic("reset expired timer") }
        if !timer.Reset(time.Millisecond) { panic("reset active timer") }
        <-timer.C
        select { case <-timer.C: panic("stale timer value"); default: }
    case 2:
        ticker := time.NewTicker(time.Millisecond)
        if cap(ticker.C) != 0 { panic("ticker channel capacity") }
        first := <-ticker.C
        time.Sleep(10 * time.Millisecond)
        next := <-ticker.C
        if next.Before(first) { panic("ticker time reversal") }
        ticker.Reset(2 * time.Millisecond)
        <-ticker.C
        ticker.Stop()
        select { case <-ticker.C: panic("stopped ticker fired"); default: }
    case 3:
        var result atomic.Uint32
        var group sync.WaitGroup
        group.Add(1)
        time.AfterFunc(time.Millisecond, func(){ defer group.Done(); result.Store(42) })
        group.Wait()
        return result.Load()
    case 4:
        time.AfterFunc(20 * time.Millisecond, func(){})
    case 5:
        deadline, cancel := context.WithTimeout(context.Background(), 2 * time.Millisecond)
        defer cancel()
        <-deadline.Done()
        if deadline.Err() != context.DeadlineExceeded { panic("context deadline") }
    case 6:
        timer := time.NewTimer(time.Hour)
        var group sync.WaitGroup
        group.Add(1)
        go func(){ defer group.Done(); time.Sleep(time.Millisecond); if !timer.Reset(time.Millisecond) { panic("reset pending timer") } }()
        <-timer.C
        group.Wait()
        timer.Stop()
    case 7:
        <-time.After(10 * time.Second)
    case 8:
        one, two := time.NewTimer(time.Hour), time.NewTimer(time.Hour)
        defer one.Stop(); defer two.Stop()
        time.NewTimer(time.Hour)
    case 9:
        for range 8 { _ = time.NewTimer(time.Hour); runtime.GC() }
    case 10:
        time.AfterFunc(time.Millisecond, func(){panic("accepted callback panic")})
    case 11:
        timer := time.NewTimer(time.Hour)
        var group sync.WaitGroup
        group.Add(1)
        go func(){ defer group.Done(); time.Sleep(time.Millisecond); timer.Stop() }()
        group.Wait()
        select { case <-timer.C: panic("stopped pending timer"); default: }
    case 12:
        for range 12 {
            timer := time.NewTimer(time.Hour)
            timer.Reset(time.Hour)
            if !timer.Stop() { panic("timer reset/stop") }
        }
    case 13:
        var group sync.WaitGroup
        group.Add(1)
        time.AfterFunc(0, group.Done)
        group.Wait()
    case 14:
        // Expiry can enqueue a callback between the runtime's idle send and
        // dispatcher receive. Each iteration needs a fresh quiescence round.
        for range 64 {
            var group sync.WaitGroup
            group.Add(1)
            time.AfterFunc(0, group.Done)
            group.Wait()
        }
    case 15:
        var group sync.WaitGroup
        group.Add(1)
        timer := time.AfterFunc(time.Hour, group.Done)
        if !timer.Stop() || timer.Stop() { panic("stop callback timer") }
        if timer.Reset(time.Millisecond) { panic("reset stopped callback timer") }
        group.Wait()
    case 16:
        // Reset after a callback starts permits a second callback to overlap.
        // The first remains accepted work until its actual goroutine exits.
        started, second, release := make(chan struct{}), make(chan struct{}), make(chan struct{})
        var calls atomic.Uint32
        var group sync.WaitGroup
        group.Add(2)
        timer := time.AfterFunc(time.Millisecond, func(){
            defer group.Done()
            switch calls.Add(1) {
            case 1: close(started); <-release
            case 2: close(second)
            default: panic("extra callback")
            }
        })
        <-started
        if timer.Reset(time.Millisecond) { panic("reset running callback timer") }
        <-second
        close(release)
        group.Wait()
    case 17:
        deadline, cancel := context.WithTimeout(context.Background(), time.Hour)
        cancel()
        <-deadline.Done()
        if deadline.Err() != context.Canceled { panic("canceled context became elapsed timer") }
        <-time.After(time.Millisecond)
    }
    return 42
}

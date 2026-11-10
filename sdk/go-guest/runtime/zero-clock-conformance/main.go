package export_tests_caller_api

import "time"

// Run exercises ordinary Go timers at shared clock edges.
func Run(which uint32) uint32 {
    switch which {
    case 0:
        timer := time.NewTimer(5 * time.Nanosecond)
        <-timer.C
        if timer.Stop() { panic("elapsed timer was still active") }
        return 42
    case 1:
        // The owner controls the shared clock and observes the actual pending
        // timer waits at 5, 10 and 30 ns; no application sleeps or explicit yields.
        ticker := time.NewTicker(5 * time.Nanosecond)
        defer ticker.Stop()
        first := <-ticker.C
        second := <-ticker.C
        if !second.After(first) { panic("ticker time did not advance") }
        select { case <-ticker.C: panic("missed ticks replayed"); default: }
        third := <-ticker.C
        if !third.After(second) { panic("ticker time did not advance again") }
        return 42
    default:
        panic("unreviewed zero-clock mode")
    }
}

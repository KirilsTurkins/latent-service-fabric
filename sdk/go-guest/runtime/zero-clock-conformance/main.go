package export_tests_caller_api

import "time"

// Run exercises the ordinary Go one-shot channel at the shared clock edge.
func Run(which uint32) uint32 {
    if which != 0 { panic("unreviewed zero-clock mode") }
    timer := time.NewTimer(5 * time.Nanosecond)
    <-timer.C
    if timer.Stop() { panic("elapsed timer was still active") }
    return 42
}

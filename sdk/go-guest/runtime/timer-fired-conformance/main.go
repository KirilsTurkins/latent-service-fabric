package export_tests_caller_api

import "time"

// This source provides public operations only; the signed host observer must
// separately prove the original timer-next stayed physically live.
func Run(which uint32) uint32 {
	if which > 1 {
		panic("unsupported fired timer case")
	}
	target := time.NewTimer(250 * time.Millisecond)
	fired := make(chan struct{})
	go func() { <-target.C; close(fired) }()
	// An independent activation wait allows the timer heap to advance even
	// when the diagnostic host holds the original timer-next after expiry.
	time.Sleep(500 * time.Millisecond)
	<-fired
	marker := time.NewTimer(time.Hour)
	if which == 0 {
		if target.Stop() {
			panic("already fired timer reported active")
		}
	} else {
		if target.Reset(time.Hour) {
			panic("already fired timer reset reported active")
		}
		if !target.Stop() {
			panic("replacement timer failed to stop")
		}
	}
	if !marker.Stop() {
		panic("marker timer unexpectedly fired")
	}
	return 42
}

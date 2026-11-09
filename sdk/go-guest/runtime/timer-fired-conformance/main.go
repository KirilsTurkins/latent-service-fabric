package export_tests_caller_api

import "time"

// This source uses public operations only. The selected signed observer must
// independently prove the original wait and canonical subtask ordering.
func Run(which uint32) uint32 {
	if which > 3 {
		panic("unsupported fired timer case")
	}
	if which >= 2 {
		// The diagnostic owner selects this distinctive ordinary ticker and
		// proves the returned event and fence ordering independently.
		target := time.NewTicker(251 * time.Millisecond)
		<-target.C
		if which == 3 { target.Reset(time.Hour) }
		target.Stop()
		marker := time.NewTimer(time.Hour)
		if !marker.Stop() { panic("returned ticker marker") }
		return 42
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

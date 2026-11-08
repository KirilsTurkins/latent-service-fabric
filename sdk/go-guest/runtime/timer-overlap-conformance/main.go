package export_tests_caller_api

import (
	"runtime"
	"time"
)

type result struct {
	worker uint8
	active bool
}

// Run is deliberately finite. The host witness, not this source's sleep or
// channel order, establishes that both calls overlap an actual timer-next.
func Run(which uint32) uint32 {
	if which > 3 {
		panic("unsupported overlap case")
	}
	target := time.NewTimer(time.Hour)
	release := make(chan struct{})
	watcherDone := make(chan struct{})
	go func() {
		defer close(watcherDone)
		select {
		case <-target.C:
			panic("stale timer delivery")
		case <-release:
		}
	}()
	// This wait allows the ordinary timer heap owner to enter timer-next; it
	// does not itself count as evidence that the next wait is live.
	time.Sleep(50 * time.Millisecond)
	markers := make(chan struct{}, 2)
	results := make(chan result, 2)
	continueSecond := make(chan struct{}, 1)
	go func() {
		marker := time.NewTimer(time.Hour)
		if !marker.Stop() {
			panic("first marker timer")
		}
		markers <- struct{}{}
		results <- result{1, target.Reset(time.Hour)}
	}()
	<-markers
	go func() {
		marker := time.NewTimer(time.Hour)
		if !marker.Stop() {
			panic("second marker timer")
		}
		if which >= 2 {
			// The host witness accepts this marker only after the first
			// worker parks with the original provider wait still pending.
			// The second worker then collects before it enters Reset/Stop.
			var before, after runtime.MemStats
			runtime.ReadMemStats(&before)
			runtime.GC()
			runtime.ReadMemStats(&after)
			if before.NumGC == after.NumGC {
				panic("forced collection did not complete")
			}
			// Its distinctive periodic owner is observed by the host only
			// after GC returns. A park inside GC cannot release the wait.
			collected := time.NewTicker(37 * time.Minute)
			collected.Stop()
		}
		markers <- struct{}{}
		if which >= 2 {
			// The root observes this only after the GC marker's Stop has
			// returned, then admits a distinct root-owned marker before
			// allowing this worker to reach the target operation.
			<-continueSecond
		}
		if which%2 == 0 {
			results <- result{2, target.Reset(time.Hour)}
		} else {
			results <- result{2, target.Stop()}
		}
	}()
	<-markers
	var releaseMarker *time.Ticker
	if which >= 2 {
		releaseMarker = time.NewTicker(41 * time.Minute)
		continueSecond <- struct{}{}
	}
	one, two := <-results, <-results
	if one.worker == two.worker {
		panic("duplicate worker result")
	}
	if one.worker == 2 {
		one, two = two, one
	}
	if one.worker != 1 || two.worker != 2 || !two.active {
		panic("public timer result")
	}
	if which%2 == 0 {
		if !one.active || !target.Stop() {
			panic("final reset timer stop")
		}
	} else if target.Stop() == one.active {
		// Native Go is allowed to schedule Stop first, in which case Reset
		// reports false and leaves the timer active. The signed host witness
		// requires the opposite order and therefore requires result 42.
		panic("reset/stop final state")
	}
	close(release)
	<-watcherDone
	if releaseMarker != nil {
		releaseMarker.Stop()
	}
	if which%2 == 1 && !one.active {
		return 43
	}
	return 42
}

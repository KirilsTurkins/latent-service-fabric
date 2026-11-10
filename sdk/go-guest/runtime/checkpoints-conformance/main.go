package export_tests_caller_api

import (
	"sync"
	"sync/atomic"
)

var invocationCount uint32

func recursiveWait(flag *atomic.Uint32) {
	if flag.Load() == 0 { recursiveWait(flag) }
}

//go:nosplit
func nonSuspendable() { for {} }

// No application Gosched, polling adapter or LSF runtime facade is supplied.
func Run(which uint32) uint32 {
	invocationCount++
	if invocationCount != 1 { panic("cross-invocation state") }
	if which == 2 { for {} }
	if which == 3 { nonSuspendable() }
	if which == 4 { return 42 }
	if which == 5 || which == 6 {
		var release, result atomic.Uint32
		started := make(chan struct{})
		var group sync.WaitGroup
		group.Add(1)
		go func() {
			defer group.Done()
			close(started)
			if which == 6 { result.Store(42); return }
		again:
			if release.Load() == 0 { goto again }
			result.Store(42)
		}()
		<-started
		release.Store(1)
		group.Wait()
		return result.Load()
	}
	var started, finish, result atomic.Uint32
	var group sync.WaitGroup
	group.Add(2)
	if which == 1 {
		go func() { defer group.Done(); started.Store(1) }()
		go func() { defer group.Done(); recursiveWait(&started); result.Store(42) }()
	} else {
		go func() {
			defer group.Done()
			started.Store(1)
			for finish.Load() == 0 {}
			result.Store(42)
		}()
		go func() {
			defer group.Done()
			for started.Load() == 0 {}
			finish.Store(1)
		}()
	}
	group.Wait()
	return result.Load()
}

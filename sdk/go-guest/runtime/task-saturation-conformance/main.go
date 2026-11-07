package export_tests_caller_api

import "sync"

var initialized = func() uint32 { return 42 }()
var calls uint32

// Run uses only ordinary goroutines and channels. Each worker is known to have
// started and stays owned until the caller closes release. The eighth start is
// attempted only after the first seven have acknowledged their original work.
func Run(which uint32) uint32 {
	calls++
	if calls != 1 || initialized != 42 {
		panic("task saturation requires fresh initialization")
	}
	if which > 1 {
		panic("unknown task saturation case")
	}
	ready, release := make(chan struct{}), make(chan struct{})
	var workers sync.WaitGroup
	workers.Add(7)
	for range 7 {
		go func() {
			defer workers.Done()
			ready <- struct{}{}
			<-release
		}()
	}
	for range 7 {
		<-ready
	}
	if which == 1 {
		go func() { <-release }()
		panic("task ceiling did not refuse the eighth worker")
	}
	close(release)
	workers.Wait()
	return 42
}

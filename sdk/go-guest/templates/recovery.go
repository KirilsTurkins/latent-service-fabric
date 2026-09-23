// lsf-example-begin: capsule
package export_examples_recovery_api

import "runtime"

var calls uint32
var retained [][]byte

func Run(which uint32) uint32 {
	calls++
	switch which {
	case 1:
		panic("requested trap")
	case 2:
		for {
			retained = append(retained, make([]byte, 1024*1024))
			runtime.KeepAlive(retained)
		}
	case 3:
		// Rendezvous with four real workers, then retain their blocked channels
		// while the main goroutine exhausts fuel. An endless scheduling loop
		// would also hammer the explicitly authorized host clock capability.
		// Whole-Store cleanup must reclaim every blocked worker and its stack.
		work := make(chan uint32, 4)
		parked := make(chan struct{})
		for worker := uint32(0); worker < 4; worker++ {
			go func(value uint32) {
				work <- value
				<-parked
			}(worker)
		}
		for worker := 0; worker < 4; worker++ {
			calls += <-work
		}
		runtime.Gosched()
		for {
			calls++
		}
	}
	return calls
}

// lsf-example-end: capsule

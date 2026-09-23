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
		// Fixed guest goroutines exercise scheduler and channel ownership.
		// The host's fuel/deadline/cancellation bounds reclaim this whole Store.
		work := make(chan uint32, 4)
		for worker := uint32(0); worker < 4; worker++ {
			go func(value uint32) {
				for {
					work <- value
				}
			}(worker)
		}
		for value := range work {
			calls += value
		}
	}
	return calls
}

// lsf-example-end: capsule

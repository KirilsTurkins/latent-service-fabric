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
		for {
			calls++
		}
	}
	return calls
}

// lsf-example-end: capsule

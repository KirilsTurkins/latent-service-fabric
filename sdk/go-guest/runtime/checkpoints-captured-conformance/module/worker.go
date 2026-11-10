package worker

import "sync/atomic"

// Spin signals only after entering the dependency. No application yield or
// injected transport is involved in the cooperative scheduling witness.
func Spin(started chan<- struct{}, release *atomic.Uint32, spin bool) {
	close(started)
	if !spin { return }
again:
	if release.Load() == 0 { goto again }
}

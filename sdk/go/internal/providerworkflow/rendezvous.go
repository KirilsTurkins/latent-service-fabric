package providerworkflow

import (
	"context"
	"errors"
	"os"
	"time"
)

const (
	// Preprepared HTTP dispatch is held beyond the original activation deadline.
	// This must expire before the guest's independent 1000 ms HTTP timeout;
	// otherwise that timeout traps the guest before activation expiry is observed.
	heldDeadlineBudget = 500 * time.Millisecond
	heldWaitBudget     = 2500 * time.Millisecond
)

var errInvocationBeforeMarker = errors.New("participant-invocation-ended-before-rendezvous")

// waitMarker observes physical upstream activity, not merely RPC dispatch.
// A nil retired channel is used for closure: local invocation retirement does
// not prove that the provider has physically closed its upstream connection.
func waitMarker(parent context.Context, path string, retired <-chan struct{}) error {
	ctx, cancel := context.WithTimeout(parent, heldWaitBudget)
	defer cancel()
	ticker := time.NewTicker(5 * time.Millisecond)
	defer ticker.Stop()
	for {
		if present, failure := privateMarker(path); failure != nil || present {
			return failure
		}
		select {
		case <-ctx.Done():
			return errors.New("participant-private-rendezvous-timeout")
		case <-retired:
			// The marker can be published between the first check and retirement.
			// Recheck after receiving the close before declaring an early result.
			if present, failure := privateMarker(path); failure != nil || present {
				return failure
			}
			return errInvocationBeforeMarker
		case <-ticker.C:
		}
	}
}

func privateMarker(path string) (bool, error) {
	info, failure := os.Lstat(path)
	if errors.Is(failure, os.ErrNotExist) {
		return false, nil
	}
	if failure != nil {
		return false, errors.New("participant-private-rendezvous-read-failed")
	}
	if !info.Mode().IsRegular() || info.Size() > 64 {
		return false, errors.New("participant-invalid-private-rendezvous")
	}
	return true, nil
}

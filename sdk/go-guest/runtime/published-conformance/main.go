package export_tests_caller_api

import (
	"context"
	"errors"
	"sync/atomic"
	"time"

	"github.com/cenkalti/backoff/v4"
	"github.com/reactivex/rxgo/v2"
)

// Run uses the libraries' ordinary goroutines and default timer implementation.
// Its retry operation has no external effect: failed attempts emit only an error.
func Run(which uint32) uint32 {
	var attempts atomic.Uint32
	retryError := errors.New("reviewed retry fixture")
	source := rxgo.Defer([]rxgo.Producer{func(ctx context.Context, next chan<- rxgo.Item) {
		n := attempts.Add(1)
		if which != 0 || n < 4 {
			rxgo.Error(retryError).SendContext(ctx, next)
			return
		}
		rxgo.Of(uint32(42)).SendContext(ctx, next)
	}})
	delay := 5 * time.Millisecond
	if which == 1 || which == 3 {
		delay = time.Hour
	}
	var policy backoff.BackOff = backoff.WithMaxRetries(backoff.NewConstantBackOff(delay), 3)
	if which == 3 {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		time.AfterFunc(5*time.Millisecond, cancel)
		policy = backoff.WithContext(policy, ctx)
	}
	values, failures := 0, 0
	for item := range source.BackOffRetry(policy).Observe() {
		if item.Error() {
			if which == 0 || which == 2 && item.E != retryError ||
				which == 3 && !errors.Is(item.E, context.Canceled) {
				panic("unexpected published retry error")
			}
			failures++
			continue
		}
		if item.V != uint32(42) || which != 0 {
			panic("unexpected published retry value")
		}
		values++
	}
	if which == 0 && (attempts.Load() != 4 || values != 1 || failures != 0) ||
		which == 2 && (attempts.Load() != 4 || values != 0 || failures != 1) ||
		which == 3 && (attempts.Load() != 1 || values != 0 || failures != 1) || which == 1 {
		panic("published worker/timer result changed")
	}
	return 42
}

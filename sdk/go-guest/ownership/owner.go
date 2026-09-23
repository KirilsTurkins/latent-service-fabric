// Package ownership keeps one explicit owner across Go aliases and async calls.
// It adds no finalizer, goroutine, provider, grant or retry. An invalid borrow
// panics; the activation boundary, not a fabricated WIT error, contains misuse.
package ownership

import "sync/atomic"

type cell[T any] struct {
	state atomic.Uint32 // 0 available, 1 borrowed, 2 consumed
	value T
}

// Owner copies share the same state. The zero value is deliberately unusable.
type Owner[T any] struct { cell *cell[T] }

func New[T any](value T) Owner[T] { return Owner[T]{&cell[T]{value: value}} }

func (o Owner[T]) Borrow() (T, func()) {
	if o.cell == nil || !o.cell.state.CompareAndSwap(0, 1) { panic("lsf: owner busy or consumed") }
	var released atomic.Bool
	return o.cell.value, func() {
		if !released.CompareAndSwap(false, true) || !o.cell.state.CompareAndSwap(1, 0) {
			panic("lsf: borrow already released")
		}
	}
}

func (o Owner[T]) Take() T {
	if o.cell == nil || !o.cell.state.CompareAndSwap(0, 2) { panic("lsf: owner busy or consumed") }
	value := o.cell.value
	var empty T
	o.cell.value = empty
	return value
}

// Close is idempotent after consumption but rejects an outstanding borrow.
// The destructor runs exactly once, including if it panics.
func (o Owner[T]) Close(drop func(T)) {
	if o.cell == nil { panic("lsf: zero owner") }
	if o.cell.state.Load() == 2 { return }
	drop(o.Take())
}

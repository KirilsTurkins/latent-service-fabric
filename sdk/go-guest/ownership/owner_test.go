package ownership

import "testing"

func mustPanic(t *testing.T, f func()) {
	t.Helper()
	defer func() {
		if recover() == nil {
			t.Fatal("ownership violation accepted")
		}
	}()
	f()
}

func TestAliasesShareExactlyOneDestructor(t *testing.T) {
	o := New(42)
	alias := o
	calls := 0
	drop := func(value int) {
		calls++
		if value != 42 {
			t.Fatal(value)
		}
	}
	o.Close(drop)
	alias.Close(drop)
	if calls != 1 {
		t.Fatal(calls)
	}
	mustPanic(t, func() { alias.Take() })
	mustPanic(t, func() { alias.Borrow() })
}

func TestPendingBorrowPreventsCloseMoveAndConcurrentBorrow(t *testing.T) {
	o := New(42)
	value, release := o.Borrow()
	if value != 42 {
		t.Fatal(value)
	}
	mustPanic(t, func() { o.Close(func(int) { t.Fatal("dropped while pending") }) })
	mustPanic(t, func() { o.Take() })
	mustPanic(t, func() { o.Borrow() })
	release()
	mustPanic(t, release)
	if o.Take() != 42 {
		t.Fatal("borrow corrupted value")
	}
}

func TestDeferredBorrowReleaseSurvivesDeclaredErrorAndPanic(t *testing.T) {
	o := New(42)
	use := func(fail bool) bool {
		_, release := o.Borrow()
		defer release()
		if fail {
			panic("application failure")
		}
		return false
	}
	if use(false) {
		t.Fatal("declared error changed")
	}
	mustPanic(t, func() { use(true) })
	if o.Take() != 42 {
		t.Fatal("borrow leaked")
	}
}

func TestOldReleaseCannotRefundAnotherBorrow(t *testing.T) {
	o := New(42)
	_, first := o.Borrow()
	first()
	_, second := o.Borrow()
	mustPanic(t, first)
	mustPanic(t, func() { o.Take() })
	second()
	if o.Take() != 42 {
		t.Fatal("wrong owner released")
	}
}

func TestFailingDestructorIsNeverRetried(t *testing.T) {
	o := New(42)
	mustPanic(t, func() { o.Close(func(int) { panic("uncertain effect") }) })
	o.Close(func(int) { t.Fatal("effect retried") })
}

func TestZeroOwnerCannotFabricateAResource(t *testing.T) {
	var o Owner[uint64]
	mustPanic(t, func() { o.Take() })
	mustPanic(t, func() { o.Borrow() })
	mustPanic(t, func() { o.Close(func(uint64) {}) })
}

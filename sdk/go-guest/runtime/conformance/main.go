package export_tests_caller_api

import (
	"runtime"
	"sync"
	"time"
)

var invocationCount uint32

// This is ordinary Go source. The compiler supplies the activation ownership
// and dispatcher hooks; the application imports no LSF runtime facade.
func Run(which uint32) uint32 {
	invocationCount++
	if invocationCount != 1 { panic("cross-invocation state") }
	switch which {
	case 1:
		go func() { time.Sleep(time.Millisecond); panic("accepted sibling failed") }()
		return 42
	case 2:
		for i := 0; i < 100; i++ { go func() { select {} }() }
		return 42
	case 3:
		time.NewTimer(time.Second)
		return 42
	case 4:
		go func() { time.Sleep(30 * time.Millisecond) }()
		return 42
	case 5:
		go func() {
			time.Sleep(time.Millisecond)
			go func() { time.Sleep(time.Millisecond) }()
		}()
		return 42
	case 6:
		go func() { select {} }()
		return 42
	case 7:
		time.Sleep(10 * time.Second)
		panic("root deadline reported elapsed success")
	case 8:
		runtime.SetFinalizer(new(int), func(*int) {})
		return 42
	case 9:
		runtime.AddCleanup(new(int), func(int) {}, 0)
		return 42
	}
	var group sync.WaitGroup
	var mutex sync.Mutex
	var result uint32
	ready := make(chan uint32, 1)
	group.Add(2)
	go func() {
		defer group.Done()
		time.Sleep(time.Millisecond)
		mutex.Lock()
		result = 40
		mutex.Unlock()
		ready <- 2
	}()
	go func() {
		defer group.Done()
		select {
		case value := <-ready:
			mutex.Lock()
			result += value
			mutex.Unlock()
		}
	}()
	group.Wait()
	return result
}

package export_tests_caller_api

import (
	"sync"
	"sync/atomic"
	"time"
)

var invocationCount uint32

// Ordinary application source: the captured compiler owns suspension and
// original activation admission. No application yield or executor is supplied.
func Run(which uint32) uint32 {
	invocationCount++
	if invocationCount != 1 {
		panic("synchronization state crossed an activation")
	}
	switch which {
	case 0:
		condition(false)
	case 1:
		readersAndWriter()
	case 2:
		onceWaiters()
	case 3:
		oncePanic()
	case 4:
		closedChannelSelect()
	case 5:
		condition(true)
	case 6:
		lateCondition()
	case 7:
		blockedCondition()
	case 8:
		blockedCondition()
		time.Sleep(10 * time.Second)
		panic("original root cancellation or deadline returned success")
	case 9:
		atomicSibling()
	default:
		panic("unknown synchronization mode")
	}
	return 42
}

func condition(signalFirst bool) {
	var mutex sync.Mutex
	cond := sync.NewCond(&mutex)
	ready := make(chan struct{}, 2)
	complete := make(chan uint32, 2)
	var group sync.WaitGroup
	var permits, value uint32
	group.Add(2)
	for index := 0; index < 2; index++ {
		go func() {
			defer group.Done()
			mutex.Lock()
			ready <- struct{}{}
			for permits == 0 {
				cond.Wait()
			}
			permits--
			observed := value
			mutex.Unlock()
			complete <- observed
		}()
	}
	<-ready
	<-ready
	// Reacquiring the same lock proves both ready senders released it in Wait.
	mutex.Lock()
	value = 42
	if signalFirst {
		permits = 1
		cond.Signal()
	} else {
		permits = 2
		cond.Broadcast()
	}
	mutex.Unlock()
	if <-complete != 42 {
		panic("condition did not publish protected state")
	}
	if signalFirst {
		mutex.Lock()
		permits = 1
		cond.Broadcast()
		mutex.Unlock()
	}
	if <-complete != 42 {
		panic("condition lost its second waiter")
	}
	group.Wait()
}

func readersAndWriter() {
	var mutex sync.RWMutex
	var readers atomic.Int32
	var value uint32
	ready := make(chan struct{}, 2)
	release := make(chan struct{})
	writerStarted := make(chan struct{})
	var group sync.WaitGroup
	group.Add(3)
	for index := 0; index < 2; index++ {
		go func() {
			defer group.Done()
			mutex.RLock()
			readers.Add(1)
			ready <- struct{}{}
			<-release
			if value != 0 {
				panic("writer overlapped an original reader")
			}
			readers.Add(-1)
			mutex.RUnlock()
		}()
	}
	<-ready
	<-ready
	go func() {
		defer group.Done()
		close(writerStarted)
		mutex.Lock()
		if readers.Load() != 0 {
			panic("writer entered with live readers")
		}
		value = 42
		mutex.Unlock()
	}()
	<-writerStarted
	close(release)
	group.Wait()
	mutex.RLock()
	defer mutex.RUnlock()
	if value != 42 {
		panic("reader did not observe the completed writer")
	}
}

func onceWaiters() {
	var once sync.Once
	var calls, value uint32
	entered := make(chan struct{})
	release := make(chan struct{})
	attempted := make(chan struct{}, 2)
	var group sync.WaitGroup
	initialize := func() {
		calls++
		close(entered)
		<-release
		value = 42
	}
	worker := func() {
		defer group.Done()
		once.Do(initialize)
		if value != 42 {
			panic("Once returned before initializer publication")
		}
	}
	group.Add(3)
	go worker()
	<-entered
	for index := 0; index < 2; index++ {
		go func() {
			attempted <- struct{}{}
			worker()
		}()
	}
	<-attempted
	<-attempted
	close(release)
	group.Wait()
	if calls != 1 {
		panic("Once ran the initializer more than once")
	}
}

func oncePanic() {
	var once sync.Once
	var calls uint32
	func() {
		defer func() {
			if recover() != "original once panic" {
				panic("Once did not preserve its original panic")
			}
		}()
		once.Do(func() {
			calls++
			panic("original once panic")
		})
	}()
	once.Do(func() { calls++ })
	if calls != 1 {
		panic("Once repeated a panicking initializer")
	}
}

func closedChannelSelect() {
	values := make(chan uint32, 2)
	var published uint32
	go func() {
		values <- 20
		values <- 22
		published = 42
		close(values)
	}()
	var sum uint32
	for value := range values {
		sum += value
	}
	if sum != 42 || published != 42 {
		panic("channel close lost buffered values or publication")
	}
	var disabled <-chan uint32
	select {
	case <-disabled:
		panic("nil select case became runnable")
	case value, ok := <-values:
		if value != 0 || ok {
			panic("closed channel did not preserve zero and false")
		}
	}
}

func parkedCondition() (*sync.Cond, *uint32) {
	cond := sync.NewCond(new(sync.Mutex))
	value := new(uint32)
	ready := make(chan struct{})
	go func() {
		cond.L.Lock()
		close(ready)
		for *value == 0 {
			cond.Wait()
		}
		if *value != 42 {
			panic("late condition state was not published")
		}
		cond.L.Unlock()
	}()
	<-ready
	cond.L.Lock()
	cond.L.Unlock()
	return cond, value
}

func blockedCondition() {
	parkedCondition()
}

func lateCondition() {
	cond, value := parkedCondition()
	go func() {
		time.Sleep(30 * time.Millisecond)
		cond.L.Lock()
		*value = 42
		cond.Broadcast()
		cond.L.Unlock()
	}()
}

func atomicSibling() {
	var published, observed atomic.Uint32
	entered := make(chan struct{})
	done := make(chan struct{})
	go func() {
		close(entered)
		for published.Load() == 0 {
		}
		observed.Store(42)
		close(done)
	}()
	<-entered
	go func() { published.Store(1) }()
	<-done
	if observed.Load() != 42 {
		panic("synchronized CPU sibling failed to progress")
	}
}

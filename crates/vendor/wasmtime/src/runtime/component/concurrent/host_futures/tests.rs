use super::*;
use crate::NativeAllocation;
use alloc::boxed::Box;
use alloc::sync::Arc as Shared;
use alloc::vec::Vec;
use core::cell::RefCell;
use core::future::Future;
use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering::SeqCst};
use core::task::Waker;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Mutex;

// Observe the REAL raw deallocator's return, without changing header layout.
// Per-thread events avoid cross-test races or a new product/accounting owner.
std::thread_local! {
    static EVENTS: RefCell<Vec<(&'static str, usize)>> = const { RefCell::new(Vec::new()) };
}
pub(super) fn physical_deallocation(bytes: usize) {
    EVENTS.with(|events| events.borrow_mut().push(("deallocated", bytes)));
}
fn reset_events() {
    EVENTS.with(|events| events.borrow_mut().clear());
}

#[derive(Default)]
struct Probe {
    requests: AtomicUsize,
    live: AtomicUsize,
    confirmations: AtomicUsize,
    refunds: AtomicUsize,
    refuse: AtomicUsize,
    panic_confirmation: AtomicBool,
    dropped: AtomicUsize,
    sizes: Mutex<Vec<usize>>,
}
struct Allocation {
    probe: Shared<Probe>,
    bytes: usize,
    confirmed: bool,
}
impl NativeAllocation for Allocation {
    fn allocated(&mut self) {
        self.confirmed = true;
        self.probe.confirmations.fetch_add(1, SeqCst);
        assert!(
            !self.probe.panic_confirmation.load(SeqCst),
            "paid-header-confirmation-control"
        );
    }
}
impl Drop for Allocation {
    fn drop(&mut self) {
        if self.confirmed {
            EVENTS.with(|events| {
                let mut events = events.borrow_mut();
                assert_eq!(events.last(), Some(&("deallocated", self.bytes)));
                events.push(("refund", self.bytes));
            });
        }
        assert!(self.probe.live.fetch_sub(self.bytes, SeqCst) >= self.bytes);
        self.probe.refunds.fetch_add(1, SeqCst);
    }
}
struct Memory(Shared<Probe>);
impl crate::NativeMemory for Memory {
    fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
        let request = self.0.requests.fetch_add(1, SeqCst) + 1;
        self.0.sizes.lock().unwrap().push(bytes);
        if request == self.0.refuse.load(SeqCst) {
            crate::bail!("original-future-header-refusal-control");
        }
        self.0.live.fetch_add(bytes, SeqCst);
        Ok(Box::new(Allocation {
            probe: self.0.clone(),
            bytes,
            confirmed: false,
        }))
    }
}
fn memory(probe: &Shared<Probe>) -> crate::runtime::native_memory::Memory {
    Some(Shared::new(Memory(probe.clone())))
}

#[repr(align(64))]
struct Aligned(u8);

#[test]
fn paid_header_exact_layout_refusal_confirmation_and_last_weak_refund() {
    reset_events();
    let probe = Shared::new(Probe::default());
    let memory = memory(&probe);
    let layout = paid_arc::Arc::<Aligned>::layout();
    probe.refuse.store(1, SeqCst);
    assert!(paid_arc::Arc::new(&memory, Aligned(9)).is_err());
    assert_eq!(probe.live.load(SeqCst), 0);
    probe.panic_confirmation.store(true, SeqCst);
    assert!(
        catch_unwind(AssertUnwindSafe(|| {
            let _ = paid_arc::Arc::new(&memory, Aligned(9));
        }))
        .is_err()
    );
    assert_eq!(probe.live.load(SeqCst), 0);
    probe.panic_confirmation.store(false, SeqCst);
    let value = paid_arc::Arc::new(&memory, Aligned(9)).unwrap();
    assert_eq!(value.0, 9);
    assert_eq!(paid_arc::Arc::as_ptr(&value) as usize % layout.align(), 0);
    let weak = paid_arc::Arc::downgrade(&value);
    let other_weak = weak.clone();
    drop(value);
    assert!(weak.upgrade().is_none());
    assert_eq!(probe.live.load(SeqCst), layout.size());
    drop(weak);
    assert_eq!(probe.live.load(SeqCst), layout.size());
    drop(other_weak);
    assert_eq!(probe.live.load(SeqCst), 0);
    assert!(
        probe
            .sizes
            .lock()
            .unwrap()
            .iter()
            .all(|size| *size == layout.size())
    );
}

struct Value {
    probe: Shared<Probe>,
    panic_drop: bool,
}
impl Drop for Value {
    fn drop(&mut self) {
        assert_ne!(self.probe.live.load(SeqCst), 0);
        self.probe.dropped.fetch_add(1, SeqCst);
        assert!(!self.panic_drop, "paid-header-payload-destructor-control");
    }
}

#[test]
fn paid_header_raw_token_and_destructor_unwind_retain_same_charge() {
    reset_events();
    let probe = Shared::new(Probe::default());
    let memory = memory(&probe);
    let value = paid_arc::Arc::new(
        &memory,
        Value {
            probe: probe.clone(),
            panic_drop: false,
        },
    )
    .unwrap();
    let weak = paid_arc::Arc::downgrade(&value);
    let raw = paid_arc::Arc::into_raw(value.clone());
    let restored = unsafe { paid_arc::Arc::from_raw(raw) };
    assert_eq!(raw, paid_arc::Arc::as_ptr(&restored));
    let upgraded = weak.upgrade().unwrap();
    drop((restored, value, upgraded));
    assert_eq!(probe.dropped.load(SeqCst), 1);
    assert!(weak.upgrade().is_none());
    drop(weak);
    assert_eq!(probe.live.load(SeqCst), 0);
    let value = paid_arc::Arc::new(
        &memory,
        Value {
            probe: probe.clone(),
            panic_drop: true,
        },
    )
    .unwrap();
    let weak = paid_arc::Arc::downgrade(&value);
    assert!(catch_unwind(AssertUnwindSafe(|| drop(value))).is_err());
    assert!(weak.upgrade().is_none());
    drop(weak); // implicit weak remains: SAME physical allocation/charge retained.
    assert_eq!(probe.requests.load(SeqCst), 2);
    assert_eq!(probe.refunds.load(SeqCst), 1);
    assert_eq!(
        probe.live.load(SeqCst),
        paid_arc::Arc::<Value>::layout().size()
    );
    assert_eq!(probe.dropped.load(SeqCst), 2);
}

struct TestFuture {
    waker: Shared<Mutex<Option<Waker>>>,
    ready: Shared<AtomicBool>,
    polls: Shared<AtomicUsize>,
    panic_drop: bool,
}
impl Future for TestFuture {
    type Output = Result<()>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        self.polls.fetch_add(1, SeqCst);
        *self.waker.lock().unwrap() = Some(cx.waker().clone());
        if self.ready.load(SeqCst) {
            Poll::Ready(Ok(()))
        } else {
            Poll::Pending
        }
    }
}
impl Drop for TestFuture {
    fn drop(&mut self) {
        assert!(!self.panic_drop, "paid-unordered-future-destructor-control");
    }
}
fn future(
    panic_drop: bool,
) -> (
    HostTaskFuture,
    Shared<Mutex<Option<Waker>>>,
    Shared<AtomicBool>,
    Shared<AtomicUsize>,
) {
    let waker = Shared::new(Mutex::new(None));
    let ready = Shared::new(AtomicBool::new(false));
    let polls = Shared::new(AtomicUsize::new(0));
    (
        HostTaskFuture::legacy(Box::pin(TestFuture {
            waker: waker.clone(),
            ready: ready.clone(),
            polls: polls.clone(),
            panic_drop,
        })),
        waker,
        ready,
        polls,
    )
}

#[test]
fn paid_unordered_escaped_waker_keeps_task_and_last_weak_queue_backing() {
    reset_events();
    let probe = Shared::new(Probe::default());
    let memory = memory(&probe);
    let (task_layout, queue_layout) = paid::allocation_layouts::<HostTaskFuture>();
    let mut set = HostFutureSet::new(true);
    set.ensure(&memory).unwrap();
    let slot = TaskSlot::prepare(&memory).unwrap();
    let (future, waker, _, polls) = future(false);
    set.push_prepared(slot, future);
    assert!(
        Pin::new(&mut set)
            .poll_next(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    assert_eq!(polls.load(SeqCst), 1);
    drop(set);
    // Stub freed; task's escaped strong and its queue Weak keep BOTH headers.
    assert_eq!(
        probe.live.load(SeqCst),
        task_layout.size() + queue_layout.size()
    );
    let waker = waker.lock().unwrap().take().unwrap();
    let clone = waker.clone();
    clone.wake(); // queue upgrade is terminal None; no enqueue/allocation.
    waker.wake_by_ref();
    assert_eq!(probe.requests.load(SeqCst), 3);
    assert_eq!(
        probe.live.load(SeqCst),
        task_layout.size() + queue_layout.size()
    );
    drop(waker);
    assert_eq!(probe.live.load(SeqCst), 0);
    assert_eq!(probe.refunds.load(SeqCst), 3);
}

#[test]
fn paid_unordered_prepared_unused_and_wake_publish_make_no_new_admission() {
    reset_events();
    let probe = Shared::new(Probe::default());
    let memory = memory(&probe);
    let mut set = HostFutureSet::new(true);
    set.ensure(&memory).unwrap();
    let initial = probe.live.load(SeqCst);
    drop(TaskSlot::prepare(&memory).unwrap());
    assert_eq!(probe.live.load(SeqCst), initial);
    let slot = TaskSlot::prepare(&memory).unwrap();
    let (future, waker, ready, polls) = future(false);
    // All later original-memory reserve calls would fail. Wake/publish need none.
    probe.refuse.store(probe.requests.load(SeqCst) + 1, SeqCst);
    set.push_prepared(slot, future);
    let mut cx = Context::from_waker(Waker::noop());
    assert!(Pin::new(&mut set).poll_next(&mut cx).is_pending());
    let escaped = waker.lock().unwrap().take().unwrap();
    ready.store(true, SeqCst);
    escaped.wake_by_ref();
    match Pin::new(&mut set).poll_next(&mut cx) {
        Poll::Ready(Some(Ok(()))) => {}
        _ => panic!("ready task missing"),
    }
    assert_eq!(polls.load(SeqCst), 2);
    drop(escaped);
    drop(waker.lock().unwrap().take());
    drop(set);
    assert_eq!(probe.requests.load(SeqCst), 4);
    assert_eq!(probe.live.load(SeqCst), 0);
}

#[test]
fn paid_unordered_lazy_each_initialization_refusal_and_none_keep_original() {
    reset_events();
    let (task, ready_queue) = paid::allocation_layouts::<HostTaskFuture>();
    println!(
        "LSF_FUTURES_BACKING_LAYOUT_V1 task-bytes={} task-align={} ready-queue-bytes={} ready-queue-align={}",
        task.size(),
        task.align(),
        ready_queue.size(),
        ready_queue.align()
    );
    let work_queue =
        super::super::work_queue::allocation_layout_witness::<super::super::WorkItem>();
    println!(
        "LSF_WORK_QUEUE_LAYOUT_V1 bytes={} align={}",
        work_queue.size(),
        work_queue.align()
    );
    println!(
        "LSF_JOIN_STATE_LAYOUT_V1 bytes={}",
        super::super::abort::accounted_layout_witness()
    );
    for refuse in [1, 2] {
        let probe = Shared::new(Probe::default());
        let memory = memory(&probe);
        let mut set = HostFutureSet::new(true);
        assert_eq!(probe.requests.load(SeqCst), 0);
        probe.refuse.store(refuse, SeqCst);
        assert!(set.ensure(&memory).is_err());
        assert_eq!(probe.live.load(SeqCst), 0);
        assert!(matches!(set.0, Kind::Paid(None)));
        set.ensure(&memory).unwrap();
        drop(set);
        assert_eq!(probe.live.load(SeqCst), 0);
    }
    let mut original = HostFutureSet::new(false);
    original.ensure(&None).unwrap();
    let slot = TaskSlot::prepare(&None).unwrap();
    let (future, waker, ready, _) = future(false);
    ready.store(true, SeqCst);
    original.push_prepared(slot, future);
    assert!(matches!(
        Pin::new(&mut original).poll_next(&mut Context::from_waker(Waker::noop())),
        Poll::Ready(Some(Ok(())))
    ));
    drop((original, waker));
}

#[test]
fn paid_unordered_future_unwind_retains_original_queue_and_task_charges() {
    reset_events();
    let probe = Shared::new(Probe::default());
    let memory = memory(&probe);
    let mut set = HostFutureSet::new(true);
    set.ensure(&memory).unwrap();
    let slot = TaskSlot::prepare(&memory).unwrap();
    let (future, waker, _, _) = future(true);
    set.push_prepared(slot, future);
    // Keep the task in the ready queue, so release_task first transfers its
    // strong token before future Drop unwinds; upstream LeakQueueOnDrop retains
    // that queue and its stub. No destructor bomb is deliberately triggered.
    let before = probe.live.load(SeqCst);
    assert!(catch_unwind(AssertUnwindSafe(|| drop(set))).is_err());
    drop(waker);
    assert_eq!(probe.requests.load(SeqCst), 3);
    assert_eq!(probe.refunds.load(SeqCst), 0);
    assert_eq!(probe.live.load(SeqCst), before);
}

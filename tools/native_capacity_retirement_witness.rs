//! Observe the production native-capacity lease allocation and original charge.
//! Unsafe code is confined to this separate allocator witness.
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeCapacityError, NativeCapacityLimits,
    NativeCapacityOwner, NativeCapacityPartition, NativeReservationRequest,
    NATIVE_RESERVATION_METADATA_BYTES,
};
use std::alloc::{GlobalAlloc, Layout, System};
use std::future::{pending, Future};
use std::pin::Pin;
use std::ptr::null_mut;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicUsize, Ordering::SeqCst};
use std::sync::{Arc, Barrier};
use std::task::{Context, Poll, Wake, Waker};
use std::time::{Duration, Instant};

struct Allocator;
#[global_allocator]
static ALLOCATOR: Allocator = Allocator;
static CAPTURING: AtomicBool = AtomicBool::new(false);
static COUNT: AtomicUsize = AtomicUsize::new(0);
static ALLOCATION_SIZE: AtomicUsize = AtomicUsize::new(0);
static WATCH: AtomicPtr<u8> = AtomicPtr::new(null_mut());
static ARMED: AtomicBool = AtomicBool::new(false);
static ENTERED: AtomicBool = AtomicBool::new(false);
static RELEASE: AtomicBool = AtomicBool::new(false);
static FREED: AtomicBool = AtomicBool::new(false);

unsafe impl GlobalAlloc for Allocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if CAPTURING.load(SeqCst) && COUNT.fetch_add(1, SeqCst) == 0 {
            WATCH.store(pointer, SeqCst);
            ALLOCATION_SIZE.store(layout.size(), SeqCst);
        }
        pointer
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        if pointer == WATCH.load(SeqCst) && ARMED.swap(false, SeqCst) {
            ENTERED.store(true, SeqCst);
            while !RELEASE.load(SeqCst) {
                std::thread::yield_now();
            }
            unsafe { System.dealloc(pointer, layout) };
            FREED.store(true, SeqCst);
        } else {
            unsafe { System.dealloc(pointer, layout) };
        }
    }
}

#[derive(Default)]
struct Wakes(AtomicUsize);
impl Wake for Wakes {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, SeqCst);
    }
    fn wake_by_ref(self: &Arc<Self>) {
        self.0.fetch_add(1, SeqCst);
    }
}
struct PanicValue;
impl Drop for PanicValue {
    fn drop(&mut self) {
        panic!("controlled payload destructor panic");
    }
}

fn limits() -> NativeCapacityLimits {
    let part = NativeCapacityPartition {
        slots: 1,
        bytes: 4096,
        maximum_reservation_bytes: 4096,
    };
    NativeCapacityLimits {
        ordinary: part,
        recovery: part,
        maximum_lifetime: Duration::from_secs(30),
    }
}

fn wait_for_free() {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !ENTERED.load(SeqCst) && Instant::now() < deadline {
        std::thread::yield_now();
    }
    if !ENTERED.load(SeqCst) {
        RELEASE.store(true, SeqCst);
        panic!("native lease deallocator not reached");
    }
}

fn run(mode: &str) {
    let owner = NativeCapacityOwner::new(limits()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    let request = NativeReservationRequest::default();
    COUNT.store(0, SeqCst);
    WATCH.store(null_mut(), SeqCst);
    ENTERED.store(false, SeqCst);
    RELEASE.store(false, SeqCst);
    FREED.store(false, SeqCst);
    CAPTURING.store(true, SeqCst);
    let reservation = owner
        .reserve(NativeAdmissionClass::Ordinary, request, deadline)
        .unwrap();
    CAPTURING.store(false, SeqCst);
    assert_eq!(
        COUNT.load(SeqCst),
        1,
        "the actual reservation allocated an unexpected shape"
    );
    assert!(!WATCH.load(SeqCst).is_null());
    assert!(ALLOCATION_SIZE.load(SeqCst) as u64 <= NATIVE_RESERVATION_METADATA_BYTES);
    let charged = reservation.reserved_bytes();
    ARMED.store(true, SeqCst);

    let wakes = Arc::new(Wakes::default());
    let waker = Waker::from(wakes.clone());
    let mut context = Context::from_waker(&waker);
    let mut drain = if mode == "drain" {
        let mut future = Box::pin(owner.drain_async(deadline, pending()).unwrap());
        assert!(future.as_mut().poll(&mut context).is_pending());
        Some(future)
    } else {
        None
    };

    let mut workers = Vec::new();
    if mode == "concurrent" {
        let barrier = Arc::new(Barrier::new(9));
        for _ in 0..8 {
            let permit = reservation
                .reserve_buffer(NativeBufferClass::Work, 0)
                .unwrap();
            let barrier = barrier.clone();
            workers.push(std::thread::spawn(move || {
                barrier.wait();
                drop(permit);
            }));
        }
        drop(reservation);
        barrier.wait();
    } else if mode == "buffer" || mode == "panic-buffer" {
        let permit = reservation
            .reserve_buffer(NativeBufferClass::Work, 0)
            .unwrap();
        drop(reservation);
        if mode == "panic-buffer" {
            let buffer = permit.attach(PanicValue);
            workers.push(std::thread::spawn(move || {
                assert!(
                    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(buffer)))
                        .is_err()
                );
            }));
        } else {
            workers.push(std::thread::spawn(move || drop(permit)));
        }
    } else {
        workers.push(std::thread::spawn(move || drop(reservation)));
    }

    wait_for_free();
    let snapshot = owner.snapshot().unwrap();
    let held = snapshot.ordinary.slots == 1 && snapshot.ordinary.bytes == charged;
    let no_early_wake = wakes.0.load(SeqCst) == 0;
    let pending_while_allocated = drain
        .as_mut()
        .is_none_or(|future| matches!(Pin::as_mut(future).poll(&mut context), Poll::Pending));
    let refused = if drain.is_none() {
        matches!(
            owner.reserve(NativeAdmissionClass::Ordinary, request, deadline),
            Err(NativeCapacityError::SlotsFull)
        )
    } else {
        true
    };
    RELEASE.store(true, SeqCst);
    for worker in workers {
        worker.join().unwrap();
    }
    assert!(FREED.load(SeqCst));
    assert!(owner.snapshot().unwrap().physically_retired());
    if let Some(future) = drain.as_mut() {
        assert!(wakes.0.load(SeqCst) > 0);
        assert!(
            matches!(Pin::as_mut(future).poll(&mut context), Poll::Ready(report) if report.clean)
        );
    }
    assert!(held && refused && no_early_wake && pending_while_allocated,
        "mode={mode} held={held} refused={refused} no_early_wake={no_early_wake} pending={pending_while_allocated}");
    println!(
        "mode={mode} actual lease Arc={} bytes, original reservation held through deallocation",
        ALLOCATION_SIZE.load(SeqCst)
    );
}

fn main() {
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        if info.payload().downcast_ref::<&str>().copied()
            != Some("controlled payload destructor panic")
        {
            default_hook(info);
        }
    }));
    for mode in ["direct", "buffer", "panic-buffer", "concurrent", "drain"] {
        run(mode);
    }
}

//! Bounded test-only allocator observation of the actual stack context.
#![cfg(all(
    test,
    target_os = "linux",
    target_arch = "x86_64",
    feature = "development-stack-custody-witness",
    not(feature = "development-go-timer-overlap")
))]

use super::*;
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicUsize, Ordering::SeqCst};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

const MAX_CAPTURE: usize = 256;
thread_local! {
    // Unrelated libtest threads must neither fill nor race the capture slots.
    static CAPTURING: Cell<bool> = const { Cell::new(false) };
}
static CAPTURE_COUNT: AtomicUsize = AtomicUsize::new(0);
static POINTERS: [AtomicPtr<u8>; MAX_CAPTURE] =
    [const { AtomicPtr::new(std::ptr::null_mut()) }; MAX_CAPTURE];
static SIZES: [AtomicUsize; MAX_CAPTURE] = [const { AtomicUsize::new(0) }; MAX_CAPTURE];
static WATCH: AtomicPtr<u8> = AtomicPtr::new(std::ptr::null_mut());
static READY: AtomicUsize = AtomicUsize::new(0);
static START: AtomicBool = AtomicBool::new(false);
static ENTERED: AtomicBool = AtomicBool::new(false);
static RELEASE: AtomicBool = AtomicBool::new(false);
static FREED: AtomicBool = AtomicBool::new(false);

struct WatchingAllocator;
#[global_allocator]
static ALLOCATOR: WatchingAllocator = WatchingAllocator;

fn capturing() -> bool {
    CAPTURING.try_with(Cell::get).unwrap_or(false)
}

// SAFETY: all allocations and frees use System with their original layouts.
// The bounded observer stores addresses without dereferencing them. Const TLS
// and atomics do not allocate, and the allocator has no panicking assertions.
unsafe impl GlobalAlloc for WatchingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() && capturing() {
            let index = CAPTURE_COUNT.fetch_add(1, SeqCst);
            if index < MAX_CAPTURE {
                POINTERS[index].store(pointer, SeqCst);
                SIZES[index].store(layout.size(), SeqCst);
            }
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        if capturing() {
            // A freed allocation can be reused during construction. Only live
            // allocations may identify the backing of the completed context.
            for slot in POINTERS.iter().take(CAPTURE_COUNT.load(SeqCst)) {
                if slot.load(SeqCst) == pointer {
                    slot.store(std::ptr::null_mut(), SeqCst);
                }
            }
        }
        // Claim the address once, before freeing it, so reuse cannot make an
        // unrelated allocation enter the barrier or publish a false witness.
        if WATCH
            .compare_exchange(pointer, std::ptr::null_mut(), SeqCst, SeqCst)
            .is_ok()
        {
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

struct Capture;
impl Capture {
    fn begin() -> Self {
        CAPTURE_COUNT.store(0, SeqCst);
        CAPTURING.with(|cell| cell.set(true));
        Self
    }
}
impl Drop for Capture {
    fn drop(&mut self) {
        CAPTURING.with(|cell| cell.set(false));
    }
}

struct Observation {
    workers: Vec<JoinHandle<()>>,
}
impl Observation {
    fn new() -> Self {
        WATCH.store(std::ptr::null_mut(), SeqCst);
        READY.store(0, SeqCst);
        START.store(false, SeqCst);
        ENTERED.store(false, SeqCst);
        RELEASE.store(false, SeqCst);
        FREED.store(false, SeqCst);
        Self {
            workers: Vec::with_capacity(8),
        }
    }

    fn spawn(&mut self, action: impl FnOnce() + Send + 'static) {
        self.workers.push(std::thread::spawn(move || {
            READY.fetch_add(1, SeqCst);
            while !START.load(SeqCst) {
                std::thread::yield_now();
            }
            action();
        }));
    }

    fn finish(&mut self) -> bool {
        // Unlike a fixed Barrier, this also releases partially spawned workers
        // if setup or an assertion unwinds. Join every worker before resetting.
        RELEASE.store(true, SeqCst);
        START.store(true, SeqCst);
        let mut joined = true;
        for worker in self.workers.drain(..) {
            joined &= worker.join().is_ok();
        }
        WATCH.store(std::ptr::null_mut(), SeqCst);
        joined
    }
}
impl Drop for Observation {
    fn drop(&mut self) {
        self.finish();
    }
}

#[test]
fn original_metadata_charge_survives_actual_stack_context_backing_deallocation() {
    for mode in ["direct", "last-clone", "unwind", "concurrent"] {
        check_context_backing(mode);
    }
}

fn check_context_backing(mode: &str) {
    let mut observation = Observation::new();
    let (budget, runtime) = owners(1, 1024 * 1024);
    let capture = Capture::begin();
    let context = StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).unwrap();
    drop(capture);
    let count = CAPTURE_COUNT.load(SeqCst);
    assert!(
        count <= MAX_CAPTURE,
        "bounded stack allocation capture overflow"
    );
    let value = (&*context as *const StackContext) as usize;
    let mut backing: *mut u8 = std::ptr::null_mut();
    for index in 0..count {
        let pointer = POINTERS[index].load(SeqCst);
        if pointer.is_null() {
            continue;
        }
        let begin = pointer as usize;
        let end = begin.checked_add(SIZES[index].load(SeqCst)).unwrap();
        if begin <= value && value < end {
            assert!(backing.is_null(), "ambiguous stack context allocation");
            backing = pointer;
        }
    }
    assert!(
        !backing.is_null(),
        "actual stack context allocation not captured"
    );
    context.cancel_unstarted();
    let metadata = context._metadata.bytes();
    let original_charge = budget.host_memory_bytes();
    assert!(metadata > 0 && original_charge >= metadata);
    match mode {
        "direct" => observation.spawn(move || drop(context)),
        "last-clone" => {
            let last = context.clone();
            drop(context);
            assert_eq!(budget.host_memory_bytes(), original_charge);
            observation.spawn(move || drop(last));
        }
        "unwind" => {
            observation.spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let _context = context;
                    panic!("controlled stack context unwind");
                }));
                assert!(result.is_err());
            });
        }
        "concurrent" => {
            for _ in 0..8 {
                let clone = context.clone();
                observation.spawn(move || drop(clone));
            }
            drop(context);
            assert_eq!(budget.host_memory_bytes(), original_charge);
        }
        _ => unreachable!(),
    }
    // Arm only after ownership has moved to the parked workers. Even failed
    // thread creation cannot drop the last holder into an armed barrier here.
    let ready_deadline = Instant::now() + Duration::from_secs(5);
    while READY.load(SeqCst) != observation.workers.len() && Instant::now() < ready_deadline {
        std::thread::yield_now();
    }
    assert_eq!(READY.load(SeqCst), observation.workers.len());
    WATCH.store(backing, SeqCst);
    START.store(true, SeqCst);
    let deadline = Instant::now() + Duration::from_secs(5);
    while !ENTERED.load(SeqCst) && Instant::now() < deadline {
        std::thread::yield_now();
    }
    let entered = ENTERED.load(SeqCst);
    let held = budget.host_memory_bytes();
    assert!(observation.finish(), "{mode}: stack drop worker panicked");
    assert!(
        entered && FREED.load(SeqCst),
        "{mode}: actual context backing was not retired"
    );
    assert_eq!(
        held, original_charge,
        "{mode}: stack metadata refunded before backing free"
    );
    assert_eq!(budget.host_memory_bytes() + metadata, original_charge);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

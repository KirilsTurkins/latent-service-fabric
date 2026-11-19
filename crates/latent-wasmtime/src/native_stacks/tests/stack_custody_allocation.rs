//! Bounded test-only allocator observation of the actual stack context.
use super::*;
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicUsize, Ordering::SeqCst};
use std::sync::Barrier;
use std::time::{Duration, Instant};

const MAX_CAPTURE: usize = 256;
static CAPTURING: AtomicBool = AtomicBool::new(false);
static CAPTURE_COUNT: AtomicUsize = AtomicUsize::new(0);
static POINTERS: [AtomicPtr<u8>; MAX_CAPTURE] =
    [const { AtomicPtr::new(std::ptr::null_mut()) }; MAX_CAPTURE];
static SIZES: [AtomicUsize; MAX_CAPTURE] = [const { AtomicUsize::new(0) }; MAX_CAPTURE];
static WATCH: AtomicPtr<u8> = AtomicPtr::new(std::ptr::null_mut());
static ENTERED: AtomicBool = AtomicBool::new(false);
static RELEASE: AtomicBool = AtomicBool::new(false);
static FREED: AtomicBool = AtomicBool::new(false);

struct WatchingAllocator;
#[global_allocator]
static ALLOCATOR: WatchingAllocator = WatchingAllocator;

// SAFETY: all allocations and frees use System with their original layouts.
// The bounded observer stores addresses without dereferencing them.
unsafe impl GlobalAlloc for WatchingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if CAPTURING.load(SeqCst) {
            let index = CAPTURE_COUNT.fetch_add(1, SeqCst);
            if index < MAX_CAPTURE {
                POINTERS[index].store(pointer, SeqCst);
                SIZES[index].store(layout.size(), SeqCst);
            }
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        if pointer == WATCH.load(SeqCst) {
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

#[test]
fn original_metadata_charge_survives_actual_stack_context_backing_deallocation() {
    for mode in ["direct", "last-clone", "unwind", "concurrent"] {
        check_context_backing(mode);
    }
}

fn check_context_backing(mode: &str) {
    WATCH.store(std::ptr::null_mut(), SeqCst);
    CAPTURE_COUNT.store(0, SeqCst);
    ENTERED.store(false, SeqCst);
    RELEASE.store(false, SeqCst);
    FREED.store(false, SeqCst);
    let (budget, runtime) = owners(1, 1024 * 1024);
    CAPTURING.store(true, SeqCst);
    let context = StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).unwrap();
    CAPTURING.store(false, SeqCst);
    let count = CAPTURE_COUNT.load(SeqCst);
    assert!(
        count < MAX_CAPTURE,
        "bounded stack allocation capture overflow"
    );
    let value = (&*context as *const StackContext) as usize;
    let mut backing: *mut u8 = std::ptr::null_mut();
    for index in 0..count {
        let pointer = POINTERS[index].load(SeqCst);
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
    let mut workers = Vec::new();
    match mode {
        "direct" => {
            WATCH.store(backing, SeqCst);
            workers.push(std::thread::spawn(move || drop(context)));
        }
        "last-clone" => {
            let last = context.clone();
            drop(context);
            assert_eq!(budget.host_memory_bytes(), original_charge);
            WATCH.store(backing, SeqCst);
            workers.push(std::thread::spawn(move || drop(last)));
        }
        "unwind" => {
            WATCH.store(backing, SeqCst);
            workers.push(std::thread::spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let _context = context;
                    panic!("controlled stack context unwind");
                }));
                assert!(result.is_err());
            }));
        }
        "concurrent" => {
            let barrier = Arc::new(Barrier::new(9));
            for _ in 0..8 {
                let clone = context.clone();
                let barrier = Arc::clone(&barrier);
                workers.push(std::thread::spawn(move || {
                    barrier.wait();
                    drop(clone);
                }));
            }
            drop(context);
            assert_eq!(budget.host_memory_bytes(), original_charge);
            WATCH.store(backing, SeqCst);
            barrier.wait();
        }
        _ => unreachable!(),
    }
    let deadline = Instant::now() + Duration::from_secs(5);
    while !ENTERED.load(SeqCst) && Instant::now() < deadline {
        std::thread::yield_now();
    }
    let entered = ENTERED.load(SeqCst);
    let held = budget.host_memory_bytes();
    RELEASE.store(true, SeqCst);
    for worker in workers {
        worker.join().unwrap();
    }
    assert!(
        entered && FREED.load(SeqCst),
        "actual context backing was not retired"
    );
    assert_eq!(
        held, original_charge,
        "{mode}: stack metadata refunded before backing free"
    );
    assert_eq!(budget.host_memory_bytes() + metadata, original_charge);
    runtime.retire().unwrap();
}

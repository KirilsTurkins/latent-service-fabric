//! Standalone observation of the actual runtime owner-storage source. Run in
//! a single-threaded process against the same pinned latent-core build.
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};

#[path = "../crates/latent-wasmtime/src/host/runtime/owner_storage.rs"]
mod owner_storage;

static MODE: AtomicUsize = AtomicUsize::new(0);
static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);
static DEALLOCATIONS: AtomicUsize = AtomicUsize::new(0);
static ALLOC_SIZE: AtomicUsize = AtomicUsize::new(0);
static ALLOC_ALIGN: AtomicUsize = AtomicUsize::new(0);
static DEALLOC_SIZE: AtomicUsize = AtomicUsize::new(0);
static DEALLOC_ALIGN: AtomicUsize = AtomicUsize::new(0);
static ALLOC_POINTER: AtomicUsize = AtomicUsize::new(0);
static DEALLOC_POINTER: AtomicUsize = AtomicUsize::new(0);

struct Witness;
#[global_allocator]
static GLOBAL: Witness = Witness;

// SAFETY: the observer delegates each layout and pointer to System.
// Forced refusal returns null without allocating or dereferencing a pointer.
#[allow(
    unsafe_code,
    reason = "isolated test-only exact allocation and release observation"
)]
unsafe impl GlobalAlloc for Witness {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let mode = MODE.load(Ordering::SeqCst);
        if mode == 0 {
            return unsafe { System.alloc(layout) };
        }
        ALLOCATIONS.fetch_add(1, Ordering::SeqCst);
        ALLOC_SIZE.store(layout.size(), Ordering::SeqCst);
        ALLOC_ALIGN.store(layout.align(), Ordering::SeqCst);
        let pointer = if mode == 2 {
            std::ptr::null_mut()
        } else {
            unsafe { System.alloc(layout) }
        };
        ALLOC_POINTER.store(pointer as usize, Ordering::SeqCst);
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        if MODE.load(Ordering::SeqCst) != 0 {
            DEALLOCATIONS.fetch_add(1, Ordering::SeqCst);
            DEALLOC_SIZE.store(layout.size(), Ordering::SeqCst);
            DEALLOC_ALIGN.store(layout.align(), Ordering::SeqCst);
            DEALLOC_POINTER.store(pointer as usize, Ordering::SeqCst);
        }
        unsafe { System.dealloc(pointer, layout) }
    }
}

fn reset() {
    for counter in [
        &ALLOCATIONS,
        &DEALLOCATIONS,
        &ALLOC_SIZE,
        &ALLOC_ALIGN,
        &DEALLOC_SIZE,
        &DEALLOC_ALIGN,
        &ALLOC_POINTER,
        &DEALLOC_POINTER,
    ] {
        counter.store(0, Ordering::SeqCst);
    }
}

fn main() {
    use latent_core::activation_runtime::RuntimeOwner;

    for capacity in [1, 2, 8192] {
        reset();
        let layout = Layout::array::<RuntimeOwner>(capacity).unwrap();
        MODE.store(1, Ordering::SeqCst);
        let storage = owner_storage::allocate(capacity).unwrap();
        let pointer = std::hint::black_box(storage.as_ptr() as usize);
        let actual_capacity = storage.capacity();
        drop(storage);
        MODE.store(0, Ordering::SeqCst);
        assert_eq!(actual_capacity, capacity);
        assert_ne!(pointer, 0);
        assert_eq!(ALLOCATIONS.load(Ordering::SeqCst), 1);
        assert_eq!(DEALLOCATIONS.load(Ordering::SeqCst), 1);
        assert_eq!(ALLOC_SIZE.load(Ordering::SeqCst), layout.size());
        assert_eq!(DEALLOC_SIZE.load(Ordering::SeqCst), layout.size());
        assert_eq!(ALLOC_ALIGN.load(Ordering::SeqCst), layout.align());
        assert_eq!(DEALLOC_ALIGN.load(Ordering::SeqCst), layout.align());
        assert_eq!(ALLOC_POINTER.load(Ordering::SeqCst), pointer);
        assert_eq!(DEALLOC_POINTER.load(Ordering::SeqCst), pointer);
    }

    reset();
    MODE.store(2, Ordering::SeqCst);
    let refused = owner_storage::allocate(2).is_err();
    MODE.store(0, Ordering::SeqCst);
    assert!(refused);
    assert_eq!(ALLOCATIONS.load(Ordering::SeqCst), 1);
    assert_eq!(DEALLOCATIONS.load(Ordering::SeqCst), 0);

    for capacity in [0, usize::MAX] {
        reset();
        MODE.store(1, Ordering::SeqCst);
        let refused = owner_storage::allocate(capacity).is_err();
        MODE.store(0, Ordering::SeqCst);
        assert!(refused);
        assert_eq!(ALLOCATIONS.load(Ordering::SeqCst), 0);
        assert_eq!(DEALLOCATIONS.load(Ordering::SeqCst), 0);
    }
    println!("runtime owner backing: exact allocation, drop, and refusal passed");
}

//! Observe actual allocator retirement, including unwinding and final clones.
use bytes::Bytes;
use std::alloc::{GlobalAlloc, Layout, System};
use std::ptr::null_mut;
use std::sync::atomic::{AtomicBool, AtomicPtr, AtomicUsize, Ordering::SeqCst};

struct ObservedAllocator;
#[global_allocator]
static ALLOCATOR: ObservedAllocator = ObservedAllocator;
static ARM: AtomicBool = AtomicBool::new(false);
static HEADER: AtomicPtr<u8> = AtomicPtr::new(null_mut());
static DATA: AtomicPtr<u8> = AtomicPtr::new(null_mut());
static OWNER: AtomicUsize = AtomicUsize::new(0);
static HEADER_FREED: AtomicBool = AtomicBool::new(false);
static DATA_FREED: AtomicBool = AtomicBool::new(false);
static OWNER_DROPPED: AtomicBool = AtomicBool::new(false);
static CONFIRMED: AtomicBool = AtomicBool::new(false);
static RETIRED: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for ObservedAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = System.alloc(layout);
        if ARM.swap(false, SeqCst) {
            HEADER.store(pointer, SeqCst);
        }
        pointer
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        System.dealloc(pointer, layout);
        // Publish only after the real allocator has freed this allocation.
        if pointer == HEADER.load(SeqCst) {
            HEADER_FREED.store(true, SeqCst);
        }
        if pointer == DATA.load(SeqCst) {
            DATA_FREED.store(true, SeqCst);
        }
    }
}

struct Owner {
    data: Vec<u8>,
    panic_ref: bool,
    panic_drop: bool,
    _pin: std::marker::PhantomPinned,
}
impl AsRef<[u8]> for Owner {
    fn as_ref(&self) -> &[u8] {
        assert!(CONFIRMED.load(SeqCst));
        OWNER.store(self as *const Self as usize, SeqCst);
        assert!(!self.panic_ref, "expected AsRef unwind");
        &self.data
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        let original = OWNER.load(SeqCst);
        assert!(original == 0 || original == self as *const Self as usize);
        assert!(!HEADER_FREED.load(SeqCst));
        assert!(!DATA_FREED.load(SeqCst));
        OWNER_DROPPED.store(true, SeqCst);
        assert!(!self.panic_drop, "expected owner unwind");
    }
}
struct Retirement;
impl Drop for Retirement {
    fn drop(&mut self) {
        assert!(OWNER_DROPPED.load(SeqCst));
        assert!(DATA.load(SeqCst).is_null() || DATA_FREED.load(SeqCst));
        assert!(
            HEADER_FREED.load(SeqCst),
            "actual owner Box must already be deallocated"
        );
        assert_eq!(RETIRED.fetch_add(1, SeqCst), 0);
    }
}

fn prepare(length: usize, panic_ref: bool, panic_drop: bool) -> Owner {
    let data = vec![7; length];
    DATA.store(
        if data.capacity() == 0 {
            null_mut()
        } else {
            data.as_ptr() as *mut u8
        },
        SeqCst,
    );
    HEADER.store(null_mut(), SeqCst);
    OWNER.store(0, SeqCst);
    HEADER_FREED.store(false, SeqCst);
    DATA_FREED.store(false, SeqCst);
    OWNER_DROPPED.store(false, SeqCst);
    CONFIRMED.store(false, SeqCst);
    RETIRED.store(0, SeqCst);
    ARM.store(true, SeqCst);
    Owner {
        data,
        panic_ref,
        panic_drop,
        _pin: std::marker::PhantomPinned,
    }
}

fn construct(panic_ref: bool, panic_drop: bool, panic_confirm: bool) -> Bytes {
    Bytes::from_owner_with_retirement(prepare(512, panic_ref, panic_drop), Retirement, |_| {
        assert!(!HEADER.load(SeqCst).is_null());
        assert!(!HEADER_FREED.load(SeqCst));
        CONFIRMED.store(true, SeqCst);
        assert!(!panic_confirm, "expected confirmation unwind");
    })
}

#[test]
fn actual_box_and_payload_free_before_retirement_on_all_owner_paths() {
    // The former result layout uses the unchanged original constructor: its
    // guard is a field of T and therefore drops before Owned<T>'s Box frees.
    // The same allocator oracle must reject that real ordering.
    struct LegacyOwner {
        owner: Owner,
        _retirement: Retirement,
    }
    impl AsRef<[u8]> for LegacyOwner {
        fn as_ref(&self) -> &[u8] {
            self.owner.as_ref()
        }
    }
    let former = std::panic::catch_unwind(|| {
        let owner = prepare(512, false, false);
        CONFIRMED.store(true, SeqCst);
        drop(Bytes::from_owner(LegacyOwner {
            owner,
            _retirement: Retirement,
        }));
    })
    .unwrap_err();
    assert_eq!(
        former.downcast_ref::<&str>(),
        Some(&"actual owner Box must already be deallocated")
    );
    assert!(HEADER_FREED.load(SeqCst));
    assert!(DATA_FREED.load(SeqCst));

    let bytes = construct(false, false, false);
    let slice = bytes.slice(1..4);
    let clone = bytes.clone();
    drop(bytes);
    drop(clone);
    assert_eq!(RETIRED.load(SeqCst), 0);
    assert!(!HEADER_FREED.load(SeqCst));
    assert_eq!(&slice[..], &[7; 3]);
    drop(slice);
    assert_eq!(RETIRED.load(SeqCst), 1);

    let bytes = construct(false, false, false);
    let copied = Vec::from(bytes);
    assert_eq!(copied, vec![7; 512]);
    assert_eq!(RETIRED.load(SeqCst), 1);
    drop(copied);

    let bytes = Bytes::from_owner_with_retirement(prepare(0, false, false), Retirement, |_| {
        CONFIRMED.store(true, SeqCst);
    });
    assert!(bytes.is_empty());
    assert_eq!(RETIRED.load(SeqCst), 0);
    drop(bytes);
    assert_eq!(RETIRED.load(SeqCst), 1);

    let bytes = construct(false, false, false);
    let copied = bytes.try_into_mut().unwrap_err();
    assert_eq!(RETIRED.load(SeqCst), 0);
    let copied = bytes::BytesMut::from(copied);
    assert_eq!(&copied[..], &[7; 512]);
    assert_eq!(RETIRED.load(SeqCst), 1);
    drop(copied);

    let bytes = construct(false, false, false);
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(9));
    let threads: Vec<_> = (0..8)
        .map(|_| {
            let clone = bytes.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                drop(clone);
            })
        })
        .collect();
    drop(bytes);
    assert_eq!(RETIRED.load(SeqCst), 0);
    barrier.wait();
    for thread in threads {
        thread.join().unwrap();
    }
    assert_eq!(RETIRED.load(SeqCst), 1);

    for (panic_ref, panic_drop, panic_confirm) in [
        (true, false, false),
        (false, true, false),
        (false, false, true),
    ] {
        assert!(std::panic::catch_unwind(|| {
            drop(construct(panic_ref, panic_drop, panic_confirm));
        })
        .is_err());
        assert_eq!(RETIRED.load(SeqCst), 1);
    }
}

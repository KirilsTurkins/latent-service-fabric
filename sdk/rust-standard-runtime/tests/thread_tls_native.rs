//! Selected std-thread TLS source with explicit canonical/ledger test ports
//! and ledger imports; not guest/std/sysroot/thread qualification.
#![allow(dead_code)]
#![forbid(unsafe_op_in_unsafe_fn)]
pub use std::{boxed, cell, mem, ptr};

// Trace the real System allocator used by the actual PAL. This shim delegates
// all bytes/alignment to std::alloc::System; it is not a guest cost measurement.
pub mod alloc {
    pub use std::alloc::{handle_alloc_error, GlobalAlloc, Layout};
    pub struct System;
    unsafe impl GlobalAlloc for System {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            super::SYSTEM_ALLOCS.fetch_add(1, super::Ordering::SeqCst);
            if super::FAIL_NEXT_ALLOCATION.swap(false, super::Ordering::SeqCst) {
                return std::ptr::null_mut();
            }
            unsafe { std::alloc::System.alloc(layout) }
        }
        unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
            unsafe {
                std::alloc::System.dealloc(pointer, layout);
            }
            super::SYSTEM_FREES.fetch_add(1, super::Ordering::SeqCst);
            if pointer.addr() == super::WATCH_CONTEXT.load(super::Ordering::SeqCst) {
                super::CONTEXT_FREED.store(1, super::Ordering::SeqCst);
            }
        }
    }
}

#[path = "../thread_tls.rs"]
mod platform;

use std::cell::{Cell, RefCell};
use std::collections::BTreeSet;
use std::sync::atomic::{AtomicUsize, Ordering};

thread_local! {
    static SLOT: Cell<*mut u8> = const { Cell::new(std::ptr::null_mut()) };
    static LEDGER: RefCell<Ledger> = RefCell::new(Ledger::default());
}
#[derive(Default)]
struct Ledger {
    next: u64,
    limit: usize,
    closing: bool,
    owners: BTreeSet<u64>,
    continued: usize,
    settlements: Vec<(u64, bool)>,
    cleanup: usize,
    kinds: Vec<u32>,
}
pub mod rt {
    pub fn thread_cleanup() {
        super::LEDGER.with(|l| l.borrow_mut().cleanup += 1);
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn context_get() -> *mut u8 {
    SLOT.with(Cell::get)
}
#[unsafe(no_mangle)]
pub extern "C" fn context_set(value: *mut u8) {
    SLOT.with(|s| s.set(value));
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn register(
    kind: u32,
    continuation: u32,
    generation: u64,
    id: u64,
    result: *mut u8,
) {
    assert!(matches!(kind, 0 | 7));
    LEDGER.with(|l| {
        let mut l = l.borrow_mut();
        if continuation == 1 {
            assert_eq!(generation, 81);
            assert!(l.owners.contains(&id));
            l.continued += 1;
        } else {
            assert_eq!((continuation, generation, id), (0, 0, 0));
        }
        if l.owners.len() == l.limit || (l.closing && continuation == 0) {
            unsafe {
                result.write(1);
                result.add(8).write(2);
            }
        } else {
            l.next += 1;
            let owner = l.next;
            l.owners.insert(owner);
            l.kinds.push(kind);
            unsafe {
                result.write(0);
                std::ptr::copy_nonoverlapping(81u64.to_le_bytes().as_ptr(), result.add(8), 8);
                std::ptr::copy_nonoverlapping(owner.to_le_bytes().as_ptr(), result.add(16), 8);
            }
        }
    });
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn settle(generation: u64, id: u64, result: *mut u8) {
    assert_eq!(generation, 81);
    if id >= 3 {
        assert!(
            SYSTEM_FREES.load(Ordering::SeqCst) >= SETTLE_REQUIRED_FREES.load(Ordering::SeqCst)
        );
    }
    if WATCH_CONTEXT.load(Ordering::SeqCst) != 0 {
        if id == 1 {
            assert_eq!(CONTEXT_FREED.load(Ordering::SeqCst), 1);
        } else {
            assert!(SYSTEM_FREES.load(Ordering::SeqCst) >= 1);
        }
    }
    LEDGER.with(|l| {
        let mut l = l.borrow_mut();
        assert!(l.owners.remove(&id));
        l.settlements.push((id, context_get().is_null()));
    });
    unsafe {
        result.write(0);
    }
}

fn reset(limit: usize) {
    assert!(context_get().is_null());
    LEDGER.with(|l| {
        assert!(l.borrow().owners.is_empty());
        *l.borrow_mut() = Ledger {
            limit,
            ..Ledger::default()
        };
    });
    DROPS.store(0, Ordering::SeqCst);
}
fn owners() -> usize {
    LEDGER.with(|l| l.borrow().owners.len())
}
static DROPS: AtomicUsize = AtomicUsize::new(0);
static SYSTEM_ALLOCS: AtomicUsize = AtomicUsize::new(0);
static SYSTEM_FREES: AtomicUsize = AtomicUsize::new(0);
static FAIL_NEXT_ALLOCATION: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);
static WATCH_CONTEXT: AtomicUsize = AtomicUsize::new(0);
static CONTEXT_FREED: AtomicUsize = AtomicUsize::new(0);
static SETTLE_REQUIRED_FREES: AtomicUsize = AtomicUsize::new(0);
unsafe extern "C" fn destroy(value: *mut u8) {
    assert!(!context_get().is_null());
    drop(unsafe { Box::from_raw(value.cast::<u32>()) });
    DROPS.fetch_add(1, Ordering::SeqCst);
}
static FIRST: platform::LazyKey = platform::LazyKey::new(Some(destroy));
static SECOND: platform::LazyKey = platform::LazyKey::new(Some(destroy));
static BORROWED: platform::LazyKey = platform::LazyKey::new(None);
static BLOCK_KEYS: [platform::LazyKey; 33] =
    [const { platform::LazyKey::new(None) }; 33];

fn boot(limit: usize) -> *mut u8 {
    reset(limit);
    let pointer = platform::prepare_owned_root_context(65_536, 131_072);
    assert!(context_get().is_null());
    assert_eq!(owners(), 0);
    unsafe {
        platform::install_thread_context(pointer);
    }
    pointer
}
unsafe fn wrapper_exited(pointer: *mut u8) {
    assert_eq!(unsafe { pointer.add(12).cast::<u32>().read() }, 4);
    unsafe {
        pointer.add(12).cast::<u32>().write(5);
    }
    context_set(std::ptr::null_mut());
}
fn finish(pointer: *mut u8) {
    unsafe {
        platform::__lsf_rust_root_finish(pointer);
        wrapper_exited(pointer);
        platform::__lsf_rust_root_reap(pointer);
    }
}

#[test]
fn no_concurrency_bootstrap_uses_fixed_record_without_task_native_allocation_or_fake_free() {
    let allocated = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    let freed = SYSTEM_FREES.load(Ordering::SeqCst);
    let root = boot(0);
    let prefix = unsafe { std::slice::from_raw_parts(root.cast::<u32>(), 4) };
    assert_eq!(prefix, [131_072, 65_536, 131_072, 2]);
    assert_eq!(root.addr() % 8, 0);
    assert_eq!(unsafe { root.add(16).cast::<u64>().read() }, 0);
    assert_eq!(unsafe { root.add(24).cast::<u64>().read() }, 0);
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), allocated);
    finish(root);
    assert!(context_get().is_null());
    assert_eq!(owners(), 0);
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), freed);
    let fresh = boot(0);
    assert_eq!(fresh, root);
    finish(fresh);
    assert!(LEDGER.with(|l| l.borrow().kinds.is_empty()));
}

#[test]
fn tls_only_admits_real_native_entries_without_creating_a_root_task() {
    let root = boot(8);
    let allocated = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    let freed = SYSTEM_FREES.load(Ordering::SeqCst);
    let value = Box::into_raw(Box::new(42u32)).cast();
    unsafe {
        platform::set(FIRST.force(), value);
    }
    assert_eq!(owners(), 2);
    assert_eq!(LEDGER.with(|l| l.borrow().kinds.clone()), [7, 7]);
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), allocated + 1);
    unsafe {
        platform::__lsf_rust_root_finish(root);
    }
    assert_eq!(DROPS.load(Ordering::SeqCst), 1);
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), freed + 1);
    assert_eq!(owners(), 1);
    unsafe {
        wrapper_exited(root);
        platform::__lsf_rust_root_reap(root);
    }
    assert_eq!(owners(), 0);
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), freed + 1);
}

#[test]
fn tls_entries_share_one_admitted_physical_block_and_next_block_still_obeys_limit() {
    let root = boot(2);
    let allocated = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    let freed = SYSTEM_FREES.load(Ordering::SeqCst);
    for key in &BLOCK_KEYS[..32] {
        unsafe {
            platform::set(key.force(), std::ptr::without_provenance_mut(1));
        }
    }
    assert_eq!(owners(), 2); // context allocation and one entry-block allocation
    assert_eq!(LEDGER.with(|l| l.borrow().kinds.clone()), [7, 7]);
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), allocated + 1);
    assert!(std::panic::catch_unwind(|| unsafe {
        platform::get(BLOCK_KEYS[32].force());
    })
    .is_err());
    assert_eq!(owners(), 2);
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), allocated + 1);
    finish(root);
    assert_eq!(owners(), 0);
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), freed + 1);
}

#[test]
fn first_concurrency_admits_one_original_task_and_retains_it_until_final_root_reap() {
    let root = boot(8);
    let allocated = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    let token = platform::ensure_thread_continuation().unwrap();
    let same = platform::ensure_thread_continuation().unwrap();
    assert_eq!((token.generation, token.id), (same.generation, same.id));
    assert_eq!(LEDGER.with(|l| l.borrow().kinds.clone()), [0]);
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), allocated);
    unsafe {
        platform::__lsf_rust_root_finish(root);
    }
    assert_eq!(owners(), 1);
    assert_eq!(context_get(), root);
    assert!(std::panic::catch_unwind(platform::ensure_thread_continuation).is_err());
    assert_eq!(owners(), 1);
    unsafe {
        wrapper_exited(root);
        platform::__lsf_rust_root_reap(root);
    }
    assert_eq!(owners(), 0);
    assert_eq!(
        LEDGER.with(|l| l.borrow().settlements.clone()),
        [(token.id, true)]
    );
}

#[test]
fn typed_task_refusal_precedes_any_allocation_or_registry_and_does_not_fake_a_task() {
    let root = boot(0);
    let allocated = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    assert!(matches!(platform::ensure_thread_continuation(), Err(2)));
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), allocated);
    assert!(LEDGER.with(|l| l.borrow().kinds.is_empty()));
    finish(root);
    assert_eq!(owners(), 0);
}

#[test]
fn static_root_cannot_use_unstarted_or_child_system_free_paths() {
    reset(8);
    let root = platform::prepare_owned_root_context(65_536, 131_072);
    let freed = SYSTEM_FREES.load(Ordering::SeqCst);
    assert!(
        std::panic::catch_unwind(|| unsafe { platform::discard_unstarted_context(root) }).is_err()
    );
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), freed);
    unsafe {
        platform::install_thread_context(root);
        platform::__lsf_rust_root_finish(root);
        wrapper_exited(root);
    }
    // A distinct real allocated legacy context supplies the child reaper's
    // caller port. The static root must still be refused before deallocation.
    unsafe {
        platform::get(BORROWED.force());
    }
    assert_ne!(context_get(), root);
    assert_eq!(
        unsafe { platform::retire_exited_thread_context(root) },
        Err(platform::RetireError::WrongStackPhase)
    );
    unsafe {
        platform::retire_current().unwrap();
        platform::__lsf_rust_root_reap(root);
    }
    assert_eq!(owners(), 0);
}

static DRAIN_CALLS: AtomicUsize = AtomicUsize::new(0);
static DRAIN_RELEASES: AtomicUsize = AtomicUsize::new(0);
unsafe fn drain_port(state: *mut u8) -> bool {
    assert_eq!(state.addr(), 8);
    assert!(!context_get().is_null());
    assert_eq!(unsafe { context_get().add(12).cast::<u32>().read() }, 3);
    assert!(LEDGER.with(|l| l.borrow().kinds.contains(&0)));
    DRAIN_CALLS.fetch_add(1, Ordering::SeqCst);
    true
}
unsafe fn release_port(state: *mut u8) {
    assert_eq!(state.addr(), 8);
    assert!(context_get().is_null());
    assert_eq!(owners(), 2); // real context Native and accepted root Task
    DRAIN_RELEASES.fetch_add(1, Ordering::SeqCst);
}
unsafe extern "C" fn submit_first_from_destructor(value: *mut u8) {
    unsafe {
        destroy(value);
    }
    let _task = platform::ensure_thread_continuation().unwrap();
    unsafe {
        platform::install_root_drain(
            std::ptr::without_provenance_mut(8),
            drain_port,
            release_port,
        );
    }
}
static SUBMITS: platform::LazyKey = platform::LazyKey::new(Some(submit_first_from_destructor));

#[test]
fn first_destructor_submitted_concurrency_can_install_drain_until_true_tls_exit() {
    DRAIN_CALLS.store(0, Ordering::SeqCst);
    DRAIN_RELEASES.store(0, Ordering::SeqCst);
    let root = boot(8);
    unsafe {
        platform::set(SUBMITS.force(), Box::into_raw(Box::new(42u32)).cast());
    }
    assert_eq!(LEDGER.with(|l| l.borrow().kinds.clone()), [7, 7]);
    unsafe {
        platform::__lsf_rust_root_finish(root);
    }
    assert_eq!(LEDGER.with(|l| l.borrow().kinds.clone()), [7, 7, 0]);
    assert!(DRAIN_CALLS.load(Ordering::SeqCst) >= 2);
    assert_eq!(DRAIN_RELEASES.load(Ordering::SeqCst), 0);
    unsafe {
        wrapper_exited(root);
        platform::__lsf_rust_root_reap(root);
    }
    assert_eq!(DRAIN_RELEASES.load(Ordering::SeqCst), 1);
    assert_eq!(owners(), 0);
}

#[test]
fn fallible_child_native_admission_refuses_before_any_system_allocation() {
    let root = boot(1);
    let task = platform::ensure_thread_continuation().unwrap();
    let before = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    assert_eq!(
        platform::try_prepare_stacked_thread_context(task, 65536),
        Err(platform::ContextError::Admission(2))
    );
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), before);
    assert_eq!(owners(), 1);
    finish(root);
    assert_eq!(owners(), 0);
}

#[test]
fn fallible_child_allocation_failure_rolls_back_only_its_accepted_native_owner() {
    let root = boot(4);
    let task = platform::ensure_thread_continuation().unwrap();
    let before = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    let freed = SYSTEM_FREES.load(Ordering::SeqCst);
    FAIL_NEXT_ALLOCATION.store(true, Ordering::SeqCst);
    assert_eq!(
        platform::try_prepare_stacked_thread_context(task, 65536),
        Err(platform::ContextError::Allocation)
    );
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), before + 1);
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), freed);
    assert_eq!(owners(), 1); // original Task remains owned through root frame exit
    finish(root);
    assert_eq!(owners(), 0);
}

#[test]
fn invalid_child_stack_layout_refuses_before_native_admission_or_allocation() {
    let root = boot(0);
    let before = SYSTEM_ALLOCS.load(Ordering::SeqCst);
    let task = platform::Token {
        generation: 81,
        id: 1,
    };
    for bytes in [0, 65535, usize::MAX] {
        assert_eq!(
            platform::try_prepare_stacked_thread_context(task, bytes),
            Err(platform::ContextError::Layout)
        );
    }
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), before);
    assert_eq!(owners(), 0);
    finish(root);
}

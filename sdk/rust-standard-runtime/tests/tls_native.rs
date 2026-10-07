//! Reference for actual TLS PAL source with explicit fake canonical contexts
//! and ledger imports; not guest/std/sysroot/thread qualification.
#![allow(dead_code)]
#![forbid(unsafe_op_in_unsafe_fn)]
pub use std::{boxed, cell, mem, ptr};

// Trace the real System allocator used by the actual PAL. This shim delegates
// all bytes/alignment to std::alloc::System; it is not a guest cost measurement.
pub mod alloc {
    pub use std::alloc::{GlobalAlloc, Layout, handle_alloc_error};
    pub struct System;
    unsafe impl GlobalAlloc for System {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            super::SYSTEM_ALLOCS.fetch_add(1, super::Ordering::SeqCst);
            unsafe { std::alloc::System.alloc(layout) }
        }
        unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
            unsafe { std::alloc::System.dealloc(pointer, layout); }
            super::SYSTEM_FREES.fetch_add(1, super::Ordering::SeqCst);
            if pointer.addr() == super::WATCH_CONTEXT.load(super::Ordering::SeqCst) {
                super::CONTEXT_FREED.store(1, super::Ordering::SeqCst);
            }
        }
    }
}

#[path = "../tls.rs"]
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
}
pub mod rt {
    pub fn thread_cleanup() {
        super::LEDGER.with(|l| l.borrow_mut().cleanup += 1);
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn context_get() -> *mut u8 { SLOT.with(Cell::get) }
#[unsafe(no_mangle)]
pub extern "C" fn context_set(value: *mut u8) { SLOT.with(|s| s.set(value)); }
#[unsafe(no_mangle)]
pub unsafe extern "C" fn register(kind: u32, continuation: u32, generation: u64, id: u64, result: *mut u8) {
    assert_eq!(kind, 7);
    LEDGER.with(|l| {
        let mut l = l.borrow_mut();
        if continuation == 1 {
            assert_eq!(generation, 81);
            assert!(l.owners.contains(&id));
            l.continued += 1;
        } else { assert_eq!((continuation, generation, id), (0, 0, 0)); }
        if l.owners.len() == l.limit || (l.closing && continuation == 0) {
            unsafe { result.write(1); result.add(8).write(2); }
        } else {
            l.next += 1; let owner = l.next; l.owners.insert(owner);
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
    if WATCH_CONTEXT.load(Ordering::SeqCst) != 0 {
        if id == 1 { assert_eq!(CONTEXT_FREED.load(Ordering::SeqCst), 1); }
        else { assert!(SYSTEM_FREES.load(Ordering::SeqCst) >= 1); }
    }
    LEDGER.with(|l| {
        let mut l = l.borrow_mut(); assert!(l.owners.remove(&id));
        l.settlements.push((id, context_get().is_null()));
    });
    unsafe { result.write(0); }
}

fn reset(limit: usize) {
    assert!(context_get().is_null());
    LEDGER.with(|l| { assert!(l.borrow().owners.is_empty()); *l.borrow_mut() = Ledger { limit, ..Ledger::default() }; });
    DROPS.store(0, Ordering::SeqCst);
}
fn owners() -> usize { LEDGER.with(|l| l.borrow().owners.len()) }
static DROPS: AtomicUsize = AtomicUsize::new(0);
static SYSTEM_ALLOCS: AtomicUsize = AtomicUsize::new(0);
static SYSTEM_FREES: AtomicUsize = AtomicUsize::new(0);
static WATCH_CONTEXT: AtomicUsize = AtomicUsize::new(0);
static CONTEXT_FREED: AtomicUsize = AtomicUsize::new(0);
unsafe extern "C" fn destroy(value: *mut u8) {
    assert!(!context_get().is_null());
    drop(unsafe { Box::from_raw(value.cast::<u32>()) });
    DROPS.fetch_add(1, Ordering::SeqCst);
}
static FIRST: platform::LazyKey = platform::LazyKey::new(Some(destroy));
static SECOND: platform::LazyKey = platform::LazyKey::new(Some(destroy));
static BORROWED: platform::LazyKey = platform::LazyKey::new(None);

#[test]
fn unused_tls_has_no_context_or_ledger_allocation() {
    reset(8);
    assert!(context_get().is_null()); assert_eq!(owners(), 0);
    unsafe { platform::retire_current().unwrap(); }
    assert_eq!(owners(), 0);
    assert_eq!(LEDGER.with(|l| l.borrow().cleanup), 0);
}

#[test]
fn same_static_key_follows_independent_saved_canonical_context_values() {
    reset(8);
    let key = FIRST.force();
    unsafe { assert!(platform::get(key).is_null()); }
    let one = Box::into_raw(Box::new(20u32)).cast();
    unsafe { platform::set(key, one); }
    let context_one = context_get();
    context_set(std::ptr::null_mut());
    unsafe { assert!(platform::get(key).is_null()); }
    let two = Box::into_raw(Box::new(22u32)).cast();
    unsafe { platform::set(key, two); }
    let context_two = context_get();
    assert_ne!(context_one, context_two);
    assert_eq!(owners(), 4);
    context_set(context_one);
    unsafe { assert_eq!(platform::get(key), one); }
    context_set(context_two);
    unsafe { assert_eq!(platform::get(key), two); platform::retire_current().unwrap(); }
    assert_eq!(owners(), 2); assert_eq!(DROPS.load(Ordering::SeqCst), 1);
    context_set(context_one);
    unsafe { assert_eq!(platform::get(key), one); platform::retire_current().unwrap(); }
    assert_eq!(owners(), 0); assert_eq!(DROPS.load(Ordering::SeqCst), 2);
}

#[test]
fn each_entry_admits_before_initialization_and_uses_current_context_continuation() {
    reset(2);
    unsafe { assert!(platform::get(FIRST.force()).is_null()); }
    assert_eq!(owners(), 2);
    let denied = std::panic::catch_unwind(|| unsafe { platform::get(SECOND.force()) });
    assert!(denied.is_err()); assert_eq!(owners(), 2);
    unsafe { assert!(platform::get(FIRST.force()).is_null()); platform::retire_current().unwrap(); }
    assert_eq!(owners(), 0);
    assert_eq!(LEDGER.with(|l| l.borrow().continued), 2);
}

unsafe extern "C" fn create_sibling(value: *mut u8) {
    unsafe { destroy(value); }
    let value = Box::into_raw(Box::new(9u32)).cast();
    unsafe { platform::set(SECOND.force(), value); }
    platform::mark_cleanup();
}
static CREATOR: platform::LazyKey = platform::LazyKey::new(Some(create_sibling));

#[test]
fn destructor_created_sibling_stays_owned_until_its_callback_finishes() {
    reset(8);
    let value = Box::into_raw(Box::new(1u32)).cast();
    unsafe { platform::set(CREATOR.force(), value); platform::retire_current().unwrap(); }
    assert_eq!(DROPS.load(Ordering::SeqCst), 2);
    assert_eq!(owners(), 0);
    assert_eq!(LEDGER.with(|l| l.borrow().cleanup), 1);
}

unsafe extern "C" fn sentinel(value: *mut u8) {
    unsafe {
        assert!(platform::get(SENTINEL.force()).is_null());
        platform::set(SENTINEL.force(), std::ptr::without_provenance_mut(1));
        assert_eq!(platform::get(SENTINEL.force()).addr(), 1);
        destroy(value);
        platform::set(SENTINEL.force(), std::ptr::null_mut());
    }
}
static SENTINEL: platform::LazyKey = platform::LazyKey::new(Some(sentinel));

#[test]
fn upstream_destroying_sentinel_preserves_reentrant_get_semantics() {
    reset(8);
    let value = Box::into_raw(Box::new(1u32)).cast();
    unsafe { platform::set(SENTINEL.force(), value); platform::retire_current().unwrap(); }
    assert_eq!(DROPS.load(Ordering::SeqCst), 1); assert_eq!(owners(), 0);
}

unsafe extern "C" fn nested_retire(value: *mut u8) {
    unsafe {
        assert_eq!(platform::retire_current(), Err(platform::RetireError::AlreadyClosing));
        assert_eq!(owners(), 2);
        destroy(value);
    }
}
static NESTED: platform::LazyKey = platform::LazyKey::new(Some(nested_retire));

#[test]
fn nested_retirement_cannot_refund_outer_live_destructor() {
    reset(8);
    let value = Box::into_raw(Box::new(1u32)).cast();
    unsafe { platform::set(NESTED.force(), value); platform::retire_current().unwrap(); }
    assert_eq!(DROPS.load(Ordering::SeqCst), 1); assert_eq!(owners(), 0);
}

#[test]
fn final_context_owner_settles_after_slot_clear_and_runtime_cleanup() {
    reset(8);
    unsafe { assert!(platform::get(BORROWED.force()).is_null()); platform::retire_current().unwrap(); }
    let events = LEDGER.with(|l| { let l = l.borrow(); assert_eq!(l.cleanup, 1); l.settlements.clone() });
    assert_eq!(events, vec![(2, false), (1, true)]);
    assert!(context_get().is_null()); assert_eq!(owners(), 0);
}

#[test]
fn internal_storage_uses_system_and_physically_frees_before_settlement() {
    reset(8);
    SYSTEM_ALLOCS.store(0, Ordering::SeqCst); SYSTEM_FREES.store(0, Ordering::SeqCst);
    unsafe { platform::get(BORROWED.force()); }
    assert_eq!(SYSTEM_ALLOCS.load(Ordering::SeqCst), 2);
    WATCH_CONTEXT.store(context_get().addr(), Ordering::SeqCst); CONTEXT_FREED.store(0, Ordering::SeqCst);
    unsafe { platform::retire_current().unwrap(); }
    assert_eq!(SYSTEM_FREES.load(Ordering::SeqCst), 2);
    assert_eq!(CONTEXT_FREED.load(Ordering::SeqCst), 1);
    assert_eq!(owners(), 0); WATCH_CONTEXT.store(0, Ordering::SeqCst);
}

unsafe extern "C" fn cycle(value: *mut u8) {
    unsafe { destroy(value); }
    let again = Box::into_raw(Box::new(1u32)).cast();
    unsafe { platform::set(CYCLE.force(), again); }
}
static CYCLE: platform::LazyKey = platform::LazyKey::new(Some(cycle));

#[test]
fn destructor_cycle_is_bounded_and_retains_its_context_and_owners() {
    reset(8);
    let value = Box::into_raw(Box::new(1u32)).cast();
    unsafe {
        platform::set(CYCLE.force(), value);
        assert_eq!(platform::retire_current(), Err(platform::RetireError::DestructorLimit));
    }
    assert_eq!(DROPS.load(Ordering::SeqCst), 4); assert_eq!(owners(), 2);
    assert!(!context_get().is_null()); assert_eq!(LEDGER.with(|l| l.borrow().cleanup), 0);
    unsafe { assert_eq!(platform::retire_current(), Err(platform::RetireError::AlreadyClosing)); }
    assert_eq!(owners(), 2);
    // Run each reference test in its own native process. This deliberate
    // retained negative is not reset/refunded or called physical retirement.
}

#[test]
fn destroying_sentinel_cannot_be_erased_or_refunded_as_finished_work() {
    reset(8);
    unsafe {
        platform::set(FIRST.force(), std::ptr::without_provenance_mut(1));
        assert_eq!(platform::retire_current(), Err(platform::RetireError::DestructorLimit));
    }
    assert_eq!(owners(), 2); assert!(!context_get().is_null());
    assert_eq!(LEDGER.with(|l| l.borrow().cleanup), 0);
}

#[test]
fn prepared_accepted_context_can_initialize_tls_during_close() {
    reset(8);
    unsafe { platform::get(BORROWED.force()); }
    let root = context_get();
    let prepared = platform::prepare_thread_context(platform::Token { generation: 81, id: 1 });
    LEDGER.with(|l| l.borrow_mut().closing = true);
    context_set(std::ptr::null_mut());
    unsafe { platform::install_thread_context(prepared); platform::get(FIRST.force()); platform::retire_current().unwrap(); }
    assert_eq!(owners(), 2);
    context_set(root);
    unsafe { platform::retire_current().unwrap(); }
    assert_eq!(owners(), 0);
}

#[test]
fn prepared_but_unstarted_context_retires_without_fake_execution() {
    reset(8);
    unsafe { platform::get(BORROWED.force()); }
    let prepared = platform::prepare_thread_context(platform::Token { generation: 81, id: 1 });
    assert_eq!(owners(), 3);
    unsafe { platform::discard_unstarted_context(prepared); }
    assert_eq!(owners(), 2);
    assert_eq!(LEDGER.with(|l| l.borrow().cleanup), 0);
    unsafe { platform::retire_current().unwrap(); }
    assert_eq!(owners(), 0);
}

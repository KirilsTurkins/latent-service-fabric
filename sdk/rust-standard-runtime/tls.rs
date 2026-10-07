//! Logical-thread TLS backend for the pinned std `os` TLS implementation.
//!
//! Context slot 0 belongs to wit-bindgen. Slot 1 belongs to this maintained
//! profile and is restored by the engine when an actual guest thread resumes.
//! No process-global current-thread pointer or host-native TLS is substituted.
//! The thread/export lifecycle must call `retire_current` after its last frame.
//! This source is not selected until that lifecycle and sysroot are qualified.

use crate::alloc::{GlobalAlloc, Layout, System, handle_alloc_error};
use crate::cell::Cell;
use crate::mem::ManuallyDrop;
use crate::ptr;

pub type Key = usize;
type Destructor = unsafe extern "C" fn(*mut u8);

// Keys identify trusted static std Storage objects, not serialized addresses
// or caller-provided capabilities. Creating a key allocates no registry.
pub struct LazyKey {
    destructor: Option<Destructor>,
}

impl LazyKey {
    pub const fn new(destructor: Option<Destructor>) -> Self {
        Self { destructor }
    }

    pub fn force(&'static self) -> Key {
        self as *const Self as usize
    }
}

#[repr(C)]
#[derive(Clone, Copy)]
pub(crate) struct Token {
    pub(crate) generation: u64,
    pub(crate) id: u64,
}

// The canonical return area for result<token, error>: the result discriminant
// is at 0, with its aligned token/enum payload at 8. This shape is checked
// against the pinned generated activation binding, not a new runtime ABI.
#[repr(C, align(8))]
struct RegisterResult([u8; 24]);

struct Lease(Token);

impl Lease {
    fn acquire(continuation: Option<Token>) -> Self {
        let token = continuation.unwrap_or(Token { generation: 0, id: 0 });
        let mut result = RegisterResult([0xff; 24]);
        unsafe {
            register(7, continuation.is_some() as u32, token.generation, token.id,
                     result.0.as_mut_ptr());
        }
        match result.0[0] {
            0 => {
                let generation = u64::from_le_bytes(result.0[8..16].try_into().unwrap());
                let id = u64::from_le_bytes(result.0[16..24].try_into().unwrap());
                assert!(generation != 0 && id != 0, "invalid TLS owner token");
                Self(Token { generation, id })
            }
            1 if result.0[8] <= 6 => panic!("TLS owner admission rejected: {}", result.0[8]),
            _ => panic!("invalid TLS owner admission result"),
        }
    }
}

impl Drop for Lease {
    fn drop(&mut self) {
        // Physical TLS entries/contexts are freed before this owner is settled.
        // An error aborts the maintained panic=abort profile rather than
        // asserting physical retirement or silently refunding a live owner.
        let mut result = [0xff; 2];
        unsafe { settle(self.0.generation, self.0.id, result.as_mut_ptr()); }
        assert!(result[0] == 0, "TLS owner settlement rejected");
    }
}

struct Entry {
    key: Key,
    value: Cell<*mut u8>,
    next: *mut Entry,
    owner: ManuallyDrop<Lease>,
}

struct Context {
    head: Cell<*mut Entry>,
    closing: Cell<bool>,
    cleanup_requested: Cell<bool>,
    owner: ManuallyDrop<Lease>,
}

fn allocate<T>(value: T) -> *mut T {
    // Match pinned os::AlignedSystemBox: a user global allocator may itself
    // use thread_local!, so internal TLS storage must use System directly.
    let layout = Layout::new::<T>();
    let pointer = unsafe { System.alloc(layout) }.cast::<T>();
    if pointer.is_null() { handle_alloc_error(layout); }
    unsafe { pointer.write(value); }
    pointer
}

unsafe fn deallocate<T>(pointer: *mut T) -> T {
    let value = unsafe { pointer.read() };
    unsafe { System.dealloc(pointer.cast(), Layout::new::<T>()); }
    value
}

fn allocate_context(continuation: Option<Token>) -> *mut Context {
    let owner = Lease::acquire(continuation);
    allocate(Context {
        head: Cell::new(ptr::null_mut()), closing: Cell::new(false),
        cleanup_requested: Cell::new(false), owner: ManuallyDrop::new(owner),
    })
}

/// The maintained thread trampoline prepares this before scheduling accepted
/// work. Its actual Task token permits later TLS initialization during drain.
/// A caller must either install it exactly once or discard it before start.
pub(crate) fn prepare_thread_context(continuation: Token) -> *mut u8 {
    allocate_context(Some(continuation)).cast()
}

/// # Safety
/// `pointer` is one fresh context returned by prepare_thread_context, owned by
/// this thread. It may not be shared, installed twice or resumed after retire.
pub(crate) unsafe fn install_thread_context(pointer: *mut u8) {
    assert!(!pointer.is_null() && unsafe { context_get() }.is_null(),
            "TLS context installation must be fresh");
    unsafe { context_set(pointer); }
}

/// # Safety
/// This fresh prepared context was never installed and no TLS frame owns it.
pub(crate) unsafe fn discard_unstarted_context(pointer: *mut u8) {
    assert!(!pointer.is_null());
    let live = unsafe { &*pointer.cast::<Context>() };
    assert!(live.head.get().is_null() && !live.closing.get());
    let context = unsafe { deallocate(pointer.cast::<Context>()) };
    let owner = unsafe { ptr::read(&*context.owner) };
    drop(context);
    drop(owner);
}

fn context() -> &'static Context {
    let mut pointer = unsafe { context_get() }.cast::<Context>();
    if pointer.is_null() {
        // Admission precedes allocation. No TLS API means no context or owner.
        pointer = allocate_context(None);
        unsafe { context_set(pointer.cast()); }
    }
    // SAFETY: this profile exclusively owns slot 1; the logical thread keeps
    // its context live until all its std frames/TLS references have exited.
    unsafe { &*pointer }
}

unsafe fn entry(key: Key) -> &'static Entry {
    let context = context();
    let mut current = context.head.get();
    while !current.is_null() {
        // No mutable reference survives a callback or a suspension.
        let item = unsafe { &*current };
        if item.key == key { return item; }
        current = item.next;
    }
    // Every key entry is a real ledger Native owner. The context token keeps
    // accepted destructor work attributable during close/drain. The values
    // and entry bytes remain under the original Wasm linear-memory limiter;
    // this code introduces no replacement byte quota or second task ledger.
    let owner = Lease::acquire(Some(context.owner.0));
    let item = allocate(Entry {
        key, value: Cell::new(ptr::null_mut()), next: context.head.get(),
        owner: ManuallyDrop::new(owner),
    });
    context.head.set(item);
    unsafe { &*item }
}

/// # Safety
/// `key` must come from `force` on a live static std `LazyKey`.
pub unsafe fn get(key: Key) -> *mut u8 {
    unsafe { entry(key) }.value.get()
}

/// # Safety
/// `key` has the same contract as `get`; the std Storage owns `value` until
/// its destructor or the next set. A raw pointer is never sent to the host.
pub unsafe fn set(key: Key, value: *mut u8) {
    unsafe { entry(key) }.value.set(value);
}

pub(crate) fn mark_cleanup() {
    context().cleanup_requested.set(true);
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum RetireError {
    AlreadyClosing,
    DestructorLimit,
}

// Match the finite four-round destructor convention used by the pinned std
// OS TLS backend. Unlike an OS teardown, residual values are a hard lifecycle
// failure: their contexts/owners stay charged, not silently erased.
const DESTRUCTOR_ROUNDS: usize = 4;

fn pending_destructors(context: &Context) -> bool {
    let mut current = context.head.get();
    while !current.is_null() {
        let item = unsafe { &*current };
        let key = unsafe { &*ptr::with_exposed_provenance::<LazyKey>(item.key) };
        // Sentinel 1 still means a destructor is in progress. It cannot be
        // dereferenced or silently erased/refunded as completed work.
        if !item.value.get().is_null() && key.destructor.is_some() { return true; }
        current = item.next;
    }
    false
}

/// Destroy this actual logical thread's TLS after its last live frame.
///
/// # Safety
/// The caller owns thread/export retirement. No reference returned by std TLS
/// may remain live, and no callback or future may resume this thread afterward.
/// Other guest threads retain their independent context slots/owners.
pub(crate) unsafe fn retire_current() -> Result<(), RetireError> {
    let pointer = unsafe { context_get() }.cast::<Context>();
    if pointer.is_null() { return Ok(()); }
    let context = unsafe { &*pointer };
    if context.closing.replace(true) { return Err(RetireError::AlreadyClosing); }
    for _ in 0..DESTRUCTOR_ROUNDS {
        let mut called = false;
        let mut current = context.head.get();
        while !current.is_null() {
            let item = unsafe { &*current };
            // SAFETY: internal Key originated from a static LazyKey. Clearing
            // before callback matches std os::destroy_value's sentinel rules.
            let key = unsafe { &*ptr::with_exposed_provenance::<LazyKey>(item.key) };
            let value = item.value.get();
            if value.addr() > 1 {
                if let Some(destructor) = key.destructor {
                    item.value.set(ptr::null_mut());
                    called = true;
                    unsafe { destructor(value); }
                }
            }
            current = item.next;
        }
        if !called { break; }
    }
    if pending_destructors(context) {
        // No retry, identity reset or live-owner refund on failure.
        return Err(RetireError::DestructorLimit);
    }
    // Pinned std drops its Thread/Parker state after all user TLS destructors.
    // That state uses our LocalPointer entries, so the context stays installed.
    crate::rt::thread_cleanup();
    if pending_destructors(context) { return Err(RetireError::DestructorLimit); }
    // No callbacks remain; detach each allocation, physically free it, then
    // settle its affine owner. The canonical context remains available until
    // the last entry has retired, and is cleared before its own deallocation.
    let mut current = context.head.replace(ptr::null_mut());
    while !current.is_null() {
        let item = unsafe { deallocate(current) };
        current = item.next;
        let owner = unsafe { ptr::read(&*item.owner) };
        drop(item);
        drop(owner);
    }
    unsafe { context_set(ptr::null_mut()); }
    let context = unsafe { deallocate(pointer) };
    let owner = unsafe { ptr::read(&*context.owner) };
    drop(context);
    drop(owner);
    Ok(())
}

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "$root"))]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "[context-get-1]")]
    fn context_get() -> *mut u8;
    #[cfg_attr(target_arch = "wasm32", link_name = "[context-set-1]")]
    fn context_set(value: *mut u8);
}

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "latent:runtime/activation@0.1.0"))]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "register")]
    fn register(kind: u32, continuation: u32, generation: u64, id: u64, result: *mut u8);
    #[cfg_attr(target_arch = "wasm32", link_name = "settle")]
    fn settle(generation: u64, id: u64, result: *mut u8);
}

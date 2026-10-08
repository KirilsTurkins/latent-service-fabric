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

/// Exact memory32 prefix used by the bounded post-link stack helpers. It is
/// infrastructure state, never a serialized address or a host capability.
#[repr(C)]
struct ShadowStack {
    pointer: Cell<u32>,
    low: u32,
    high: u32,
    phase: Cell<u32>,
}

const STACK_LEGACY_TLS_ONLY: u32 = 0;
const STACK_PREPARED: u32 = 1;
const STACK_RUNNING: u32 = 2;
const STACK_FINISHING_TLS: u32 = 3;
const STACK_TLS_FINISHED: u32 = 4;
const STACK_WASM_FRAMES_EXITED: u32 = 5;

struct StackAllocation {
    pointer: *mut u8,
    layout: Layout,
}

impl Drop for StackAllocation {
    fn drop(&mut self) {
        unsafe { System.dealloc(self.pointer, self.layout); }
    }
}

#[repr(C)]
struct Context {
    // Keep this prefix first. Native offset checks and the actual encoded-Wasm
    // reader/writer controls bind all four offsets, not a Rust default layout.
    stack: ShadowStack,
    head: Cell<*mut Entry>,
    closing: Cell<bool>,
    cleanup_requested: Cell<bool>,
    owner: ManuallyDrop<Lease>,
    stack_allocation: Option<StackAllocation>,
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
        stack: ShadowStack { pointer: Cell::new(0), low: 0, high: 0,
                             phase: Cell::new(STACK_LEGACY_TLS_ONLY) },
        head: Cell::new(ptr::null_mut()), closing: Cell::new(false),
        cleanup_requested: Cell::new(false), owner: ManuallyDrop::new(owner),
        stack_allocation: None,
    })
}

/// The maintained thread trampoline prepares this before scheduling accepted
/// work. Its actual Task token permits later TLS initialization during drain.
/// A caller must either install it exactly once or discard it before start.
pub(crate) fn prepare_thread_context(continuation: Token) -> *mut u8 {
    allocate_context(Some(continuation)).cast()
}

/// Prepare the existing, instance-owned root linear stack. The owned entry
/// wrapper must install it before calling any translated Rust frame. This
/// API does not allocate, resize, free or pretend to switch that stack.
pub(crate) fn prepare_borrowed_root_context(continuation: Token, low: u32, high: u32) -> *mut u8 {
    assert!(low != 0 && low % 16 == 0 && high % 16 == 0 && high > low,
            "root stack must be a nonempty aligned memory32 range");
    assert!(high - low >= 64 * 1024, "root stack below pinned std minimum");
    let owner = Lease::acquire(Some(continuation));
    allocate(Context {
        stack: ShadowStack { pointer: Cell::new(high), low, high,
                             phase: Cell::new(STACK_PREPARED) },
        head: Cell::new(ptr::null_mut()), closing: Cell::new(false),
        cleanup_requested: Cell::new(false), owner: ManuallyDrop::new(owner),
        stack_allocation: None,
    }).cast()
}

/// Allocate an independent linear stack and its TLS/context record after the
/// real accepted Task's Native continuation has been admitted. The Task itself
/// must already be owned by the thread PAL before canonical thread creation.
/// These bytes stay under the original Wasm memory limiter, not a new quota.
/// This memory32-only path is not selected by the maintained builder yet.
pub(crate) fn prepare_stacked_thread_context(continuation: Token, bytes: usize) -> *mut u8 {
    assert!(bytes >= 64 * 1024, "logical stack below pinned std minimum");
    let size = bytes.checked_add(15).expect("logical stack size overflow") & !15;
    let layout = Layout::from_size_align(size, 16).expect("invalid logical stack layout");
    let size32 = u32::try_from(size).expect("logical stack exceeds memory32");
    let owner = Lease::acquire(Some(continuation));
    let pointer = unsafe { System.alloc(layout) };
    if pointer.is_null() { handle_alloc_error(layout); }
    // On a source-reference host, a failed memory32 check still frees this
    // actual allocation before unwinding/settling its admitted Native owner.
    let allocation = StackAllocation { pointer, layout };
    let low = u32::try_from(pointer.addr()).expect("logical stack is not memory32");
    let high = low.checked_add(size32).expect("logical stack address overflow");
    assert!(low != 0 && low % 16 == 0 && high % 16 == 0);
    allocate(Context {
        stack: ShadowStack { pointer: Cell::new(high), low, high,
                             phase: Cell::new(STACK_PREPARED) },
        head: Cell::new(ptr::null_mut()), closing: Cell::new(false),
        cleanup_requested: Cell::new(false), owner: ManuallyDrop::new(owner),
        stack_allocation: Some(allocation),
    }).cast()
}

/// # Safety
/// `pointer` is one fresh context returned by prepare_thread_context, owned by
/// this thread. It may not be shared, installed twice or resumed after retire.
pub(crate) unsafe fn install_thread_context(pointer: *mut u8) {
    assert!(!pointer.is_null() && unsafe { context_get() }.is_null(),
            "TLS context installation must be fresh");
    let context = unsafe { &*pointer.cast::<Context>() };
    if context.stack.phase.get() != STACK_LEGACY_TLS_ONLY {
        assert_eq!(context.stack.phase.get(), STACK_PREPARED,
                   "stacked context installation must be unstarted");
        context.stack.phase.set(STACK_RUNNING);
    }
    unsafe { context_set(pointer); }
}

/// # Safety
/// This fresh prepared context was never installed and no TLS frame owns it.
pub(crate) unsafe fn discard_unstarted_context(pointer: *mut u8) {
    assert!(!pointer.is_null());
    let live = unsafe { &*pointer.cast::<Context>() };
    assert!(live.head.get().is_null() && !live.closing.get());
    assert!(matches!(live.stack.phase.get(), STACK_LEGACY_TLS_ONLY | STACK_PREPARED));
    assert_ne!(unsafe { context_get() }, pointer, "discard requires an uninstalled context");
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
    LiveShadowStack,
    WrongStackPhase,
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
    // Clearing/freeing a stack-bearing context from Rust would invalidate the
    // caller's own remaining shadow-stack epilogue. Only the stackless encoded
    // entry wrapper may detach it after the last Rust frame has returned.
    if context.stack.phase.get() != STACK_LEGACY_TLS_ONLY { return Err(RetireError::LiveShadowStack); }
    unsafe { finish_tls(context)?; }
    unsafe { context_set(ptr::null_mut()); }
    let context = unsafe { deallocate(pointer) };
    let owner = unsafe { ptr::read(&*context.owner) };
    drop(context);
    drop(owner);
    Ok(())
}

/// Run TLS/std cleanup while the actual stack and context are still installed.
/// The final Rust epilogue still uses this prefix. No context/stack owner is
/// settled, cleared or freed by this phase.
pub(crate) unsafe fn finish_stacked_thread_tls() -> Result<(), RetireError> {
    let pointer = unsafe { context_get() }.cast::<Context>();
    if pointer.is_null() { return Err(RetireError::WrongStackPhase); }
    let context = unsafe { &*pointer };
    if context.stack.phase.get() != STACK_RUNNING {
        return Err(RetireError::WrongStackPhase);
    }
    context.stack.phase.set(STACK_FINISHING_TLS);
    unsafe { finish_tls(context)?; }
    context.stack.phase.set(STACK_TLS_FINISHED);
    Ok(())
}

unsafe fn finish_tls(context: &Context) -> Result<(), RetireError> {
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
    // No callbacks remain; detach/free each TLS entry before settling its
    // owner. The context and shadow stack remain installed through return.
    let mut current = context.head.replace(ptr::null_mut());
    while !current.is_null() {
        let item = unsafe { deallocate(current) };
        current = item.next;
        let owner = unsafe { ptr::read(&*item.owner) };
        drop(item);
        drop(owner);
    }
    Ok(())
}

/// # Safety
/// The parent/reaper owns this distinct context and has established canonical
/// thread completion and no remaining native continuation. The wrapper's
/// WASM_FRAMES_EXITED word alone is not proof of host-fiber physical retirement.
/// This cleanup must run on another live context/stack, never the retired one.
pub(crate) unsafe fn retire_exited_thread_context(pointer: *mut u8) -> Result<(), RetireError> {
    let current = unsafe { context_get() };
    assert!(!pointer.is_null() && !current.is_null() && current != pointer,
            "thread reaping must use a different live context");
    let live = unsafe { &*pointer.cast::<Context>() };
    if live.stack.phase.get() != STACK_WASM_FRAMES_EXITED
            || !live.closing.get() || !live.head.get().is_null() {
        return Err(RetireError::WrongStackPhase);
    }
    // All Wasm/Rust frames are gone and the caller supplied actual native
    // completion proof. Context and any owned stack retire before Native settle;
    // the borrowed instance stack remains owned by its admitted instance.
    let context = unsafe { deallocate(pointer.cast::<Context>()) };
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

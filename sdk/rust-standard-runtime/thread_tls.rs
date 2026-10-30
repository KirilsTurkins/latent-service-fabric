//! Selected std-thread TLS derivation; original tls.rs/default profiles stay unchanged.
//! Logical-thread TLS backend for the pinned std `os` TLS implementation.
//!
//! Context slot 0 belongs to wit-bindgen. Slot 1 belongs to this maintained
//! profile and is restored by the engine when an actual guest thread resumes.
//! No process-global current-thread pointer or host-native TLS is substituted.
//! The thread/export lifecycle must call `retire_current` after its last frame.
//! This source is not selected until that lifecycle and sysroot are qualified.

use crate::alloc::{handle_alloc_error, GlobalAlloc, Layout, System};
use crate::cell::{Cell, UnsafeCell};
use crate::mem::{ManuallyDrop, MaybeUninit};
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
        Self::acquire_kind(7, continuation)
    }

    fn acquire_kind(kind: u32, continuation: Option<Token>) -> Self {
        Self::try_acquire_kind(kind, continuation)
            .unwrap_or_else(|error| panic!("TLS owner admission rejected: {}", error))
    }
    fn try_acquire_kind(kind: u32, continuation: Option<Token>) -> Result<Self, u8> {
        let token = continuation.unwrap_or(Token {
            generation: 0,
            id: 0,
        });
        let mut result = RegisterResult([0xff; 24]);
        unsafe {
            register(
                kind,
                continuation.is_some() as u32,
                token.generation,
                token.id,
                result.0.as_mut_ptr(),
            );
        }
        match result.0[0] {
            0 => {
                let token = Token {
                    generation: u64::from_le_bytes(result.0[8..16].try_into().unwrap()),
                    id: u64::from_le_bytes(result.0[16..24].try_into().unwrap()),
                };
                assert!(
                    token.generation != 0 && token.id != 0,
                    "invalid TLS owner token"
                );
                Ok(Self(token))
            }
            1 if result.0[8] <= 6 => Err(result.0[8]),
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
        unsafe {
            settle(self.0.generation, self.0.id, result.as_mut_ptr());
        }
        assert!(result[0] == 0, "TLS owner settlement rejected");
    }
}

struct Entry {
    key: Key,
    value: Cell<*mut u8>,
    next: *mut Entry,
}

// A Native owner follows one actual System allocation, not each logical TLS
// key stored inside it. Amortizing the small entries prevents ordinary std
// bookkeeping from consuming the activation's finite Native-owner capacity
// while retaining admission-before-allocation and bounded growth.
const ENTRIES_PER_BLOCK: usize = 32;

struct EntryBlock {
    next: *mut EntryBlock,
    used: Cell<usize>,
    entries: UnsafeCell<[MaybeUninit<Entry>; ENTRIES_PER_BLOCK]>,
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
    // V2 keeps the original16-byte stack prefix and appends one accepted Task
    // continuation plus the fixed child admission result/one-shot guard.
    continuation: Token,
    admission: Cell<[u8; 2]>,
    creation_started: Cell<u8>,
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

#[derive(Clone, Copy)]
struct RootDrain {
    state: *mut u8,
    run: unsafe fn(*mut u8) -> bool,
    // This final release may use only System and must invoke no application
    // callback or TLS after the final translated root frame has returned.
    release: unsafe fn(*mut u8),
}

impl Drop for StackAllocation {
    fn drop(&mut self) {
        unsafe {
            System.dealloc(self.pointer, self.layout);
        }
    }
}

#[repr(C)]
struct Context {
    // Keep this prefix first. Native offset checks and the actual encoded-Wasm
    // reader/writer controls bind all four offsets, not a Rust default layout.
    stack: ShadowStack,
    head: Cell<*mut Entry>,
    blocks: Cell<*mut EntryBlock>,
    closing: Cell<bool>,
    cleanup_requested: Cell<bool>,
    owner: ManuallyDrop<Cell<Option<Lease>>>,
    stack_allocation: Option<StackAllocation>,
    // Only first accepted root concurrency owns this Task. Pure bootstrap and
    // TLS-only root access admit no Task. Child Tasks belong to the real PAL.
    root_task: ManuallyDrop<Cell<Option<Lease>>>,
    root_drain: Cell<Option<RootDrain>>,
    draining: Cell<bool>,
}

// Bind the fixed encoded wrapper's offsets on the actual compiling target,
// including memory32. A source-reference host alone cannot establish layout.
const _: () = {
    assert!(crate::mem::size_of::<ShadowStack>() == 40);
    assert!(crate::mem::align_of::<ShadowStack>() == 8);
    assert!(crate::mem::offset_of!(ShadowStack, continuation) == 16);
    assert!(crate::mem::offset_of!(ShadowStack, admission) == 32);
    assert!(crate::mem::offset_of!(ShadowStack, creation_started) == 34);
    assert!(crate::mem::offset_of!(Context, head) == 40);
};

fn allocate<T>(value: T) -> *mut T {
    // Match pinned os::AlignedSystemBox: a user global allocator may itself
    // use thread_local!, so internal TLS storage must use System directly.
    let layout = Layout::new::<T>();
    let pointer = unsafe { System.alloc(layout) }.cast::<T>();
    if pointer.is_null() {
        handle_alloc_error(layout);
    }
    unsafe {
        pointer.write(value);
    }
    pointer
}

unsafe fn deallocate<T>(pointer: *mut T) -> T {
    let value = unsafe { pointer.read() };
    unsafe {
        System.dealloc(pointer.cast(), Layout::new::<T>());
    }
    value
}

fn allocate_context(continuation: Option<Token>) -> *mut Context {
    let owner = Lease::acquire(continuation);
    allocate(Context {
        stack: ShadowStack {
            pointer: Cell::new(0),
            low: 0,
            high: 0,
            phase: Cell::new(STACK_LEGACY_TLS_ONLY),
            continuation: continuation.unwrap_or(Token {
                generation: 0,
                id: 0,
            }),
            admission: Cell::new([0xff; 2]),
            creation_started: Cell::new(0),
        },
        head: Cell::new(ptr::null_mut()),
        blocks: Cell::new(ptr::null_mut()),
        closing: Cell::new(false),
        cleanup_requested: Cell::new(false),
        owner: ManuallyDrop::new(Cell::new(Some(owner))),
        stack_allocation: None,
        root_task: ManuallyDrop::new(Cell::new(None)),
        root_drain: Cell::new(None),
        draining: Cell::new(false),
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
    assert!(
        low != 0 && low % 16 == 0 && high % 16 == 0 && high > low,
        "root stack must be a nonempty aligned memory32 range"
    );
    assert!(
        high - low >= 64 * 1024,
        "root stack below pinned std minimum"
    );
    let owner = Lease::acquire(Some(continuation));
    allocate(Context {
        stack: ShadowStack {
            pointer: Cell::new(high),
            low,
            high,
            phase: Cell::new(STACK_PREPARED),
            continuation,
            admission: Cell::new([0xff; 2]),
            creation_started: Cell::new(0),
        },
        head: Cell::new(ptr::null_mut()),
        blocks: Cell::new(ptr::null_mut()),
        closing: Cell::new(false),
        cleanup_requested: Cell::new(false),
        owner: ManuallyDrop::new(Cell::new(Some(owner))),
        stack_allocation: None,
        root_task: ManuallyDrop::new(Cell::new(None)),
        root_drain: Cell::new(None),
        draining: Cell::new(false),
    })
    .cast()
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
    if pointer.is_null() {
        handle_alloc_error(layout);
    }
    // On a source-reference host, a failed memory32 check still frees this
    // actual allocation before unwinding/settling its admitted Native owner.
    let allocation = StackAllocation { pointer, layout };
    let low = u32::try_from(pointer.addr()).expect("logical stack is not memory32");
    let high = low
        .checked_add(size32)
        .expect("logical stack address overflow");
    assert!(low != 0 && low % 16 == 0 && high % 16 == 0);
    allocate(Context {
        stack: ShadowStack {
            pointer: Cell::new(high),
            low,
            high,
            phase: Cell::new(STACK_PREPARED),
            continuation,
            admission: Cell::new([0xff; 2]),
            creation_started: Cell::new(0),
        },
        head: Cell::new(ptr::null_mut()),
        blocks: Cell::new(ptr::null_mut()),
        closing: Cell::new(false),
        cleanup_requested: Cell::new(false),
        owner: ManuallyDrop::new(Cell::new(Some(owner))),
        stack_allocation: Some(allocation),
        root_task: ManuallyDrop::new(Cell::new(None)),
        root_drain: Cell::new(None),
        draining: Cell::new(false),
    })
    .cast()
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum ContextError {
    Admission(u8),
    Allocation,
    Layout,
}

/// Ordinary Builder::spawn's fallible selected path. The accepted Task already
/// exists; its Native context owner precedes BOTH System allocations. Failure
/// destroys actual backing before settling that owner and starts no thread.
pub(crate) fn try_prepare_stacked_thread_context(
    continuation: Token,
    bytes: usize,
) -> Result<*mut u8, ContextError> {
    if continuation.generation == 0 || continuation.id == 0 || bytes < 64 * 1024 {
        return Err(ContextError::Layout);
    }
    let size = bytes.checked_add(15).ok_or(ContextError::Layout)? & !15;
    let size32 = u32::try_from(size).map_err(|_| ContextError::Layout)?;
    let layout = Layout::from_size_align(size, 16).map_err(|_| ContextError::Layout)?;
    let owner = Lease::try_acquire_kind(7, Some(continuation)).map_err(ContextError::Admission)?;
    let pointer = unsafe { System.alloc(layout) };
    if pointer.is_null() {
        return Err(ContextError::Allocation);
    }
    let allocation = StackAllocation { pointer, layout };
    let low = u32::try_from(pointer.addr()).map_err(|_| ContextError::Layout)?;
    let high = low.checked_add(size32).ok_or(ContextError::Layout)?;
    if low == 0 || low % 16 != 0 || high % 16 != 0 {
        return Err(ContextError::Layout);
    }
    let pointer = unsafe { System.alloc(Layout::new::<Context>()) }.cast::<Context>();
    if pointer.is_null() {
        return Err(ContextError::Allocation);
    }
    unsafe {
        pointer.write(Context {
            stack: ShadowStack {
                pointer: Cell::new(high),
                low,
                high,
                phase: Cell::new(STACK_PREPARED),
                continuation,
                admission: Cell::new([0xff; 2]),
                creation_started: Cell::new(0),
            },
            head: Cell::new(ptr::null_mut()),
            blocks: Cell::new(ptr::null_mut()),
            closing: Cell::new(false),
            cleanup_requested: Cell::new(false),
            owner: ManuallyDrop::new(Cell::new(Some(owner))),
            stack_allocation: Some(allocation),
            root_task: ManuallyDrop::new(Cell::new(None)),
            root_drain: Cell::new(None),
            draining: Cell::new(false),
        });
    }
    Ok(pointer.cast())
}

/// Read only the compiler's selected fallible prestart result. The old trapping
/// wrapper does not satisfy this contract and must not select the std profile.
pub(crate) unsafe fn creation_result(pointer: *mut u8) -> Result<(), u8> {
    let live = unsafe { &*pointer.cast::<Context>() };
    let result = live.stack.admission.get();
    match (live.stack.creation_started.get(), result) {
        (0, [1, error @ 0..=6]) => Err(error),
        (1, [0, _]) => Ok(()),
        _ => panic!("selected fallible native prestart contract not installed"),
    }
}

/// Copy-only post-handoff inspection. Phase5 is meaningful ONLY with the
/// authenticated fixed wrapper: it checks restored SP/TLS and has no yielding
/// or user work between marking5, detach and actual canonical return. Host
/// StackMemory retirement remains independently charged through its real Drop.
pub(crate) unsafe fn frames_exited(pointer: *mut u8) -> bool {
    assert!(!pointer.is_null() && unsafe { context_get() } != pointer);
    let live = unsafe { &*pointer.cast::<Context>() };
    live.stack.phase.get() == STACK_WASM_FRAMES_EXITED
        && live.stack.pointer.get() == live.stack.high
        && live.closing.get()
        && live.head.get().is_null()
        && live.blocks.get().is_null()
}

pub(crate) fn installed_context() -> *mut u8 {
    unsafe { context_get() }
}
pub(crate) fn root_context_installed() -> bool {
    is_static_root(context())
}

/// # Safety
/// `pointer` is one fresh context returned by prepare_thread_context, owned by
/// this thread. It may not be shared, installed twice or resumed after retire.
pub(crate) unsafe fn install_thread_context(pointer: *mut u8) {
    assert!(
        !pointer.is_null() && unsafe { context_get() }.is_null(),
        "TLS context installation must be fresh"
    );
    let context = unsafe { &*pointer.cast::<Context>() };
    if context.stack.phase.get() != STACK_LEGACY_TLS_ONLY {
        assert_eq!(
            context.stack.phase.get(),
            STACK_PREPARED,
            "stacked context installation must be unstarted"
        );
        context.stack.phase.set(STACK_RUNNING);
    }
    unsafe {
        context_set(pointer);
    }
}

/// Called only by the authenticated stackless root wrapper. The linker-owned
/// range is passed as exact memory32 bounds, before any translated root frame.
/// This selected hook uses fixed in-component backing without owner admission.
/// It does not close/drain accepted work or enable an incomplete std profile.
#[cfg_attr(target_arch = "wasm32", unsafe(no_mangle))]
pub unsafe extern "C" fn __lsf_rust_root_bootstrap(low: u32, high: u32) -> *mut u8 {
    prepare_owned_root_context(low, high)
}

pub(crate) fn prepare_owned_root_context(low: u32, high: u32) -> *mut u8 {
    assert!(
        unsafe { context_get() }.is_null(),
        "root context must be fresh"
    );
    assert!(
        low != 0 && low % 16 == 0 && high % 16 == 0 && high > low && high - low >= 64 * 1024,
        "invalid linker-owned root stack"
    );
    assert!(!ROOT.live.replace(true), "one nonreentrant selected root");
    let pointer = ROOT.context.get().cast::<Context>();
    unsafe {
        pointer.write(Context {
            stack: ShadowStack {
                pointer: Cell::new(high),
                low,
                high,
                phase: Cell::new(STACK_PREPARED),
                continuation: Token {
                    generation: 0,
                    id: 0,
                },
                admission: Cell::new([0xff; 2]),
                creation_started: Cell::new(0),
            },
            head: Cell::new(ptr::null_mut()),
            blocks: Cell::new(ptr::null_mut()),
            closing: Cell::new(false),
            cleanup_requested: Cell::new(false),
            owner: ManuallyDrop::new(Cell::new(None)),
            stack_allocation: None,
            root_task: ManuallyDrop::new(Cell::new(None)),
            root_drain: Cell::new(None),
            draining: Cell::new(false),
        });
    }
    // Fixed in-component backing is within original linear memory. Bootstrap
    // admits no Task/Native, allocates no backing, and invokes no callback/TLS.
    pointer.cast()
}

/// Compiler-owned std threading installs its activation-local registry only
/// on first accepted concurrency. There is no allocation or callback in the
/// lazy no-concurrency path. Applications retain ordinary std call sites.
///
/// # Safety
/// `state` belongs exclusively to this root through its final System reaper.
/// `run` must drain real accepted continuations without retaining an exclusive
/// Rust borrow across suspension; false means unfinished work, never success.
/// `release` must require an empty registry and free only System-owned bytes.
pub(crate) unsafe fn install_root_drain(
    state: *mut u8,
    run: unsafe fn(*mut u8) -> bool,
    release: unsafe fn(*mut u8),
) {
    let root = context();
    assert!(
        !state.is_null()
            && root_task_token(root).is_some()
            && matches!(root.stack.phase.get(), STACK_RUNNING | STACK_FINISHING_TLS)
            && root.root_drain.get().is_none(),
        "root drain installation must be fresh"
    );
    root.root_drain.set(Some(RootDrain {
        state,
        run,
        release,
    }));
}

fn drain_root(context: &Context) -> Result<(), RetireError> {
    let Some(drain) = context.root_drain.get() else {
        return Ok(());
    };
    if context.draining.replace(true) {
        return Err(RetireError::AlreadyClosing);
    }
    let complete = unsafe { (drain.run)(drain.state) };
    context.draining.set(false);
    if complete {
        Ok(())
    } else {
        Err(RetireError::AcceptedWorkPending)
    }
}

/// The compiler-owned std drainer must complete accepted work before cleanup.
/// Context and owners remain live through the final translated Rust epilogue.
#[cfg_attr(target_arch = "wasm32", unsafe(no_mangle))]
pub unsafe extern "C" fn __lsf_rust_root_finish(pointer: *mut u8) {
    assert!(
        !pointer.is_null() && unsafe { context_get() } == pointer,
        "root finish requires its installed context"
    );
    let context = unsafe { &*pointer.cast::<Context>() };
    assert!(
        is_static_root(context) && context.stack_allocation.is_none(),
        "root finish requires its admitted borrowed stack"
    );
    unsafe {
        finish_stacked_thread_tls().expect("root TLS drain failed");
    }
}

/// System-only postlude after the stackless wrapper detached the root and all
/// translated Rust frames returned. Logical context/Task retirement is distinct
/// from physical Wasmtime stack retirement: the host retains its reservation
/// through the actual StackMemory/Store destructor, never this guest flag.
#[cfg_attr(target_arch = "wasm32", unsafe(no_mangle))]
pub unsafe extern "C" fn __lsf_rust_root_reap(pointer: *mut u8) {
    assert!(
        !pointer.is_null() && unsafe { context_get() }.is_null(),
        "root reaper requires a detached context"
    );
    let live = unsafe { &*pointer.cast::<Context>() };
    assert!(
        is_static_root(live)
            && live.stack_allocation.is_none()
            && live.stack.phase.get() == STACK_WASM_FRAMES_EXITED
            && live.stack.pointer.get() == live.stack.high
            && live.closing.get()
            && live.head.get().is_null()
            && live.blocks.get().is_null(),
        "root reaper requires completed logical TLS/frame retirement"
    );
    let drain = live.root_drain.get();
    let owner = live.owner.take();
    let task = live.root_task.take();
    // No fabricated System free for fixed in-component backing. The record is
    // reusable only after all actual root frames/TLS and continuations exited.
    if let Some(drain) = drain {
        unsafe {
            (drain.release)(drain.state);
        }
    }
    drop(owner);
    drop(task);
    ROOT.live.set(false);
}

/// # Safety
/// This fresh prepared context was never installed and no TLS frame owns it.
pub(crate) unsafe fn discard_unstarted_context(pointer: *mut u8) {
    assert!(!pointer.is_null());
    let live = unsafe { &*pointer.cast::<Context>() };
    assert!(
        !is_static_root(live),
        "fixed root must use its final root reaper"
    );
    assert!(
        live.head.get().is_null() && live.blocks.get().is_null() && !live.closing.get()
    );
    assert!(
        root_task_token(live).is_none(),
        "root context requires its owned root lifecycle"
    );
    assert!(matches!(
        live.stack.phase.get(),
        STACK_LEGACY_TLS_ONLY | STACK_PREPARED
    ));
    assert_ne!(
        unsafe { context_get() },
        pointer,
        "discard requires an uninstalled context"
    );
    let context = unsafe { deallocate(pointer.cast::<Context>()) };
    let owner = context.owner.take();
    drop(context);
    drop(owner);
}

fn context() -> &'static Context {
    let mut pointer = unsafe { context_get() }.cast::<Context>();
    if pointer.is_null() {
        // Admission precedes allocation. No TLS API means no context or owner.
        pointer = allocate_context(None);
        unsafe {
            context_set(pointer.cast());
        }
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
        if item.key == key {
            return item;
        }
        current = item.next;
    }
    let mut block = context.blocks.get();
    if block.is_null() || unsafe { &*block }.used.get() == ENTRIES_PER_BLOCK {
        // One accepted Native owner covers this one physical block allocation.
        // The context token keeps accepted destructor work attributable during
        // close/drain. Block and value bytes remain charged to the original
        // Wasm linear-memory limiter; there is no replacement byte quota.
        let owner = Lease::acquire(Some(ensure_context_owner(context)));
        block = allocate(EntryBlock {
            next: block,
            used: Cell::new(0),
            entries: UnsafeCell::new([const { MaybeUninit::uninit() }; ENTRIES_PER_BLOCK]),
            owner: ManuallyDrop::new(owner),
        });
        context.blocks.set(block);
    }
    let block_ref = unsafe { &*block };
    let index = block_ref.used.get();
    let item = unsafe {
        block_ref
            .entries
            .get()
            .cast::<MaybeUninit<Entry>>()
            .add(index)
            .cast::<Entry>()
    };
    unsafe { item.write(Entry {
        key,
        value: Cell::new(ptr::null_mut()),
        next: context.head.get(),
    }) };
    block_ref.used.set(index + 1);
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
    AcceptedWorkPending,
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
        if !item.value.get().is_null() && key.destructor.is_some() {
            return true;
        }
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
    if pointer.is_null() {
        return Ok(());
    }
    let context = unsafe { &*pointer };
    // Clearing/freeing a stack-bearing context from Rust would invalidate the
    // caller's own remaining shadow-stack epilogue. Only the stackless encoded
    // entry wrapper may detach it after the last Rust frame has returned.
    if context.stack.phase.get() != STACK_LEGACY_TLS_ONLY {
        return Err(RetireError::LiveShadowStack);
    }
    unsafe {
        finish_tls(context)?;
    }
    unsafe {
        context_set(ptr::null_mut());
    }
    let context = unsafe { deallocate(pointer) };
    let owner = context.owner.take();
    drop(context);
    drop(owner);
    Ok(())
}

/// Run TLS/std cleanup while the actual stack and context are still installed.
/// The final Rust epilogue still uses this prefix. No context/stack owner is
/// settled, cleared or freed by this phase.
pub(crate) unsafe fn finish_stacked_thread_tls() -> Result<(), RetireError> {
    let pointer = unsafe { context_get() }.cast::<Context>();
    if pointer.is_null() {
        return Err(RetireError::WrongStackPhase);
    }
    let context = unsafe { &*pointer };
    if context.stack.phase.get() != STACK_RUNNING {
        return Err(RetireError::WrongStackPhase);
    }
    drain_root(context)?;
    context.stack.phase.set(STACK_FINISHING_TLS);
    unsafe {
        finish_tls(context)?;
    }
    context.stack.phase.set(STACK_TLS_FINISHED);
    Ok(())
}

unsafe fn finish_tls(context: &Context) -> Result<(), RetireError> {
    if context.closing.replace(true) {
        return Err(RetireError::AlreadyClosing);
    }
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
                    unsafe {
                        destructor(value);
                    }
                    // A root TLS destructor may accept a child through std.
                    // Drain it while this actual root stack/context is live,
                    // before freeing any entry or settling its logical owner.
                    drain_root(context)?;
                }
            }
            current = item.next;
        }
        if !called {
            break;
        }
    }
    if pending_destructors(context) {
        // No retry, identity reset or live-owner refund on failure.
        return Err(RetireError::DestructorLimit);
    }
    // Pinned std drops its Thread/Parker state after all user TLS destructors.
    // That state uses our LocalPointer entries, so the context stays installed.
    crate::rt::thread_cleanup();
    drain_root(context)?;
    if pending_destructors(context) {
        return Err(RetireError::DestructorLimit);
    }
    // No callbacks remain; detach all logical entries, then free each physical
    // block before settling that block's Native owner. The context and shadow
    // stack remain installed through return.
    context.head.set(ptr::null_mut());
    let mut current = context.blocks.replace(ptr::null_mut());
    while !current.is_null() {
        let block = unsafe { deallocate(current) };
        current = block.next;
        let owner = unsafe { ptr::read(&*block.owner) };
        drop(block);
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
    assert!(
        !pointer.is_null() && !current.is_null() && current != pointer,
        "thread reaping must use a different live context"
    );
    let live = unsafe { &*pointer.cast::<Context>() };
    if is_static_root(live)
        || live.stack.phase.get() != STACK_WASM_FRAMES_EXITED
        || !live.closing.get()
        || !live.head.get().is_null()
        || !live.blocks.get().is_null()
        || root_task_token(live).is_some()
    {
        return Err(RetireError::WrongStackPhase);
    }
    // All Wasm/Rust frames are gone and the caller supplied actual native
    // completion proof. Context and any owned stack retire before Native settle;
    // the borrowed instance stack remains owned by its admitted instance.
    let context = unsafe { deallocate(pointer.cast::<Context>()) };
    let owner = context.owner.take();
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

#[cfg_attr(
    target_arch = "wasm32",
    link(wasm_import_module = "latent:runtime/activation@0.1.0")
)]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "register")]
    fn register(kind: u32, continuation: u32, generation: u64, id: u64, result: *mut u8);
    #[cfg_attr(target_arch = "wasm32", link_name = "settle")]
    fn settle(generation: u64, id: u64, result: *mut u8);
}

// Selected std-thread profile ONLY: trusted cooperative nonreentrant Store,
// one unshared memory. This fixed backing is not host-native or process TLS.
struct RootStorage {
    live: Cell<bool>,
    context: UnsafeCell<MaybeUninit<Context>>,
}
unsafe impl Sync for RootStorage {}
static ROOT: RootStorage = RootStorage {
    live: Cell::new(false),
    context: UnsafeCell::new(MaybeUninit::uninit()),
};
fn is_static_root(context: &Context) -> bool {
    ROOT.live.get() && ptr::eq(context, ROOT.context.get().cast::<Context>())
}
fn root_task_token(context: &Context) -> Option<Token> {
    // Copy only the token: no Cell reference survives a broker call.
    unsafe { (&*context.root_task.as_ptr()).as_ref().map(|owner| owner.0) }
}
fn ensure_context_owner(context: &Context) -> Token {
    let existing = unsafe { (&*context.owner.as_ptr()).as_ref().map(|owner| owner.0) };
    if let Some(token) = existing {
        return token;
    }
    assert!(
        is_static_root(context),
        "only fixed root may have no Native owner"
    );
    let owner = Lease::acquire(root_task_token(context));
    let token = owner.0;
    assert!(
        context.owner.replace(Some(owner)).is_none(),
        "duplicate root Native admission"
    );
    token
}
/// First accepted std concurrency calls this before registry allocation.
/// Task refusal stays typed for ordinary fallible Builder::spawn. A pure root
/// never calls it; Native TLS entry admission alone also creates no Task.
pub(crate) fn ensure_thread_continuation() -> Result<Token, u8> {
    let context = context();
    assert!(
        matches!(
            context.stack.phase.get(),
            STACK_RUNNING | STACK_FINISHING_TLS
        ),
        "thread continuation must precede actual TLS/frame exit"
    );
    if !is_static_root(context) {
        let token = context.stack.continuation;
        assert!(
            token.generation != 0 && token.id != 0,
            "child must own original Task"
        );
        return Ok(token);
    }
    if let Some(token) = root_task_token(context) {
        return Ok(token);
    }
    let task = Lease::try_acquire_kind(0, None)?;
    let token = task.0;
    assert!(
        context.root_task.replace(Some(task)).is_none(),
        "duplicate root Task admission"
    );
    Ok(token)
}

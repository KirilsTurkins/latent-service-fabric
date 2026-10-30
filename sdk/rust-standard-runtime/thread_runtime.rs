// SPDX-License-Identifier: MIT OR Apache-2.0
//! Selected cooperative std PAL: actual canonical children and original owners.
//! No user closure is polled on the root as a substitute for a real thread.
//! Only the initial known unstarted/Ready handshake explicitly promotes a
//! target. Ordinary progress uses the engine's own ready queue; a Running
//! record may be inside an engine host-await and is NEVER manually promoted.
use crate::cell::UnsafeCell;
use crate::io;
use crate::ptr::{self, NonNull};
use crate::sys::thread::lsf::wait::WaitQueue;
use crate::sys::thread_local::key::lsf as tls;
use crate::thread::ThreadInit;

pub(crate) mod executor_bridge;
pub(crate) mod executor_control;
pub(crate) mod executor_lifecycle;
pub(crate) mod executor_root;
pub(crate) mod executor_worker;
pub(crate) mod owner;
pub(crate) mod registry;
mod start;
mod wait_driver;
mod wait_registry;
pub(crate) use owner::Token;
use owner::{AllocationError, Error, Kind, Owner, SystemOwned};
pub(crate) use registry::Handle;
pub(crate) use wait_driver::{
    allocate_wait_node, deallocate_wait_node, drive_wait, register_wait, unregister_wait, wake_wait,
    WaitLease,
};

struct Child {
    task: Owner,
    context: NonNull<u8>,
    bootstrap: Option<NonNull<start::Bootstrap>>,
    parent: u32,
    executor: Option<executor_worker::Lease>,
}
struct Runtime {
    root: u32,
    registry: UnsafeCell<registry::Registry>,
    children: UnsafeCell<[Option<Child>; registry::MAX_THREADS]>,
    executors: UnsafeCell<executor_root::Registry>,
    joins: [WaitQueue; registry::MAX_THREADS],
    completed: WaitQueue,
}
// One activation-local linear-memory pointer. Selection refuses shared memory
// and reentrant exports. No process TLS, host scheduler, or ambient authority.
struct Storage(UnsafeCell<*mut Runtime>);
unsafe impl Sync for Storage {}
static RUNTIME: Storage = Storage(UnsafeCell::new(ptr::null_mut()));
fn existing() -> *mut Runtime {
    unsafe { *RUNTIME.0.get() }
}
fn reg<R>(f: impl FnOnce(&mut registry::Registry) -> R) -> R {
    let runtime = existing();
    assert!(!runtime.is_null(), "std thread runtime not installed");
    // Borrow only this disjoint field, never the Runtime aggregate: shared
    // references to its stable WaitQueues may remain live through suspension.
    unsafe { f(&mut *(*runtime).registry.get()) }
}
fn children<R>(f: impl FnOnce(&mut [Option<Child>; registry::MAX_THREADS]) -> R) -> R {
    let runtime = existing();
    assert!(!runtime.is_null(), "std child backing missing");
    unsafe { f(&mut *(*runtime).children.get()) }
}
fn join_queue(handle: Handle) -> &'static WaitQueue {
    unsafe {
        &*ptr::addr_of!((*existing()).joins)
            .cast::<WaitQueue>()
            .add(handle.slot())
    }
}
fn completed_queue() -> &'static WaitQueue {
    unsafe { &*ptr::addr_of!((*existing()).completed) }
}
pub(crate) fn current_index() -> u32 {
    unsafe { thread_index() }
}
fn try_current_task() -> Result<Token, Error> {
    let token = tls::ensure_thread_continuation().map_err(owner::error)?;
    let token = Token {
        generation: token.generation,
        id: token.id,
    };
    assert!(token.valid(), "selected TLS returned an absent Task");
    Ok(token)
}
pub(crate) fn current_task() -> Token {
    try_current_task().unwrap_or_else(|error| panic!("std current Task unavailable: {:?}", error))
}
fn io_error(error: Error) -> io::Error {
    io::Error::from(match error {
        Error::Unavailable => io::ErrorKind::Unsupported,
        Error::PermissionDenied => io::ErrorKind::PermissionDenied,
        Error::ResourceExhausted => io::ErrorKind::WouldBlock,
        Error::Cancelled => io::ErrorKind::Interrupted,
        Error::Deadline => io::ErrorKind::TimedOut,
        Error::InvalidState | Error::InvalidToken => io::ErrorKind::InvalidInput,
    })
}
fn allocation_error(error: AllocationError) -> io::Error {
    match error {
        AllocationError::Admission(error) => io_error(error),
        AllocationError::Allocation => io::Error::from(io::ErrorKind::OutOfMemory),
    }
}
fn ensure_runtime() -> io::Result<()> {
    if !existing().is_null() {
        return Ok(());
    }
    assert!(
        tls::root_context_installed(),
        "first std concurrency requires the actual root"
    );
    let task = try_current_task().map_err(io_error)?;
    let root = current_index();
    let runtime = SystemOwned::try_new(
        Runtime {
            root,
            registry: UnsafeCell::new(registry::Registry::new(root)),
            children: UnsafeCell::new(crate::array::from_fn(|_| None)),
            executors: UnsafeCell::new(executor_root::Registry::new()),
            joins: crate::array::from_fn(|_| WaitQueue::new()),
            completed: WaitQueue::new(),
        },
        Some(task),
    )
    .map_err(allocation_error)?;
    let pointer = runtime.into_raw().as_ptr();
    assert!(existing().is_null(), "reentrant std runtime construction");
    unsafe {
        *RUNTIME.0.get() = pointer;
        tls::install_root_drain(pointer.cast(), drain, release);
    }
    Ok(())
}

/// A logical Result record, NOT ownership of the Arc allocation/control block.
/// The selected Packet holds this as its final field through original result
/// consumption/Drop. Arc bytes retain their original Wasm-linear charge through
/// actual allocator deallocation (or failed activation's real Store teardown).
pub(crate) struct PacketResult(Owner);
impl PacketResult {
    pub(crate) fn admit() -> io::Result<Self> {
        ensure_runtime()?;
        Owner::admit(Kind::Result, Some(current_task()))
            .map(Self)
            .map_err(io_error)
    }
}

pub(crate) fn system_allocate<T>(value: T) -> *mut T {
    SystemOwned::try_new(value, Some(current_task()))
        .unwrap_or_else(|error| panic!("std infrastructure allocation refused: {:?}", error))
        .into_raw()
        .as_ptr()
}
pub(crate) unsafe fn system_deallocate<T>(pointer: *mut T) {
    drop(unsafe { SystemOwned::from_raw(NonNull::new(pointer).expect("live System backing")) });
}

struct Preparing {
    handle: Handle,
    task: Option<Owner>,
    context: Option<NonNull<u8>>,
    bootstrap: Option<NonNull<start::Bootstrap>>,
    started: bool,
    published: bool,
}
impl Drop for Preparing {
    fn drop(&mut self) {
        if self.published || self.started {
            return;
        }
        reg(|r| r.rollback(self.handle)).expect("unstarted std slot rollback");
        if let Some(pointer) = self.bootstrap.take() {
            drop(unsafe { SystemOwned::from_raw(pointer) });
        }
        if let Some(pointer) = self.context.take() {
            unsafe {
                tls::discard_unstarted_context(pointer.as_ptr());
            }
        }
        drop(self.task.take());
    }
}

pub(crate) unsafe fn spawn(stack: usize, init: Box<ThreadInit>) -> io::Result<Handle> {
    ensure_runtime()?;
    let parent = current_index();
    let task = current_task();
    let handle = reg(|r| r.reserve()).map_err(|_| io::Error::from(io::ErrorKind::WouldBlock))?;
    let mut preparing = Preparing {
        handle,
        task: None,
        context: None,
        bootstrap: None,
        started: false,
        published: false,
    };
    preparing.task = Some(Owner::admit(Kind::Task, Some(task)).map_err(io_error)?);
    let token = preparing.task.as_ref().unwrap().token();
    let context = tls::try_prepare_stacked_thread_context(
        tls::Token {
            generation: token.generation,
            id: token.id,
        },
        stack.max(64 * 1024),
    )
    .map_err(|error| match error {
        tls::ContextError::Admission(error) => io_error(owner::error(error)),
        tls::ContextError::Allocation => io::Error::from(io::ErrorKind::OutOfMemory),
        tls::ContextError::Layout => io::Error::from(io::ErrorKind::InvalidInput),
    })?;
    preparing.context = NonNull::new(context);
    preparing.bootstrap = Some(
        start::Bootstrap::prepare(init, token)
            .map_err(allocation_error)?
            .into_raw(),
    );
    let canonical = unsafe {
        thread_new(
            super::__lsf_rust_owned_thread_entry as *const () as usize as u32,
            context,
        )
    };
    // The compiler's selected fallible wrapper returns before raw creation on
    // refusal. The old trapping Rust wrapper is never accepted for this path.
    unsafe { tls::creation_result(context) }.map_err(|error| io_error(owner::error(error)))?;
    preparing.started = true;
    assert_ne!(
        canonical, parent,
        "canonical creation returned current thread"
    );
    reg(|r| r.admitted(handle, token, context.addr(), canonical))
        .expect("canonical std identity publication");
    let child = Child {
        task: preparing.task.take().unwrap(),
        context: preparing.context.take().unwrap(),
        bootstrap: preparing.bootstrap.take(),
        parent,
        executor: None,
    };
    children(|c| {
        assert!(c[handle.slot()].replace(child).is_none());
    });
    preparing.published = true;
    // Only this exact newly created target and the known Ready caller take
    // the explicit promotion route. Child entry runs no ThreadInit/user code.
    assert_eq!(
        unsafe { yield_then_promote(canonical) },
        0,
        "std creation handshake cancelled"
    );
    assert_eq!(current_index(), parent);
    // entered() has explicitly suspended this child after identity handshake.
    // Queueing it is nonsuspending; user work cannot execute on the creator.
    unsafe {
        resume_later(canonical);
    }
    Ok(handle)
}

pub(crate) unsafe fn entered(context: *mut u8) {
    assert_eq!(
        tls::installed_context(),
        context,
        "entry context not installed before Rust prologue"
    );
    let canonical = current_index();
    let handle =
        reg(|r| r.entered(canonical, context.addr())).expect("separate std child identity");
    let parent = children(|c| c[handle.slot()].as_ref().unwrap().parent);
    assert_eq!(
        unsafe { suspend_then_promote(parent) },
        0,
        "std child handshake cancelled"
    );
    reg(|r| r.start(handle, canonical)).expect("std child started without creator handshake");
    let bootstrap = children(|c| c[handle.slot()].as_mut().unwrap().bootstrap.take().unwrap());
    unsafe {
        start::run(bootstrap);
    }
    unsafe {
        tls::finish_stacked_thread_tls().expect("std child TLS cleanup did not complete");
    }
    reg(|r| r.tls_drained(handle, canonical)).expect("std child closure/TLS exit state");
    // Copy the callback target without retaining a Child/Runtime reference
    // over even this closed lifecycle notification.
    let executor = children(|c| {
        c[handle.slot()]
            .as_ref()
            .unwrap()
            .executor
            .as_ref()
            .map(|lease| lease.tls_notification())
    });
    if let Some((pointer, canonical, callback)) = executor {
        unsafe {
            callback(pointer, canonical);
        }
    }
    // Both queues are private UNTImed queues: these paths contain only bounded
    // state changes and canonical resume-later, never host await/user work.
    // The fixed compiler verifier must prove the remaining return/epilogue
    // path before phase5/detach. No Task or stack is released on this child.
    join_queue(handle).notify_all();
    completed_queue().notify_all();
}

fn reap(handle: Handle) -> bool {
    if reg(|r| r.is_reaped(handle)).expect("live std reap identity") {
        return true;
    }
    if !reg(|r| r.tls_finished(handle)).expect("live std TLS identity") {
        return false;
    }
    let context = children(|c| c[handle.slot()].as_ref().unwrap().context);
    if !unsafe { tls::frames_exited(context.as_ptr()) } {
        return false;
    }
    reg(|r| r.claim_reap(handle)).expect("one affine std reaper");
    let mut child = children(|c| c[handle.slot()].take().unwrap());
    assert!(child.bootstrap.is_none(), "unconsumed original ThreadInit");
    unsafe {
        tls::retire_exited_thread_context(context.as_ptr()).expect("std linear context still live");
    }
    if let Some(executor) = child.executor.take() {
        unsafe {
            executor.after_frames();
        }
    }
    drop(child); // Task after actual stack/context free; host stack remains owned.
    reg(|r| r.reaped(handle)).expect("std canonical/frame retirement state");
    join_queue(handle).notify_all();
    completed_queue().notify_all();
    if reg(|r| r.is_detached(handle)).unwrap() {
        reg(|r| r.retire_detached(handle)).expect("detached std tombstone retirement");
    }
    true
}
pub(crate) fn join(handle: Handle) {
    let caller = current_index();
    reg(|r| r.claim_join(handle, caller)).expect("invalid, self, duplicate or cyclic std join");
    loop {
        if reap(handle) {
            break;
        }
        let wait = join_queue(handle).prepare(None);
        if reap(handle) {
            wait.cancel();
            break;
        }
        assert!(wait.wait(), "untimed std join reported timer completion");
    }
    reg(|r| r.complete_join(handle, caller)).expect("std join before physical frame retirement");
}
pub(crate) fn detach(handle: Handle) {
    reg(|r| r.detach(handle)).expect("invalid std detach");
    if reg(|r| r.is_reaped(handle)).unwrap() {
        reg(|r| r.retire_detached(handle)).expect("std detached completed identity");
    }
}
pub(crate) fn yield_eligible() {
    if existing().is_null() {
        return;
    } // No std child exists; no bootstrap allocation.
    assert_eq!(unsafe { thread_yield() }, 0, "std yield cancelled");
}
fn reap_all() -> bool {
    let handles = reg(|r| r.handles());
    for handle in handles.into_iter().flatten() {
        // Settlement may yield and another legitimate joiner may remove a
        // completed tombstone from this copied snapshot. No stale pointer is
        // retained or used. Current live records are checked again below.
        if reg(|r| r.is_reaped(handle)) == Err(registry::Error::Stale) {
            continue;
        }
        reap(handle);
    }
    // New accepted child work may have appeared during actual free/settlement.
    // Completion is never inferred from the earlier snapshot or an empty queue.
    reg(|r| {
        r.handles()
            .into_iter()
            .flatten()
            .all(|h| r.is_reaped(h) == Ok(true))
    })
}
unsafe fn drain(pointer: *mut u8) -> bool {
    assert_eq!(pointer.cast::<Runtime>(), existing());
    assert_eq!(current_index(), unsafe { (*existing()).root });
    loop {
        let executors_ready = unsafe { executor_root::progress_all() };
        if reap_all() && executors_ready.is_some_and(executor_root::unchanged) {
            return true;
        }
        let wait = completed_queue().prepare(None);
        let executors_ready = unsafe { executor_root::progress_all() };
        if reap_all() && executors_ready.is_some_and(executor_root::unchanged) {
            wait.cancel();
            return true;
        }
        assert!(wait.wait(), "untimed std root drain reported elapsed timer");
    }
}
unsafe fn release(pointer: *mut u8) {
    assert_eq!(pointer.cast::<Runtime>(), existing());
    reg(|r| r.close_after_root_frames()).expect("root ended with live std child frames");
    children(|c| assert!(c.iter().all(Option::is_none)));
    assert!(
        unsafe { &*(*existing()).executors.get() }.is_empty(),
        "root ended with live selected executor handles or wake registrations"
    );
    assert!(
        wait_driver::quiescent(),
        "root ended with live std wait frames"
    );
    unsafe {
        *RUNTIME.0.get() = ptr::null_mut();
    }
    drop(unsafe { SystemOwned::from_raw(NonNull::new(pointer.cast::<Runtime>()).unwrap()) });
}

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "$root"))]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-index]")]
    fn thread_index() -> u32;
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-new-indirect-v0]")]
    fn thread_new(entry: u32, context: *mut u8) -> u32;
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-yield-then-promote]")]
    fn yield_then_promote(index: u32) -> u32;
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-suspend-then-promote]")]
    fn suspend_then_promote(index: u32) -> u32;
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-resume-later]")]
    fn resume_later(index: u32);
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-yield]")]
    fn thread_yield() -> u32;
}

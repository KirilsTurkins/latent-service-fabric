//! Actual selected worker-lease/registry source with explicit pool/canonical ports.
//! No canonical thread, sysroot, future poll or final component is executed.
use std::cell::{Cell, RefCell};
use std::ptr::NonNull;
use std::sync::Arc;
pub use std::{array, io, ptr};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Token {
    generation: u64,
    id: u64,
}
impl Token {
    fn valid(self) -> bool {
        self.generation != 0 && self.id != 0
    }
}
#[path = "../thread_registry.rs"]
mod registry;
#[path = "../executor_worker.rs"]
mod worker;
mod executor_root {
    use super::*;
    #[derive(Clone, Copy)]
    pub(crate) struct Handle(pub(crate) u64);
    pub(crate) fn owns(handle: Handle, pointer: NonNull<()>) -> bool {
        POOL.with(|p| p.get() == Some((handle.0, pointer.as_ptr() as usize)))
    }
}
mod tls {
    pub(crate) fn installed_context() -> *mut u8 {
        super::CONTEXT.get() as *mut u8
    }
}
struct Child {
    executor: Option<worker::Lease>,
}
thread_local! {
    static CURRENT:Cell<u32>=Cell::new(0);
    static CONTEXT:Cell<usize>=Cell::new(0x1000);
    static POOL:Cell<Option<(u64,usize)>>=Cell::new(None);
    static REGISTRY:RefCell<registry::Registry>=RefCell::new(registry::Registry::new(0));
    static CHILDREN:RefCell<[Option<Child>;registry::MAX_THREADS]>=RefCell::new(array::from_fn(|_|None));
}
fn existing() -> *mut () {
    std::ptr::NonNull::<()>::dangling().as_ptr()
}
fn current_index() -> u32 {
    CURRENT.get()
}
fn reg<R>(f: impl FnOnce(&mut registry::Registry) -> R) -> R {
    REGISTRY.with(|r| f(&mut r.borrow_mut()))
}
fn children<R>(f: impl FnOnce(&mut [Option<Child>; registry::MAX_THREADS]) -> R) -> R {
    CHILDREN.with(|c| f(&mut c.borrow_mut()))
}
struct Pool {
    phase: [Cell<u8>; 3],
    released: Cell<usize>,
}
fn pool() -> (Arc<Pool>, NonNull<()>) {
    let pool = Arc::new(Pool {
        phase: array::from_fn(|_| Cell::new(0)),
        released: Cell::new(0),
    });
    let pointer = NonNull::new(Arc::into_raw(pool.clone()).cast_mut().cast()).unwrap();
    POOL.set(Some((1, pointer.as_ptr() as usize)));
    (pool, pointer)
}
unsafe fn tls_done(pointer: NonNull<()>, canonical: u32) {
    let pool = unsafe { &*pointer.cast::<Pool>().as_ptr() };
    assert_eq!(current_index(), canonical);
    assert_eq!(pool.phase[canonical as usize].replace(1), 0);
}
unsafe fn frames_done(pointer: NonNull<()>, canonical: u32) {
    let pool = unsafe { &*pointer.cast::<Pool>().as_ptr() };
    assert_eq!(current_index(), 0);
    assert_eq!(pool.phase[canonical as usize].replace(2), 1);
}
unsafe fn release(pointer: NonNull<()>) {
    assert_eq!(
        current_index(),
        0,
        "release must run on the actual reaper frame"
    );
    let pool = unsafe { Arc::from_raw(pointer.cast::<Pool>().as_ptr()) };
    assert!(pool.phase.iter().any(|value| value.get() == 2));
    pool.released.set(pool.released.get() + 1);
    drop(pool);
}
fn callbacks() -> worker::Callbacks {
    worker::Callbacks {
        tls_drained: tls_done,
        frames_exited: frames_done,
        release,
    }
}
fn ready(canonical: u32, context: usize) -> registry::Handle {
    let handle = reg(|r| r.reserve().unwrap());
    reg(|r| {
        r.admitted(
            handle,
            Token {
                generation: 1,
                id: u64::from(canonical),
            },
            context,
            canonical,
        )
        .unwrap()
    });
    children(|c| c[handle.slot()] = Some(Child { executor: None }));
    handle
}
fn started(handle: registry::Handle, canonical: u32, context: usize) {
    reg(|r| {
        r.entered(canonical, context).unwrap();
        r.start(handle, canonical).unwrap();
    });
    CURRENT.set(canonical);
    CONTEXT.set(context);
}
fn reset() {
    CURRENT.set(0);
    CONTEXT.set(0x1000);
    POOL.set(None);
    CHILDREN.with(|c| {
        assert!(c
            .borrow()
            .iter()
            .all(|row| row.as_ref().is_none_or(|r| r.executor.is_none())))
    });
    CHILDREN.with(|c| *c.borrow_mut() = array::from_fn(|_| None));
    REGISTRY.with(|r| *r.borrow_mut() = registry::Registry::new(0));
}
#[test]
fn worker_lease_refuses_root_ready_foreign_context_stale_executor_and_duplicate_transfer() {
    reset();
    let (pool, pointer) = pool();
    let owner = executor_root::Handle(1);
    assert!(unsafe { worker::register(owner, pointer, callbacks()) }.is_err());
    let handle = ready(1, 0x1000);
    CURRENT.set(1);
    assert!(
        unsafe { worker::register(owner, pointer, callbacks()) }.is_err(),
        "Ready is not running"
    );
    started(handle, 1, 0x1000);
    CONTEXT.set(0x2000);
    assert!(unsafe { worker::register(owner, pointer, callbacks()) }.is_err());
    CONTEXT.set(0x1000);
    assert!(unsafe { worker::register(executor_root::Handle(2), pointer, callbacks()) }.is_err());
    assert_eq!(
        Arc::strong_count(&pool),
        2,
        "every refusal retains the caller reference"
    );
    unsafe {
        worker::register(owner, pointer, callbacks()).unwrap();
    }
    let duplicate = NonNull::new(Arc::into_raw(pool.clone()).cast_mut().cast()).unwrap();
    assert_eq!(
        unsafe { worker::register(owner, duplicate, callbacks()) }
            .unwrap_err()
            .kind(),
        io::ErrorKind::AlreadyExists
    );
    drop(unsafe { Arc::from_raw(duplicate.cast::<Pool>().as_ptr()) });
    let lease = children(|c| c[handle.slot()].as_mut().unwrap().executor.take().unwrap());
    let (p, canonical, notify) = lease.tls_notification();
    unsafe {
        notify(p, canonical);
        CURRENT.set(0);
        lease.after_frames();
    }
    assert_eq!(pool.released.get(), 1);
    assert_eq!(Arc::strong_count(&pool), 1);
    reset();
}
#[test]
fn worker_lease_retains_actual_arc_until_separate_tls_and_frame_notifications() {
    reset();
    let (pool, pointer) = pool();
    let handle = ready(1, 0x1000);
    started(handle, 1, 0x1000);
    unsafe {
        worker::register(executor_root::Handle(1), pointer, callbacks()).unwrap();
    }
    let notification = children(|c| {
        c[handle.slot()]
            .as_ref()
            .unwrap()
            .executor
            .as_ref()
            .unwrap()
            .tls_notification()
    });
    assert_eq!(pool.phase[1].get(), 0);
    assert_eq!(Arc::strong_count(&pool), 2);
    reg(|r| r.tls_drained(handle, 1).unwrap());
    let late = NonNull::new(Arc::into_raw(pool.clone()).cast_mut().cast()).unwrap();
    assert_eq!(
        unsafe { worker::register(executor_root::Handle(1), late, callbacks()) }
            .unwrap_err()
            .kind(),
        io::ErrorKind::InvalidInput,
        "ended TLS frame cannot accept a new worker lease"
    );
    drop(unsafe { Arc::from_raw(late.cast::<Pool>().as_ptr()) });
    unsafe {
        notification.2(notification.0, notification.1);
    }
    assert_eq!(pool.phase[1].get(), 1);
    assert_eq!(pool.released.get(), 0);
    assert_eq!(Arc::strong_count(&pool), 2);
    let lease = children(|c| c[handle.slot()].as_mut().unwrap().executor.take().unwrap());
    CURRENT.set(0);
    unsafe {
        lease.after_frames();
    }
    assert_eq!(pool.phase[1].get(), 2);
    assert_eq!(pool.released.get(), 1);
    assert_eq!(Arc::strong_count(&pool), 1);
    reset();
}

#[test]
fn worker_lease_frame_callback_keeps_each_real_child_identity_after_return_to_root() {
    reset();
    let (pool, first_pointer) = pool();
    let first = ready(1, 0x1000);
    started(first, 1, 0x1000);
    unsafe {
        worker::register(executor_root::Handle(1), first_pointer, callbacks()).unwrap();
    }
    let second_pointer = NonNull::new(Arc::into_raw(pool.clone()).cast_mut().cast()).unwrap();
    let second = ready(2, 0x2000);
    started(second, 2, 0x2000);
    unsafe {
        worker::register(executor_root::Handle(1), second_pointer, callbacks()).unwrap();
    }
    assert_eq!(Arc::strong_count(&pool), 3);
    for (handle, canonical) in [(second, 2), (first, 1)] {
        CURRENT.set(canonical);
        reg(|r| r.tls_drained(handle, canonical).unwrap());
        let lease = children(|c| c[handle.slot()].as_mut().unwrap().executor.take().unwrap());
        let (pointer, saved, notify) = lease.tls_notification();
        assert_eq!(saved, canonical);
        unsafe {
            notify(pointer, saved);
        }
        CURRENT.set(0);
        unsafe {
            lease.after_frames();
        }
        assert_eq!(pool.phase[canonical as usize].get(), 2);
    }
    assert_eq!(pool.released.get(), 2);
    assert_eq!(Arc::strong_count(&pool), 1);
    reset();
}

//! Actual pool control/lifecycle with explicit bounded owner and wait ports.
//! This does not execute a real engine, selected sysroot or signed guest.
use std::cell::{Cell, RefCell};
use std::collections::BTreeSet;
pub use std::ptr;
use std::ptr::NonNull;
use std::sync::Arc;
use std::time::Duration;
pub use std::{array, cell, io};

mod owner {
    use super::*;
    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    pub(crate) struct Token {
        pub(crate) generation: u64,
        pub(crate) id: u64,
    }
    impl Token {
        pub(crate) fn valid(self) -> bool {
            self.generation != 0 && self.id != 0
        }
    }
    #[derive(Clone, Copy)]
    pub(crate) enum Kind {
        Task,
        QueuedWork,
    }
    pub(crate) struct Owner(Token);
    thread_local! {
        static NEXT: Cell<u64> = const { Cell::new(0) };
        static LIVE: RefCell<BTreeSet<u64>> = RefCell::new(BTreeSet::new());
        static DROPS: Cell<usize> = const { Cell::new(0) };
    }
    impl Owner {
        pub(crate) fn admit(_kind: Kind, _parent: Option<Token>) -> Result<Self, ()> {
            let id = NEXT.with(|n| {
                let id = n.get() + 1;
                n.set(id);
                id
            });
            LIVE.with(|live| assert!(live.borrow_mut().insert(id)));
            Ok(Self(Token { generation: 1, id }))
        }
        pub(crate) fn token(&self) -> Token {
            self.0
        }
    }
    impl Drop for Owner {
        fn drop(&mut self) {
            LIVE.with(|live| assert!(live.borrow_mut().remove(&self.0.id)));
            DROPS.with(|drops| drops.set(drops.get() + 1));
        }
    }
    pub(crate) fn live() -> usize {
        LIVE.with(|v| v.borrow().len())
    }
    pub(crate) fn drops() -> usize {
        DROPS.with(Cell::get)
    }
}
use owner::Token;
fn io_error(_: ()) -> io::Error {
    io::Error::from(io::ErrorKind::WouldBlock)
}
struct WaitQueue;
struct Wait;
impl WaitQueue {
    const fn new() -> Self {
        Self
    }
    fn prepare(&self, _: Option<Duration>) -> Wait {
        panic!("unexpected provisioning wait")
    }
    fn notify_all(&self) {}
}
impl Wait {
    fn wait(self) -> bool {
        true
    }
    fn cancel(self) {}
}
#[path = "../executor_bridge.rs"]
mod executor_bridge;
#[path = "../executor_control.rs"]
mod executor_control;
#[path = "../executor_lifecycle.rs"]
mod executor_lifecycle;
#[path = "../executor_worker.rs"]
mod executor_worker;
#[path = "../thread_registry.rs"]
mod thread_registry;
struct Child {
    executor: Option<executor_worker::Lease>,
}
struct Pool {
    released: Cell<usize>,
}
thread_local! {
    static INDEX: Cell<u32> = const { Cell::new(0) };
    static CONTEXT: Cell<usize> = const { Cell::new(0) };
    static THREADS: RefCell<thread_registry::Registry> = RefCell::new(thread_registry::Registry::new(0));
    static CHILDREN: RefCell<[Option<Child>; thread_registry::MAX_THREADS]> = RefCell::new(array::from_fn(|_| None));
}
fn current_index() -> u32 {
    INDEX.with(Cell::get)
}
fn existing() -> *mut () {
    NonNull::<()>::dangling().as_ptr()
}
fn reg<R>(f: impl FnOnce(&mut thread_registry::Registry) -> R) -> R {
    THREADS.with(|r| f(&mut r.borrow_mut()))
}
fn children<R>(f: impl FnOnce(&mut [Option<Child>; thread_registry::MAX_THREADS]) -> R) -> R {
    CHILDREN.with(|c| f(&mut c.borrow_mut()))
}
mod tls {
    pub(crate) fn installed_context() -> *mut u8 {
        super::CONTEXT.with(|c| c.get() as *mut u8)
    }
}
mod executor_root {
    use super::*;
    #[derive(Clone, Copy)]
    pub(crate) struct Handle(u64);
    #[derive(Clone, Copy)]
    pub(crate) struct CapturedCallbacks {
        pub progress: unsafe extern "C" fn(*mut ()) -> u32,
        pub release: unsafe extern "C" fn(*mut ()),
    }
    pub(crate) struct Binding {
        pub handle: Handle,
        pub pointer: NonNull<()>,
        pub parent: Token,
        pub control: NonNull<Control>,
    }
    thread_local! { static CONTROL: Cell<*mut Control> = const { Cell::new(ptr::null_mut()) }; static POOL: Cell<*mut ()> = const { Cell::new(ptr::null_mut()) }; }
    pub(crate) fn install(control: &Control, pool: *mut ()) {
        CONTROL.with(|c| c.set(ptr::from_ref(control).cast_mut()));
        POOL.with(|p| p.set(pool));
    }
    pub(crate) fn prepare() -> io::Result<u64> {
        Err(io::ErrorKind::Unsupported.into())
    }
    pub(crate) unsafe fn commit_prepared(_: u64, _: NonNull<()>, _: CapturedCallbacks) {
        panic!("unexpected setup")
    }
    pub(crate) fn abort_prepared(_: u64) {
        panic!("unexpected abort")
    }
    pub(crate) fn changed() {}
    pub(crate) fn owns(handle: Handle, pointer: NonNull<()>) -> bool {
        handle.0 == 1 && POOL.with(|p| p.get() == pointer.as_ptr())
    }
    pub(crate) fn control(key: u64) -> io::Result<Binding> {
        if key != 1 {
            return Err(io::ErrorKind::InvalidInput.into());
        }
        let control = CONTROL
            .with(|c| NonNull::new(c.get()))
            .ok_or(io::ErrorKind::InvalidInput)?;
        let pointer = POOL
            .with(|p| NonNull::new(p.get()))
            .ok_or(io::ErrorKind::InvalidInput)?;
        Ok(Binding {
            handle: Handle(1),
            pointer,
            control,
            parent: Token {
                generation: 1,
                id: 999,
            },
        })
    }
    pub(crate) unsafe fn worker_tls_drained(pointer: NonNull<()>, worker: u64) {
        assert!(owns(Handle(1), pointer));
        unsafe { control(1).unwrap().control.as_ref() }
            .worker_tls_drained(worker)
            .unwrap();
    }
    pub(crate) unsafe fn worker_frames_exited(pointer: NonNull<()>, worker: u64) {
        assert!(owns(Handle(1), pointer));
        unsafe { control(1).unwrap().control.as_ref() }
            .worker_frames_exited(worker)
            .unwrap();
    }
    pub(crate) unsafe fn worker_release(pointer: NonNull<()>) {
        let pool = unsafe { Arc::from_raw(pointer.cast::<Pool>().as_ptr()) };
        pool.released.set(pool.released.get() + 1);
    }
}

use executor_control::{Control, Drain};

#[test]
fn old_and_new_worker_callbacks_are_keyed_to_their_own_generations() {
    let pool = Control::new();
    let parent = Token {
        generation: 1,
        id: 999,
    };
    let old_gen = pool.begin_generation(1).unwrap().unwrap();
    let old = pool.reserve_worker(old_gen, parent).unwrap();
    pool.check_worker_start(old, 7).unwrap();
    pool.worker_started(old, 7).unwrap();
    pool.commit_generation(old_gen).unwrap();
    assert!(
        matches!(pool.drain().unwrap(), Drain::Close { generation, messages: 1 } if generation == old_gen)
    );
    let next_gen = pool.begin_generation(1).unwrap().unwrap();
    let next = pool.reserve_worker(next_gen, parent).unwrap();
    assert_ne!(old, next);
    assert!(pool.check_worker_start(next, 7).is_err());
    assert!(pool.claim_close(old, old_gen).unwrap());
    assert!(pool.check_worker_start(next, 7).is_err());
    assert!(
        pool.worker_frames_exited(old).is_err(),
        "TLS must drain before frames exit"
    );
    pool.worker_tls_drained(old).unwrap();
    // The port supplies the separately validated new PAL child/index.
    pool.check_worker_start(next, 7).unwrap();
    pool.worker_started(next, 7).unwrap();
    pool.commit_generation(next_gen).unwrap();
    assert_eq!(owner::live(), 1);
    pool.worker_frames_exited(old).unwrap();
    assert!(
        pool.worker_frames_exited(old).is_err(),
        "stale callback must not retire the successor"
    );
    assert!(
        matches!(pool.drain().unwrap(), Drain::Close { generation, messages: 1 } if generation == next_gen)
    );
    assert!(pool.claim_close(next, next_gen).unwrap());
    pool.worker_tls_drained(next).unwrap();
    pool.worker_frames_exited(next).unwrap();
    pool.retire().unwrap();
    assert_eq!(owner::live(), 0);
    assert_eq!(owner::drops(), 2);
}

#[repr(C)]
struct Wire {
    status: u32,
    kind: u32,
    key: u64,
    count: u32,
}
fn request(operation: u32, a: u64, b: u64, pointer: *mut ()) -> Wire {
    let mut value = std::mem::MaybeUninit::<Wire>::uninit();
    unsafe {
        executor_bridge::__lsf_rust_pool_request(
            operation,
            1,
            a,
            b,
            pointer,
            value.as_mut_ptr().cast::<executor_bridge::Reply>(),
        );
        value.assume_init()
    }
}
fn running(token: Token, index: u32, context: usize) -> thread_registry::Handle {
    let handle = reg(|r| {
        let h = r.reserve().unwrap();
        r.admitted(h, token, context, index).unwrap();
        r.entered(index, context).unwrap();
        r.start(h, index).unwrap();
        h
    });
    children(|c| c[handle.slot()] = Some(Child { executor: None }));
    INDEX.with(|i| i.set(index));
    CONTEXT.with(|c| c.set(context));
    handle
}
#[test]
fn actual_bridge_carries_worker_keys_through_recycled_canonical_index_and_arc_release() {
    let control = Control::new();
    let pool = Arc::new(Pool {
        released: Cell::new(0),
    });
    let pool_pointer = Arc::as_ptr(&pool).cast_mut().cast::<()>();
    executor_root::install(&control, pool_pointer);
    let old_gen = request(0, 1, 0, ptr::null_mut()).key;
    let old_key = request(1, old_gen, 0, ptr::null_mut()).key;
    let old = running(
        Token {
            generation: 1,
            id: 101,
        },
        1,
        0x1000,
    );
    let old_arc = Arc::into_raw(pool.clone()).cast_mut().cast::<()>();
    assert_eq!(request(2, old_key, 0, old_arc).status, 0);
    assert_eq!(request(3, old_gen, 0, ptr::null_mut()).status, 0);
    assert_eq!(request(12, 0, 0, ptr::null_mut()).kind, 1);
    assert_eq!(request(11, old_key, old_gen, ptr::null_mut()).count, 1);
    reg(|r| r.tls_drained(old, 1)).unwrap();
    let notice = children(|c| {
        c[old.slot()]
            .as_ref()
            .unwrap()
            .executor
            .as_ref()
            .unwrap()
            .tls_notification()
    });
    assert_eq!(notice.1, old_key);
    unsafe {
        notice.2(notice.0, notice.1);
    }
    reg(|r| r.clear_exited_canonical(old, 1, true)).unwrap();
    let next_gen = request(0, 1, 0, ptr::null_mut()).key;
    let next_key = request(1, next_gen, 0, ptr::null_mut()).key;
    assert_ne!(old_key, next_key);
    let next = running(
        Token {
            generation: 1,
            id: 102,
        },
        1,
        0x2000,
    );
    let next_arc = Arc::into_raw(pool.clone()).cast_mut().cast::<()>();
    assert_eq!(request(2, next_key, 0, next_arc).status, 0);
    assert_eq!(request(3, next_gen, 0, ptr::null_mut()).status, 0);
    assert_eq!(Arc::strong_count(&pool), 3);
    let old_lease = children(|c| c[old.slot()].as_mut().unwrap().executor.take().unwrap());
    INDEX.with(|i| i.set(0));
    unsafe {
        old_lease.after_frames();
    }
    assert_eq!(pool.released.get(), 1);
    assert_eq!(Arc::strong_count(&pool), 2);
    assert!(control.worker_frames_exited(old_key).is_err());
    let close = request(12, 0, 0, ptr::null_mut());
    assert_eq!((close.kind, close.key, close.count), (1, next_gen, 1));
    assert_eq!(request(11, next_key, next_gen, ptr::null_mut()).count, 1);
    INDEX.with(|i| i.set(1));
    CONTEXT.with(|c| c.set(0x2000));
    reg(|r| r.tls_drained(next, 1)).unwrap();
    let next_lease = children(|c| c[next.slot()].as_mut().unwrap().executor.take().unwrap());
    let notice = next_lease.tls_notification();
    assert_eq!(notice.1, next_key);
    unsafe {
        notice.2(notice.0, notice.1);
    }
    INDEX.with(|i| i.set(0));
    unsafe {
        next_lease.after_frames();
    }
    assert_eq!(pool.released.get(), 2);
    assert_eq!(Arc::strong_count(&pool), 1);
    assert_eq!(request(13, 0, 0, ptr::null_mut()).status, 0);
    assert_eq!(owner::live(), 0);
}

#[test]
fn three_reused_generations_retire_only_their_exact_worker_keys() {
    let pool = Control::new();
    let parent = Token {
        generation: 1,
        id: 999,
    };
    let mut workers = Vec::new();
    for _ in 0..3 {
        let generation = pool.begin_generation(1).unwrap().unwrap();
        let worker = pool.reserve_worker(generation, parent).unwrap();
        pool.check_worker_start(worker, 7).unwrap();
        pool.worker_started(worker, 7).unwrap();
        pool.commit_generation(generation).unwrap();
        assert!(
            matches!(pool.drain().unwrap(), Drain::Close { generation: id, messages: 1 } if id == generation)
        );
        assert!(pool.claim_close(worker, generation).unwrap());
        pool.worker_tls_drained(worker).unwrap();
        workers.push(worker);
    }
    assert_ne!(workers[0], workers[1]);
    assert_ne!(workers[1], workers[2]);
    pool.worker_frames_exited(workers[1]).unwrap();
    assert!(pool.worker_frames_exited(workers[1]).is_err());
    pool.worker_frames_exited(workers[0]).unwrap();
    assert!(
        pool.retire().is_err(),
        "the third worker still owns its frame"
    );
    pool.worker_frames_exited(workers[2]).unwrap();
    pool.retire().unwrap();
    assert_eq!(owner::live(), 0);
    assert_eq!(owner::drops(), 3);
}

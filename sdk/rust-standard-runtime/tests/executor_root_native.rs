//! Actual executor-root registry and affine owner source, with explicit host,
//! completion-notification and pool callbacks. No canonical thread, selected
//! sysroot, guest execution or physical Wasmtime retirement is proved here.
#![allow(dead_code)]
use std::cell::{Cell, RefCell, UnsafeCell};
use std::collections::BTreeMap;
use std::ptr::NonNull;
use std::rc::Rc;
use std::sync::Arc;
pub use std::{array, io, mem, ptr};
pub mod alloc {
    pub use std::alloc::{GlobalAlloc, Layout, System};
}
#[path = "../runtime_owner.rs"]
mod owner;
#[path = "../executor_root.rs"]
mod root;
use owner::{AllocationError, Error, Kind, Token};
use root::Progress;

// Only the physical Control backing boundary is exercised in this harness.
// Worker/TLS semantics have their separate actual-source controls; these
// methods must not substitute for them or manufacture a worker transition.
mod executor_control {
    pub(crate) struct Control(u8);
    impl Control {
        pub(crate) fn new() -> Self {
            Self(0)
        }
        pub(crate) fn worker_tls_drained(&self, _: u32) -> Result<(), ()> {
            panic!("worker TLS is outside the root notification control")
        }
        pub(crate) fn worker_frames_exited(&self, _: u32) -> Result<(), ()> {
            panic!("worker frames are outside the root notification control")
        }
    }
    impl Drop for Control {
        fn drop(&mut self) {
            super::event("drop-control");
        }
    }
}

#[derive(Default)]
struct Completion {
    prepared: Cell<bool>,
    notified: Cell<bool>,
}
impl Completion {
    fn prepare(&self) {
        assert!(!self.prepared.replace(true));
        self.notified.set(false);
    }
    fn notify_all(&self) {
        event("notify-completion");
        if self.prepared.get() {
            self.notified.set(true);
        }
    }
    fn take_notification(&self) -> bool {
        assert!(self.prepared.replace(false));
        self.notified.replace(false)
    }
}
struct Runtime {
    executors: UnsafeCell<root::Registry>,
    completed: Completion,
}
#[derive(Default)]
struct Host {
    next: u64,
    owners: BTreeMap<u64, (u32, u64)>,
    events: Vec<&'static str>,
}
std::thread_local! {
    static RUNTIME: Cell<*mut Runtime> = Cell::new(ptr::null_mut());
    static HOST: RefCell<Host> = RefCell::new(Host::default());
}
const ROOT: Token = Token { generation: 41, id: 99 };
fn current_task() -> Token {
    ROOT
}
fn existing() -> *mut Runtime {
    RUNTIME.get()
}
fn ensure_runtime() -> io::Result<()> {
    assert!(!existing().is_null(), "control requires an installed runtime");
    Ok(())
}
fn completed_queue() -> &'static Completion {
    unsafe { &*ptr::addr_of!((*existing()).completed) }
}
fn io_error(error: Error) -> io::Error {
    io::Error::other(format!("control owner admission: {error:?}"))
}
fn allocation_error(error: AllocationError) -> io::Error {
    io::Error::other(format!("control allocation: {error:?}"))
}
fn event(value: &'static str) {
    HOST.with(|host| host.borrow_mut().events.push(value));
}
fn clear_events() {
    HOST.with(|host| host.borrow_mut().events.clear());
}
fn events() -> Vec<&'static str> {
    HOST.with(|host| host.borrow().events.clone())
}
fn owners() -> usize {
    HOST.with(|host| host.borrow().owners.len())
}
struct Installed(Box<Runtime>);
impl Installed {
    fn new() -> Self {
        assert!(existing().is_null());
        HOST.with(|host| {
            assert!(host.borrow().owners.is_empty());
            *host.borrow_mut() = Host { next: ROOT.id, ..Host::default() };
        });
        let mut runtime = Box::new(Runtime {
            executors: UnsafeCell::new(root::Registry::new()),
            completed: Completion::default(),
        });
        RUNTIME.set(ptr::from_mut(runtime.as_mut()));
        Self(runtime)
    }
    fn stable_empty(&self) {
        assert!(unsafe { &*self.0.executors.get() }.is_empty());
        assert_eq!(owners(), 0);
        let stamp = unsafe { root::progress_all() }.expect("fresh empty registry scan");
        assert!(root::unchanged(stamp));
    }
}
impl Drop for Installed {
    fn drop(&mut self) {
        assert!(self.0.executors.get_mut().is_empty());
        assert!(!self.0.completed.prepared.get());
        assert_eq!(owners(), 0);
        assert_eq!(RUNTIME.replace(ptr::null_mut()), ptr::from_mut(self.0.as_mut()));
    }
}

#[unsafe(no_mangle)]
unsafe extern "C" fn register(kind: u32, present: u32, generation: u64, parent: u64, out: *mut u8) {
    assert_eq!((present, generation), (1, ROOT.generation));
    let id = HOST.with(|host| {
        let mut host = host.borrow_mut();
        match kind {
            2 => assert_eq!(parent, ROOT.id),
            7 => assert_eq!(host.owners.get(&parent).map(|entry| entry.0), Some(2)),
            _ => panic!("unexpected owner kind in executor-root control"),
        }
        host.next += 1;
        let id = host.next;
        assert!(host.owners.insert(id, (kind, parent)).is_none());
        id
    });
    unsafe {
        out.write(0);
        ptr::copy_nonoverlapping(generation.to_le_bytes().as_ptr(), out.add(8), 8);
        ptr::copy_nonoverlapping(id.to_le_bytes().as_ptr(), out.add(16), 8);
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn settle(generation: u64, id: u64, out: *mut u8) {
    assert_eq!(generation, ROOT.generation);
    let kind = HOST.with(|host| {
        let mut host = host.borrow_mut();
        assert!(!host.owners.values().any(|entry| entry.1 == id));
        host.owners.remove(&id).expect("one live affine owner").0
    });
    event(match kind {
        2 => "settle-executor",
        7 => "settle-native",
        _ => panic!("unexpected settled owner kind"),
    });
    unsafe { out.write(0) };
}
#[unsafe(no_mangle)]
unsafe extern "C" fn park(_: u64, _: u64, _: *mut u8) {
    panic!("root notification control must not park a host task");
}
#[unsafe(no_mangle)]
unsafe extern "C" fn wake(_: u64, _: u64, _: *mut u8) {
    panic!("root notification control must not wake a host task");
}

struct PoolState {
    progress: Cell<Progress>,
    successor: RefCell<Option<Rc<PoolState>>>,
}
fn state(progress: Progress) -> Rc<PoolState> {
    Rc::new(PoolState { progress: Cell::new(progress), successor: RefCell::new(None) })
}
struct Pool(Rc<PoolState>);
impl Drop for Pool {
    fn drop(&mut self) {
        event("drop-pool");
        let successor = self.0.successor.borrow_mut().take();
        if let Some(successor) = successor {
            register_pool(successor);
        }
    }
}
fn pool_pointer(state: Rc<PoolState>) -> NonNull<()> {
    NonNull::new(Arc::into_raw(Arc::new(Pool(state))).cast_mut().cast()).unwrap()
}
unsafe fn progress(pointer: NonNull<()>) -> Progress {
    unsafe { &*pointer.cast::<Pool>().as_ptr() }.0.progress.get()
}
unsafe fn release(pointer: NonNull<()>) {
    let pool = unsafe { Arc::from_raw(pointer.cast::<Pool>().as_ptr()) };
    assert_eq!(Arc::strong_count(&pool), 1, "actual final retained pool Arc");
    assert!(HOST.with(|host| host.borrow().owners.values().any(|row| row.0 == Kind::Executor as u32)));
    drop(pool);
}
fn register_pool(state: Rc<PoolState>) {
    unsafe { root::register(pool_pointer(state), root::Callbacks { progress, release }) }.unwrap();
}
unsafe extern "C" fn captured_progress(pointer: *mut ()) -> u32 {
    match unsafe { progress(NonNull::new(pointer).unwrap()) } {
        Progress::Pending => 0,
        Progress::Quiescent => 1,
        Progress::Releasable => 2,
    }
}
unsafe extern "C" fn captured_release(pointer: *mut ()) {
    unsafe { release(NonNull::new(pointer).unwrap()) };
}

#[test]
fn last_executor_retirement_notifies_the_second_drain_check() {
    let runtime = Installed::new();
    let pool = state(Progress::Pending);
    register_pool(pool.clone());
    assert!(unsafe { root::progress_all() }.is_none());
    completed_queue().prepare();
    pool.progress.set(Progress::Releasable);
    clear_events();
    assert!(unsafe { root::progress_all() }.is_none(), "changed snapshot requires a rescan");
    assert!(completed_queue().take_notification(), "no remaining worker can wake this root");
    assert_eq!(events(), ["drop-pool", "settle-executor", "notify-completion"]);
    runtime.stable_empty();
}

#[test]
fn pending_executor_keeps_its_owner_and_does_not_invent_a_notification() {
    let runtime = Installed::new();
    let pool = state(Progress::Pending);
    register_pool(pool.clone());
    completed_queue().prepare();
    clear_events();
    assert!(unsafe { root::progress_all() }.is_none());
    assert!(!completed_queue().take_notification());
    assert!(events().is_empty());
    assert_eq!(owners(), 1);
    pool.progress.set(Progress::Releasable);
    assert!(unsafe { root::progress_all() }.is_none());
    runtime.stable_empty();
}

#[test]
fn retirement_invalidates_a_previously_quiescent_stamp() {
    let runtime = Installed::new();
    let pool = state(Progress::Quiescent);
    register_pool(pool.clone());
    let stamp = unsafe { root::progress_all() }.expect("quiescent pool");
    assert!(root::unchanged(stamp));
    assert_eq!(owners(), 1);
    completed_queue().prepare();
    pool.progress.set(Progress::Releasable);
    assert!(unsafe { root::progress_all() }.is_none());
    assert!(completed_queue().take_notification());
    assert!(!root::unchanged(stamp), "retirement must publish its own transition");
    runtime.stable_empty();
}

#[test]
fn release_callback_successor_requires_a_fresh_scan_and_keeps_its_owner() {
    let runtime = Installed::new();
    let successor = state(Progress::Pending);
    let pool = state(Progress::Releasable);
    *pool.successor.borrow_mut() = Some(successor.clone());
    register_pool(pool);
    completed_queue().prepare();
    assert!(unsafe { root::progress_all() }.is_none());
    assert!(completed_queue().take_notification());
    assert_eq!(owners(), 1, "successor work is still registered");
    completed_queue().prepare();
    assert!(unsafe { root::progress_all() }.is_none());
    assert!(!completed_queue().take_notification(), "no repeated wake without progress");
    successor.progress.set(Progress::Releasable);
    completed_queue().prepare();
    assert!(unsafe { root::progress_all() }.is_none());
    assert!(completed_queue().take_notification());
    runtime.stable_empty();
}

#[test]
fn captured_pool_and_control_retire_before_executor_completion_notification() {
    let runtime = Installed::new();
    let serial = root::prepare().unwrap();
    unsafe {
        root::commit_prepared(serial, pool_pointer(state(Progress::Releasable)),
            root::CapturedCallbacks { progress: captured_progress, release: captured_release });
    }
    assert_eq!(owners(), 2, "actual Executor and Control Native owners");
    completed_queue().prepare();
    clear_events();
    assert!(unsafe { root::progress_all() }.is_none());
    assert!(completed_queue().take_notification());
    assert_eq!(events(), ["drop-pool", "drop-control", "settle-native",
                         "settle-executor", "notify-completion"]);
    runtime.stable_empty();
}

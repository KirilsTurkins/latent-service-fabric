//! Bounded canonical readiness under the pinned wit-bindgen 0.62 C task ABI.
//! This connects ordinary WASI polls to retained original LSF calls. It owns
//! no OS thread, executor, Store, replacement budget, or ambient descriptor.
use std::{
    cell::RefCell,
    collections::BTreeMap,
    ffi::c_void,
    ptr,
    rc::{Rc, Weak},
    task::{Context, Waker},
};

const MAX_WAITABLES: usize = 64;
const MAX_OPERATIONS: usize = 32;

pub trait Progress {
    fn progress(&self, context: &mut Context<'_>);
}
pub trait Readiness {
    fn ready(&self) -> bool;
}

type Callback = unsafe extern "C" fn(*mut c_void, u32);
struct Completion {
    callback: Callback,
    pointer: *mut c_void,
}

pub struct Pump {
    set: u32,
    callbacks: RefCell<BTreeMap<u32, Completion>>,
    operations: RefCell<Vec<Weak<dyn Progress>>>,
}
thread_local! {
    static CURRENT: Rc<Pump> = Rc::new(Pump::new());
}

impl Pump {
    fn new() -> Self {
        // The canonical set is activation-local and exists only after a real
        // admitted logical owner has been registered by its caller.
        let set = unsafe { waitable_set_new() };
        assert_ne!(set, 0, "canonical waitable allocation failed");
        Self {
            set,
            callbacks: RefCell::new(BTreeMap::new()),
            operations: RefCell::new(Vec::with_capacity(MAX_OPERATIONS)),
        }
    }

    pub fn current() -> Rc<Self> {
        CURRENT.with(Rc::clone)
    }

    pub fn track(operation: &Rc<dyn Progress>) {
        let pump = Self::current();
        let mut operations = pump.operations.borrow_mut();
        operations.retain(|owner| owner.strong_count() != 0);
        assert!(
            operations.len() < MAX_OPERATIONS,
            "HTTP readiness owner limit"
        );
        operations.push(Rc::downgrade(operation));
    }

    /// The v2 clone/drop contract keeps this pump alive through actual pending
    /// import destruction, including a resource disposed outside a poll call.
    pub fn enter<R>(self: &Rc<Self>, action: impl FnOnce() -> R) -> R {
        let mut task = TaskV2 {
            v1: Task {
                version: 2,
                pointer: Rc::as_ptr(self).cast_mut().cast(),
                register,
                unregister,
            },
            vtable: &VTABLE,
        };
        let previous = unsafe { wasip3_task_set(ptr::from_mut(&mut task.v1)) };
        let restore = Restore(previous);
        let result = action();
        drop(restore);
        result
    }

    pub fn step(self: &Rc<Self>) {
        self.enter(|| {
            // Handle only events already available. A caller asking get/read
            // must be able to observe a genuinely incomplete operation.
            for _ in 0..MAX_WAITABLES {
                if !self.event(false) {
                    break;
                }
            }
            let owners: Vec<_> = self
                .operations
                .borrow()
                .iter()
                .filter_map(Weak::upgrade)
                .collect();
            let mut context = Context::from_waker(Waker::noop());
            for owner in owners {
                owner.progress(&mut context);
            }
        });
    }

    pub fn poll(self: &Rc<Self>, inputs: &[Rc<dyn Readiness>]) -> Vec<u32> {
        assert!(
            !inputs.is_empty() && inputs.len() <= MAX_WAITABLES,
            "WASI poll input limit"
        );
        loop {
            self.step();
            let ready: Vec<_> = inputs
                .iter()
                .enumerate()
                .filter(|(_, owner)| owner.ready())
                .map(|(index, _)| index as u32)
                .collect();
            if !ready.is_empty() {
                return ready;
            }
            // Body producers and runnable CLR siblings supply their existing
            // zero-delay pollable. Never spin or invent body/timer completion.
            assert!(
                !self.callbacks.borrow().is_empty(),
                "poll has no eligible readiness source"
            );
            self.enter(|| self.event(true));
        }
    }

    fn event(&self, wait: bool) -> bool {
        let mut payload = [0_u32; 2];
        let kind = unsafe {
            if wait {
                waitable_set_wait(self.set, &mut payload)
            } else {
                waitable_set_poll(self.set, &mut payload)
            }
        };
        if kind == 0 {
            return false;
        }
        // A cancelled canonical parent cannot mean that a requested timer or
        // pending HTTP call succeeded. The node's original stop cause remains
        // authoritative during Store retirement.
        assert_ne!(kind, 6, "canonical activation cancelled");
        let completion = self.callbacks.borrow_mut().remove(&payload[0]);
        let completion = completion.expect("foreign canonical readiness handle");
        unsafe {
            waitable_join(payload[0], 0);
            (completion.callback)(completion.pointer, payload[1]);
        }
        true
    }
}
impl Drop for Pump {
    fn drop(&mut self) {
        assert!(
            self.callbacks.get_mut().is_empty(),
            "pending canonical owner destruction"
        );
        unsafe { waitable_set_drop(self.set) };
    }
}

#[repr(C)]
struct Task {
    version: u32,
    pointer: *mut c_void,
    register: unsafe extern "C" fn(*mut c_void, u32, Callback, *mut c_void) -> *mut c_void,
    unregister: unsafe extern "C" fn(*mut c_void, u32) -> *mut c_void,
}
#[repr(C)]
struct TaskV2 {
    v1: Task,
    vtable: &'static Vtable,
}
#[repr(C)]
struct Vtable {
    register: unsafe extern "C" fn(*mut c_void, u32, Callback, *mut c_void) -> *mut c_void,
    unregister: unsafe extern "C" fn(*mut c_void, u32) -> *mut c_void,
    clone: unsafe extern "C" fn(*mut c_void) -> *mut c_void,
    drop: unsafe extern "C" fn(*mut c_void),
}
static VTABLE: Vtable = Vtable {
    register,
    unregister,
    clone: clone_pointer,
    drop: drop_pointer,
};

unsafe extern "C" fn register(
    pointer: *mut c_void,
    handle: u32,
    callback: Callback,
    data: *mut c_void,
) -> *mut c_void {
    // SAFETY: enter owns this Rc through the complete stack frame; v2 clones
    // retain it for pending imports. Registration pointers belong to pinned
    // wit-bindgen futures and are removed before those futures are destroyed.
    let pump = unsafe { &*pointer.cast::<Pump>() };
    let mut callbacks = pump.callbacks.borrow_mut();
    assert!(
        callbacks.contains_key(&handle) || callbacks.len() < MAX_WAITABLES,
        "canonical waitable limit"
    );
    let old = callbacks.insert(
        handle,
        Completion {
            callback,
            pointer: data,
        },
    );
    unsafe { waitable_join(handle, pump.set) };
    old.map_or(ptr::null_mut(), |value| value.pointer)
}
unsafe extern "C" fn unregister(pointer: *mut c_void, handle: u32) -> *mut c_void {
    let pump = unsafe { &*pointer.cast::<Pump>() };
    unsafe { waitable_join(handle, 0) };
    pump.callbacks
        .borrow_mut()
        .remove(&handle)
        .map_or(ptr::null_mut(), |value| value.pointer)
}
unsafe extern "C" fn clone_pointer(pointer: *mut c_void) -> *mut c_void {
    unsafe { Rc::increment_strong_count(pointer.cast::<Pump>()) };
    pointer
}
unsafe extern "C" fn drop_pointer(pointer: *mut c_void) {
    unsafe { Rc::decrement_strong_count(pointer.cast::<Pump>()) };
}
struct Restore(*mut Task);
impl Drop for Restore {
    fn drop(&mut self) {
        unsafe { wasip3_task_set(self.0) };
    }
}
unsafe extern "C" {
    fn wasip3_task_set(task: *mut Task) -> *mut Task;
}
#[link(wasm_import_module = "$root")]
unsafe extern "C" {
    #[link_name = "[waitable-set-new]"]
    fn waitable_set_new() -> u32;
    #[link_name = "[waitable-set-drop]"]
    fn waitable_set_drop(set: u32);
    #[link_name = "[waitable-join]"]
    fn waitable_join(handle: u32, set: u32);
    #[link_name = "[waitable-set-wait]"]
    fn waitable_set_wait(set: u32, payload: *mut [u32; 2]) -> u32;
    #[link_name = "[waitable-set-poll]"]
    fn waitable_set_poll(set: u32, payload: *mut [u32; 2]) -> u32;
}

// SPDX-License-Identifier: MIT OR Apache-2.0
//! Root drain registrations for the selected captured executor port.
//!
//! Each pointer is one real retained pool Arc supplied by that closed port.
//! No callback polls user futures on the root. Progress may only publish the
//! real generation Close messages and inspect the actual PAL frame state.
//! The pool consumes its retained Arc during release on this NORMAL root
//! frame, so user captures never first Drop in the stackless System postlude.
use super::executor_control::Control;
use super::owner::{Kind, Owner, SystemOwned, Token};
use super::{allocation_error, completed_queue, current_task, ensure_runtime, existing};
use crate::io;
use crate::ptr::NonNull;

const MAX_EXECUTORS: usize = 32;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Handle {
    slot: u8,
    serial: u64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Progress {
    // An accepted future/reservation or real worker/TLS frame remains.
    Pending,
    // All work and worker frames ended. User handles or completed wakers may
    // still live in root TLS; keep their pool and logical Executor registered.
    Quiescent,
    // In addition, no user handle/waker can submit again. The only remaining
    // strong reference is this root registration's actual retained pool Arc.
    Releasable,
}
#[derive(Clone, Copy)]
pub(crate) struct Callbacks {
    pub(crate) progress: unsafe fn(NonNull<()>) -> Progress,
    pub(crate) release: unsafe fn(NonNull<()>),
}
#[derive(Clone, Copy)]
pub(crate) struct CapturedCallbacks {
    pub(crate) progress: unsafe extern "C" fn(*mut ()) -> u32,
    pub(crate) release: unsafe extern "C" fn(*mut ()),
}
#[derive(Clone, Copy)]
enum Port {
    Source(Callbacks),
    Captured(CapturedCallbacks),
}
impl Port {
    unsafe fn progress(self, pointer: NonNull<()>) -> Progress {
        match self {
            Self::Source(callbacks) => unsafe { (callbacks.progress)(pointer) },
            Self::Captured(callbacks) => match unsafe { (callbacks.progress)(pointer.as_ptr()) } {
                0 => Progress::Pending,
                1 => Progress::Quiescent,
                2 => Progress::Releasable,
                _ => panic!("invalid captured executor progress"),
            },
        }
    }
    unsafe fn release(self, pointer: NonNull<()>) {
        match self {
            Self::Source(callbacks) => unsafe { (callbacks.release)(pointer) },
            Self::Captured(callbacks) => unsafe { (callbacks.release)(pointer.as_ptr()) },
        }
    }
}
struct Prepared {
    // Field order is not used for successful retirement; callers explicitly
    // drop actual Control backing before its logical Executor below.
    control: SystemOwned<Control>,
    executor: Owner,
}
struct Live {
    pointer: NonNull<()>,
    port: Port,
    control: Option<SystemOwned<Control>>,
    executor: Owner,
}
enum Entry {
    Reserved {
        serial: u64,
        pointer: Option<NonNull<()>>,
    },
    Prepared {
        serial: u64,
        value: Prepared,
    },
    Live {
        serial: u64,
        value: Live,
    },
}
impl Entry {
    fn serial(&self) -> u64 {
        match self {
            Self::Reserved { serial, .. }
            | Self::Prepared { serial, .. }
            | Self::Live { serial, .. } => *serial,
        }
    }
    fn pointer(&self) -> Option<NonNull<()>> {
        match self {
            Self::Reserved { pointer, .. } => *pointer,
            Self::Prepared { .. } => None,
            Self::Live { value, .. } => Some(value.pointer),
        }
    }
}
// Included INSIDE Runtime's prepaid SystemOwned allocation. This fixed table
// never allocates another backing Vec or claims that Arc payload bytes vanish
// when a logical Executor settles; those bytes keep their original memory cost.
pub(crate) struct Registry {
    entries: [Option<Entry>; MAX_EXECUTORS],
    serial: u64,
    epoch: u64,
}
impl Registry {
    pub(crate) fn new() -> Self {
        Self {
            entries: crate::array::from_fn(|_| None),
            serial: 0,
            epoch: 0,
        }
    }
    fn reserve(&mut self, pointer: Option<NonNull<()>>) -> io::Result<Handle> {
        if pointer.is_some()
            && self
                .entries
                .iter()
                .flatten()
                .any(|entry| entry.pointer() == pointer)
        {
            return Err(io::Error::from(io::ErrorKind::InvalidInput));
        }
        let slot = self
            .entries
            .iter()
            .position(Option::is_none)
            .ok_or_else(|| io::Error::from(io::ErrorKind::WouldBlock))?;
        let serial = self
            .serial
            .checked_add(1)
            .ok_or_else(|| io::Error::from(io::ErrorKind::WouldBlock))?;
        self.serial = serial;
        self.entries[slot] = Some(Entry::Reserved { serial, pointer });
        Ok(Handle {
            slot: slot as u8,
            serial,
        })
    }
    fn entry(&self, handle: Handle) -> &Entry {
        self.entries
            .get(usize::from(handle.slot))
            .and_then(Option::as_ref)
            .filter(|entry| entry.serial() == handle.serial)
            .expect("stale selected executor root identity")
    }
    fn rollback(&mut self, handle: Handle) {
        assert!(matches!(self.entry(handle), Entry::Reserved { .. }));
        self.entries[usize::from(handle.slot)] = None;
    }
    fn commit(&mut self, handle: Handle, value: Live) {
        assert!(
            matches!(self.entry(handle), Entry::Reserved { pointer: Some(pointer), .. } if *pointer == value.pointer)
        );
        self.entries[usize::from(handle.slot)] = Some(Entry::Live {
            serial: handle.serial,
            value,
        });
    }
    fn resolve(&self, serial: u64) -> io::Result<Handle> {
        self.entries
            .iter()
            .enumerate()
            .find_map(|(slot, entry)| {
                entry
                    .as_ref()
                    .filter(|entry| entry.serial() == serial)
                    .map(|_| Handle {
                        slot: slot as u8,
                        serial,
                    })
            })
            .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidInput))
    }
    fn snapshot(&self) -> [Option<Handle>; MAX_EXECUTORS] {
        crate::array::from_fn(|slot| {
            self.entries[slot].as_ref().map(|entry| Handle {
                slot: slot as u8,
                serial: entry.serial(),
            })
        })
    }
    pub(crate) fn is_empty(&self) -> bool {
        self.entries.iter().all(Option::is_none)
    }
}
fn state<R>(f: impl FnOnce(&mut Registry) -> R) -> R {
    let pointer = existing();
    assert!(!pointer.is_null(), "selected executor root runtime absent");
    // No Runtime aggregate reference, broker, allocation, callback or yield
    // is allowed inside this Copy-state mutation boundary.
    unsafe { f(&mut *(*pointer).executors.get()) }
}
struct Reservation(Option<Handle>);
impl Drop for Reservation {
    fn drop(&mut self) {
        if let Some(handle) = self.0.take() {
            state(|registry| registry.rollback(handle));
            changed();
        }
    }
}

/// The caller retains ownership of pointer on Err; on Ok this registry owns
/// its ONE retained Arc until the matching release callback consumes it.
///
/// # Safety
/// The selected complete graph must authenticate these callback bodies and
/// pointer construction from the captured executor port. This private source
/// API alone does not prohibit an arbitrary callback or cross-Store pointer.
pub(crate) unsafe fn register(pointer: NonNull<()>, callbacks: Callbacks) -> io::Result<Handle> {
    ensure_runtime()?;
    let handle = state(|registry| registry.reserve(Some(pointer)))?;
    let mut reservation = Reservation(Some(handle));
    let executor = Owner::admit(Kind::Executor, Some(current_task())).map_err(super::io_error)?;
    state(|registry| {
        registry.commit(
            handle,
            Live {
                pointer,
                port: Port::Source(callbacks),
                control: None,
                executor,
            },
        )
    });
    reservation.0 = None;
    changed();
    Ok(handle)
}

// Two-phase setup for the authenticated ordinary pool. The entry is visible
// before either fallible owner admission; a suspended root drain cannot
// mistake the not-yet-published pool for an empty executor registry.
pub(crate) fn prepare() -> io::Result<u64> {
    ensure_runtime()?;
    let handle = state(|registry| registry.reserve(None))?;
    let mut reservation = Reservation(Some(handle));
    let executor = Owner::admit(Kind::Executor, Some(current_task())).map_err(super::io_error)?;
    let control =
        SystemOwned::try_new(Control::new(), Some(executor.token())).map_err(allocation_error)?;
    state(|registry| {
        assert!(matches!(
            registry.entry(handle),
            Entry::Reserved { pointer: None, .. }
        ));
        registry.entries[usize::from(handle.slot)] = Some(Entry::Prepared {
            serial: handle.serial,
            value: Prepared { control, executor },
        });
    });
    reservation.0 = None;
    changed();
    Ok(handle.serial)
}

/// Binding consumes the caller's ONE retained pool Arc on success only. No
/// allocation, callback, owner admission or canonical handoff occurs here.
/// The complete selected graph must authenticate the original Arc construction
/// and both captured callback bodies; an opaque serial alone is not authority.
pub(crate) unsafe fn commit_prepared(
    serial: u64,
    pointer: NonNull<()>,
    callbacks: CapturedCallbacks,
) {
    state(|registry| {
        let handle = registry
            .resolve(serial)
            .expect("prepared captured executor identity");
        assert!(matches!(registry.entry(handle), Entry::Prepared { .. }));
        assert!(!registry
            .entries
            .iter()
            .flatten()
            .any(|entry| entry.pointer() == Some(pointer)));
        let Entry::Prepared { value, .. } =
            registry.entries[usize::from(handle.slot)].take().unwrap()
        else {
            unreachable!()
        };
        registry.entries[usize::from(handle.slot)] = Some(Entry::Live {
            serial,
            value: Live {
                pointer,
                port: Port::Captured(callbacks),
                control: Some(value.control),
                executor: value.executor,
            },
        });
    });
    // Deliberately no changed()/Wait wake after pointer publication: the
    // constructor has not yet provisioned a worker, and may not suspend here.
}

pub(crate) fn abort_prepared(serial: u64) {
    let value = state(|registry| {
        let handle = registry
            .resolve(serial)
            .expect("uncommitted pool setup identity");
        assert!(matches!(registry.entry(handle), Entry::Prepared { .. }));
        match registry.entries[usize::from(handle.slot)].take().unwrap() {
            Entry::Prepared { value, .. } => value,
            _ => unreachable!(),
        }
    });
    drop(value.control);
    drop(value.executor);
    changed();
}

#[derive(Clone, Copy)]
pub(crate) struct BoundControl {
    pub(crate) handle: Handle,
    pub(crate) pointer: NonNull<()>,
    pub(crate) parent: Token,
    pub(crate) control: NonNull<Control>,
}
/// Copy stable identities before any method that can admit, wait or invoke a
/// callback. The actual caller retains its Pool Arc / registered worker, so
/// root release cannot free this Control while the method is suspended.
pub(crate) fn control(serial: u64) -> io::Result<BoundControl> {
    state(|registry| {
        let handle = registry.resolve(serial)?;
        match registry.entry(handle) {
            Entry::Live { value, .. } => Ok(BoundControl {
                handle,
                pointer: value.pointer,
                parent: value.executor.token(),
                control: value
                    .control
                    .as_ref()
                    .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidInput))?
                    .pointer(),
            }),
            _ => Err(io::Error::from(io::ErrorKind::InvalidInput)),
        }
    })
}

fn captured_for_pointer(pointer: NonNull<()>) -> (NonNull<Control>, CapturedCallbacks) {
    state(|registry| {
        registry
            .entries
            .iter()
            .flatten()
            .find_map(|entry| match entry {
                Entry::Live { value, .. } if value.pointer == pointer => match value.port {
                    Port::Captured(callbacks) => Some((
                        value
                            .control
                            .as_ref()
                            .expect("captured control backing")
                            .pointer(),
                        callbacks,
                    )),
                    _ => None,
                },
                _ => None,
            })
            .expect("live captured worker pool identity")
    })
}
pub(crate) unsafe fn worker_tls_drained(pointer: NonNull<()>, canonical: u32) {
    let (control, _) = captured_for_pointer(pointer);
    unsafe { control.as_ref() }
        .worker_tls_drained(canonical)
        .expect("actual captured worker TLS boundary");
}
pub(crate) unsafe fn worker_frames_exited(pointer: NonNull<()>, canonical: u32) {
    let (control, _) = captured_for_pointer(pointer);
    unsafe { control.as_ref() }
        .worker_frames_exited(canonical)
        .expect("actual captured worker frame boundary");
}
pub(crate) unsafe fn worker_release(pointer: NonNull<()>) {
    let (_, callbacks) = captured_for_pointer(pointer);
    // Root's retained Arc is still live: consuming this worker reference
    // cannot be the final PoolState / user recipe destructor on this boundary.
    unsafe { (callbacks.release)(pointer.as_ptr()) };
}

/// A real registered Executor must still retain this exact pool pointer.
/// No registration reservation or stale generation authorizes a worker lease.
pub(crate) fn owns(handle: Handle, pointer: NonNull<()>) -> bool {
    state(|registry| {
        matches!(registry.entries.get(usize::from(handle.slot)).and_then(Option::as_ref),
            Some(Entry::Live { serial, value }) if *serial == handle.serial && value.pointer == pointer)
    })
}

/// The port invokes this AFTER releasing its own Mutex and publishing each
/// accept/complete/requeue/worker-exit transition. The ordinary WaitQueue
/// carries the real parked root notification; there is no side executor.
pub(crate) fn changed() {
    if !existing().is_null() {
        state(|registry| {
            registry.epoch = registry
                .epoch
                .checked_add(1)
                .expect("selected executor transition generation exhausted")
        });
        completed_queue().notify_all();
    }
}

/// Called only while real root Rust/TLS cleanup frames are installed. Recheck
/// after every callback and actual Arc Drop: both can accept work in another
/// pool or install a successor generation. Never hold registry references
/// across those operations or discard an accepted work record as shutdown.
#[derive(Clone, Copy)]
pub(crate) struct Stamp(u64);
pub(crate) fn unchanged(stamp: Stamp) -> bool {
    state(|registry| registry.epoch == stamp.0)
}

pub(crate) unsafe fn progress_all() -> Option<Stamp> {
    let (handles, epoch) = state(|registry| (registry.snapshot(), registry.epoch));
    let mut complete = true;
    for handle in handles.into_iter().flatten() {
        let call = state(|registry| match registry.entry(handle) {
            Entry::Reserved { .. } | Entry::Prepared { .. } => None,
            Entry::Live { value, .. } => Some((value.pointer, value.port)),
        });
        let Some((pointer, callbacks)) = call else {
            complete = false;
            continue;
        };
        match unsafe { callbacks.progress(pointer) } {
            Progress::Pending => complete = false,
            Progress::Quiescent => {}
            Progress::Releasable => {
                let live = state(|registry| {
                    assert!(
                        matches!(registry.entry(handle), Entry::Live { value, .. } if value.pointer == pointer)
                    );
                    match registry.entries[usize::from(handle.slot)].take().unwrap() {
                        Entry::Live { value, .. } => value,
                        Entry::Reserved { .. } | Entry::Prepared { .. } => unreachable!(),
                    }
                });
                // The actual pool Arc/control block is released FIRST, while
                // its logical Executor and Runtime Native backing remain.
                // A panic/trap does not become successful retirement.
                unsafe {
                    live.port.release(live.pointer);
                }
                // Native covers the actual Control destructor/allocation free,
                // after the real Pool Arc/control block was physically freed.
                drop(live.control);
                drop(live.executor);
                // Removing this entry invalidates the snapshot below. If it
                // happens on drain's second check, its completed waiter is
                // already queued and no worker may remain to wake it. Publish
                // the retirement only after all original backing/owners have
                // actually retired, then let that waiter recheck the registry.
                // Never hold the registry borrow or a pool pointer at the wake.
                changed();
            }
        }
    }
    // A callback can register another real pool, or a destructor can accept
    // work after an earlier pool reported Quiescent. Inspect every current
    // entry again on the next round rather than trusting the old snapshot.
    let current = state(|registry| registry.snapshot());
    (complete && current == handles && state(|registry| registry.epoch == epoch))
        .then_some(Stamp(epoch))
}
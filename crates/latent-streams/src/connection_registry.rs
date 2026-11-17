//! One prepaid table: active paid weak owners become retiring strong owners.
//! No destructor/callback runs while the registry mutex is held.
use crate::{connection::Connection, error, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use latent_core::HostMemoryReservation;
use std::{
    ops::Deref,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, Weak,
    },
};

pub(crate) const CAPACITY: usize = 32;

pub(crate) fn arc_bytes<T>() -> usize {
    // Pinned std::sync::ArcInner is repr(C): two AtomicUsize counters then T.
    // extend + final pad_to_align covers BOTH inter-field and final padding.
    std::alloc::Layout::new::<[std::sync::atomic::AtomicUsize; 2]>()
        .extend(std::alloc::Layout::new::<T>())
        .expect("three fixed provider Arc layouts fit usize")
        .0
        .pad_to_align()
        .size()
}

// The same original fixed envelope pays the connection, its strong-custody
// and billing Arc allocations. No raw Arc or Weak to either charge can escape:
// `into_inner` deallocates the final billing header before refunding the guard.
struct ConnectionCharge {
    allocation: HostMemoryReservation,
    _metadata: ProviderMetadata,
}
struct Billing(Option<Arc<ConnectionCharge>>);
impl Clone for Billing {
    fn clone(&self) -> Self {
        Self(self.0.as_ref().map(Arc::clone))
    }
}
impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(owner) = self.0.take() {
            drop(Arc::into_inner(owner));
        }
    }
}
struct StrongCustody {
    // Drop billing before the opening row. A registry weak still retains its
    // own billing clone until the original Connection header is released.
    billing: Billing,
    opening: RetirementCustody,
    failed_retirement: AtomicBool,
}
impl Drop for StrongCustody {
    fn drop(&mut self) {
        if self.failed_retirement.load(Ordering::Acquire) {
            // Leave this already-prepaid row sticky without forgetting a paid
            // Arc. Its registry has a finite lifetime and finite slot table.
            drop(self.opening.owner.take());
        } else {
            self.opening.begin_drop();
        }
    }
}
struct StrongBilling(Option<Arc<StrongCustody>>);
impl Clone for StrongBilling {
    fn clone(&self) -> Self {
        Self(self.0.as_ref().map(Arc::clone))
    }
}
impl Drop for StrongBilling {
    fn drop(&mut self) {
        if let Some(owner) = self.0.take() {
            drop(Arc::into_inner(owner));
        }
    }
}

/// A strong Connection Arc with the same original paid lifetime outside it.
/// Every strong clone and every registry upgrade carries this owner.
pub(crate) struct ConnectionOwner {
    inner: Option<Arc<Connection>>,
    custody: Option<StrongBilling>,
}
impl ConnectionOwner {
    pub(crate) fn allocation_bytes() -> usize {
        arc_bytes::<Connection>() + arc_bytes::<ConnectionCharge>() + arc_bytes::<StrongCustody>()
    }
    pub(crate) fn new(
        value: Connection,
        allocation: HostMemoryReservation,
        metadata: ProviderMetadata,
        opening: RetirementCustody,
    ) -> Self {
        let billing = Billing(Some(Arc::new(ConnectionCharge {
            allocation,
            _metadata: metadata,
        })));
        let custody = StrongBilling(Some(Arc::new(StrongCustody {
            billing,
            opening,
            failed_retirement: AtomicBool::new(false),
        })));
        let mut owner = Self {
            inner: Some(Arc::new(value)),
            custody: Some(custody),
        };
        // Install physical-first ownership before confirming either allocation.
        Arc::get_mut(
            owner
                .custody
                .as_mut()
                .expect("new custody")
                .0
                .as_mut()
                .expect("new strong owner"),
        )
        .and_then(|custody| Arc::get_mut(custody.billing.0.as_mut().expect("new billing")))
        .expect("new unique connection charge")
        .allocation
        .confirm();
        owner
    }
    fn downgrade(&self) -> PaidWeak {
        let custody = self.custody.as_ref().expect("live connection custody");
        PaidWeak {
            owner: Arc::downgrade(self.inner.as_ref().expect("live connection")),
            _billing: custody
                .0
                .as_ref()
                .expect("live strong owner")
                .billing
                .clone(),
            custody: Some(custody.clone()),
        }
    }
    fn as_ptr(&self) -> *const Connection {
        Arc::as_ptr(self.inner.as_ref().expect("live connection"))
    }
}
impl Clone for ConnectionOwner {
    fn clone(&self) -> Self {
        Self {
            inner: Some(Arc::clone(self.inner.as_ref().expect("live connection"))),
            custody: Some(
                self.custody
                    .as_ref()
                    .expect("live connection custody")
                    .clone(),
            ),
        }
    }
}
impl Deref for ConnectionOwner {
    type Target = Connection;
    fn deref(&self) -> &Connection {
        self.inner.as_deref().expect("live connection")
    }
}
impl Drop for ConnectionOwner {
    fn drop(&mut self) {
        let Some(inner) = self.inner.take() else {
            return;
        };
        let pointer = Arc::as_ptr(&inner);
        let held = self.custody.take();
        // Every strong Connection reference uses this wrapper. into_inner
        // identifies the unique last owner even when releases race; only it
        // may detach the paid weak after the value destructor returns.
        let value = Arc::into_inner(inner);
        let last = value.is_some();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(value)));
        if let Err(panic) = result {
            if let Some(custody) = held.as_ref().and_then(|v| v.0.as_ref()) {
                custody.failed_retirement.store(true, Ordering::Release);
            }
            // The registry slot (when still alive) retains its exact paid weak
            // header and sticky row. Never forget a new cross-generation Arc.
            drop(held);
            std::panic::resume_unwind(panic);
        }
        #[cfg(all(test, unix))]
        if !last {
            if let Some(marker) = held
                .as_ref()
                .and_then(|value| value.0.as_ref())
                .and_then(|custody| custody.opening.owner.as_ref())
            {
                if let Some(registry) = marker.registry.upgrade() {
                    registry.pause_non_last_drop_for_test();
                }
            }
        }
        if last {
            if let Some(custody) = held.as_ref().and_then(|v| v.0.as_ref()) {
                if let Some(marker) = &custody.opening.owner {
                    if let Some(registry) = marker.registry.upgrade() {
                        registry.detach_dead_weak(
                            marker.index,
                            custody.opening.generation,
                            pointer,
                        );
                    }
                }
            }
        }
        drop(held);
    }
}

struct PaidWeak {
    owner: Weak<Connection>,
    // The SAME original connection charge, not another reservation. A dead
    // Weak still physically retains the Arc allocation until header retirement.
    _billing: Billing,
    custody: Option<StrongBilling>,
}
impl PaidWeak {
    fn upgrade(&self) -> Option<ConnectionOwner> {
        // Do not drop a temporary last Connection or custody under the table
        // lock. A missing custody cannot be resurrected after strong count 0.
        let custody = self.custody.as_ref()?;
        let inner = self.owner.upgrade()?;
        Some(ConnectionOwner {
            inner: Some(inner),
            custody: Some(custody.clone()),
        })
    }
}
#[derive(Clone, Copy)]
struct Opening {
    sequence: u64,
    holders: u8,
}
enum Slot {
    Empty,
    Opening(Opening),
    Active {
        weak: PaidWeak,
        opening: Option<Opening>,
    },
    Retiring {
        owner: ConnectionOwner,
        opening: Option<Opening>,
    },
}
impl Slot {
    fn owner(&self) -> Option<ConnectionOwner> {
        match self {
            Self::Empty | Self::Opening(_) => None,
            Self::Active { weak, .. } => weak.upgrade(),
            Self::Retiring { owner, .. } => Some(owner.clone()),
        }
    }
    fn has_opening(&self) -> bool {
        match self {
            Self::Opening(_) => true,
            Self::Active { opening, .. } | Self::Retiring { opening, .. } => opening.is_some(),
            Self::Empty => false,
        }
    }
    fn reusable(&self) -> bool {
        matches!(self, Self::Empty)
            || matches!(self, Self::Active { weak, opening: None } if weak.owner.strong_count() == 0)
    }
}

pub(crate) struct Registry {
    state: Mutex<RegistryState>,
    #[cfg(all(test, unix))]
    registration_pause: Mutex<Option<(std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>)>>,
    #[cfg(all(test, unix))]
    release_pause: Mutex<Option<(std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>)>>,
    #[cfg(all(test, unix))]
    empty_release_pause:
        Mutex<Option<(std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>)>>,
    #[cfg(all(test, unix))]
    observation_pause: Mutex<Option<(std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>)>>,
    #[cfg(all(test, unix))]
    non_last_drop_pause:
        Mutex<Option<(std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>)>>,
    // Preallocated once per paid slot; no allocation is reused while its
    // previous Arc destructor is still running.
    markers: [Arc<OpeningMarker>; CAPACITY],
    // Last field: actual table and Arc-owned connection refs drop first.
    billing: Arc<ProviderMetadata>,
}
struct RegistryState {
    closed: bool,
    next_opening: u64,
    slots: [Slot; CAPACITY],
}
pub(crate) struct OpeningMarker {
    // The original charge pays both the weak registry allocation and this
    // ticket even if its provider is dropped while physical work remains.
    registry: Weak<Registry>,
    _billing: Arc<ProviderMetadata>,
    index: usize,
}
impl OpeningMarker {
    fn acquire(&self, generation: u64) -> bool {
        self.registry
            .upgrade()
            .is_some_and(|registry| registry.acquire_opening(self.index, generation))
    }
    fn release(&self, generation: u64) {
        if let Some(registry) = self.registry.upgrade() {
            #[cfg(all(test, unix))]
            registry.pause_release_for_test();
            registry.release_opening(self.index, generation);
            #[cfg(all(test, unix))]
            registry.pause_empty_release_for_test(self.index);
        }
    }
}
impl latent_capabilities::broker::io::StreamRetirementObserver for OpeningMarker {
    fn release_stream_retirement(&self, sequence: u64) {
        self.release(sequence);
    }
}
/// A reference to the same prepaid opening row. It is placed after the stream
/// fields it observes and never changes the original resource or refund path.
pub(crate) struct RetirementCustody {
    owner: Option<Arc<OpeningMarker>>,
    generation: u64,
    entered_unwinding: bool,
}
impl RetirementCustody {
    fn acquire(owner: Arc<OpeningMarker>, generation: u64) -> Result<Self, StreamError> {
        if !owner.acquire(generation) {
            return Err(error(StreamErrorCode::Revoked));
        }
        Ok(Self {
            owner: Some(owner),
            generation,
            // Setup can be invoked from a caller already unwinding. A normal
            // refusal then drops this guard before an enclosing future exists.
            // A newly started panic is still distinguishable and keeps the row.
            entered_unwinding: std::thread::panicking(),
        })
    }
    pub fn try_clone(&self) -> Result<Self, StreamError> {
        let owner = self
            .owner
            .as_ref()
            .ok_or_else(|| error(StreamErrorCode::Revoked))?;
        Self::acquire(Arc::clone(owner), self.generation)
    }
    pub fn begin_drop(&mut self) {
        self.entered_unwinding = std::thread::panicking();
    }
    pub fn into_stream_guard(mut self) -> latent_capabilities::broker::io::StreamRetirementGuard {
        let owner = self.owner.take().expect("original opening custody");
        latent_capabilities::broker::io::StreamRetirementGuard::new(owner, self.generation)
    }
}
impl Drop for RetirementCustody {
    fn drop(&mut self) {
        if let Some(owner) = self.owner.take() {
            // Leave the already-paid row outstanding on an unexpected
            // destructor unwind, without leaking its marker allocation.
            if !std::thread::panicking() || self.entered_unwinding {
                owner.release(self.generation);
            }
        }
    }
}
/// Same original row held through future, socket and pool destruction.
pub(crate) struct OpeningTicket {
    marker: Arc<OpeningMarker>,
    sequence: u64,
    custody: RetirementCustody,
}
impl OpeningTicket {
    pub fn try_clone_custody(&self) -> Result<RetirementCustody, StreamError> {
        self.custody.try_clone()
    }
    #[cfg(all(test, unix))]
    pub fn marker_weak_for_test(&self) -> Weak<OpeningMarker> {
        Arc::downgrade(&self.marker)
    }
}
impl Drop for OpeningTicket {
    fn drop(&mut self) {
        self.custody.begin_drop();
    }
}
pub(crate) struct RegistryWeak {
    owner: Weak<Registry>,
    // Every surviving Weak keeps the original table/header charge paid.
    _billing: Arc<ProviderMetadata>,
}
impl Registry {
    pub fn new(pools: &ProviderPools) -> Result<Arc<Self>, StreamError> {
        // Actual larger enum table + both Arc allocations are charged BEFORE
        // allocation. No arbitrary caller token or assumed Weak-sized layout.
        let bytes = arc_bytes::<Self>()
            + arc_bytes::<ProviderMetadata>()
            + CAPACITY * arc_bytes::<OpeningMarker>();
        let billing = Arc::new(pools.reserve_protocol_metadata(bytes)?);
        Ok(Arc::new_cyclic(|registry| Self {
            state: Mutex::new(RegistryState {
                closed: false,
                next_opening: 0,
                slots: std::array::from_fn(|_| Slot::Empty),
            }),
            #[cfg(all(test, unix))]
            registration_pause: Mutex::new(None),
            #[cfg(all(test, unix))]
            release_pause: Mutex::new(None),
            #[cfg(all(test, unix))]
            empty_release_pause: Mutex::new(None),
            #[cfg(all(test, unix))]
            observation_pause: Mutex::new(None),
            #[cfg(all(test, unix))]
            non_last_drop_pause: Mutex::new(None),
            markers: std::array::from_fn(|index| {
                Arc::new(OpeningMarker {
                    registry: registry.clone(),
                    _billing: Arc::clone(&billing),
                    index,
                })
            }),
            billing: Arc::clone(&billing),
        }))
    }
    pub fn downgrade(self: &Arc<Self>) -> RegistryWeak {
        RegistryWeak {
            owner: Arc::downgrade(self),
            _billing: Arc::clone(&self.billing),
        }
    }
    pub fn reserve_opening(self: &Arc<Self>) -> Result<OpeningTicket, StreamError> {
        let (marker, sequence, displaced) = {
            let mut state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            if state.closed {
                return Err(error(StreamErrorCode::Revoked));
            }
            let index = state
                .slots
                .iter()
                .position(Slot::reusable)
                .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
            let sequence = state
                .next_opening
                .checked_add(1)
                .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
            let marker = Arc::clone(&self.markers[index]);
            state.next_opening = sequence;
            let displaced = std::mem::replace(
                &mut state.slots[index],
                Slot::Opening(Opening {
                    sequence,
                    holders: 0,
                }),
            );
            (marker, sequence, displaced)
        };
        drop(displaced);
        let custody = match RetirementCustody::acquire(marker.clone(), sequence) {
            Ok(custody) => custody,
            Err(failure) => {
                self.release_empty_opening(marker.index, sequence);
                return Err(failure);
            }
        };
        Ok(OpeningTicket {
            marker,
            sequence,
            custody,
        })
    }
    pub fn register(
        &self,
        opening: &OpeningTicket,
        owner: &ConnectionOwner,
    ) -> Result<(), StreamError> {
        #[cfg(all(test, unix))]
        if let Some((reached, resume)) = self.registration_pause.lock().unwrap().take() {
            let _ = reached.send(());
            let _ = resume.recv_timeout(std::time::Duration::from_secs(20));
        }
        let weak = owner.downgrade();
        let displaced = {
            let mut state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            if state.closed || !std::ptr::eq(self, opening.marker.registry.as_ptr()) {
                return Err(error(StreamErrorCode::Revoked));
            }
            let slot = state
                .slots
                .get_mut(opening.marker.index)
                .ok_or_else(|| error(StreamErrorCode::Revoked))?;
            if !matches!(slot, Slot::Opening(current) if current.sequence == opening.sequence && current.holders > 0)
            {
                return Err(error(StreamErrorCode::Revoked));
            }
            let Slot::Opening(current) = slot else {
                unreachable!()
            };
            let current = *current;
            std::mem::replace(
                slot,
                Slot::Active {
                    weak,
                    opening: Some(current),
                },
            )
        };
        drop(displaced); // Last paid weak/header retirement is outside mutex.
        Ok(())
    }
    pub fn snapshot(&self, index: usize) -> Result<Option<ConnectionOwner>, StreamError> {
        self.observe(index).map(|(owner, _)| owner)
    }
    pub fn observe(&self, index: usize) -> Result<(Option<ConnectionOwner>, bool), StreamError> {
        let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
        let Some(slot) = state.slots.get(index) else {
            return Ok((None, false));
        };
        let owner = slot.owner();
        let pending = owner.is_none() && slot.has_opening();
        drop(state);
        #[cfg(all(test, unix))]
        if owner.is_some() {
            if let Some((reached, resume)) = self.observation_pause.lock().unwrap().take() {
                let _ = reached.send(());
                let _ = resume.recv_timeout(std::time::Duration::from_secs(20));
            }
        }
        Ok((owner, pending))
    }
    #[cfg(all(test, unix))]
    pub fn pause_next_observed_owner(
        &self,
    ) -> (std::sync::mpsc::Receiver<()>, std::sync::mpsc::Sender<()>) {
        let (reached, wait) = std::sync::mpsc::channel();
        let (resume, release) = std::sync::mpsc::channel();
        assert!(self
            .observation_pause
            .lock()
            .unwrap()
            .replace((reached, release))
            .is_none());
        (wait, resume)
    }
    #[cfg(all(test, unix))]
    pub fn pause_next_non_last_drop(
        &self,
    ) -> (std::sync::mpsc::Receiver<()>, std::sync::mpsc::Sender<()>) {
        let (reached, wait) = std::sync::mpsc::channel();
        let (resume, release) = std::sync::mpsc::channel();
        assert!(self
            .non_last_drop_pause
            .lock()
            .unwrap()
            .replace((reached, release))
            .is_none());
        (wait, resume)
    }
    #[cfg(all(test, unix))]
    fn pause_non_last_drop_for_test(&self) {
        let pause = self.non_last_drop_pause.lock().unwrap().take();
        if let Some((reached, resume)) = pause {
            let _ = reached.send(());
            let _ = resume.recv_timeout(std::time::Duration::from_secs(20));
        }
    }
    /// A callback-free, monotone empty observation for a closed registry.
    /// In particular this never upgrades or drops a Connection under the
    /// caller's lifecycle mutex.
    pub fn closed_and_empty(&self) -> bool {
        let Ok(state) = self.state.try_lock() else {
            return false;
        };
        state.closed
            && state.slots.iter().all(|slot| match slot {
                Slot::Empty => true,
                Slot::Active {
                    weak,
                    opening: None,
                } => weak.owner.strong_count() == 0,
                Slot::Opening(_) | Slot::Active { .. } | Slot::Retiring { .. } => false,
            })
    }
    fn acquire_opening(&self, index: usize, sequence: u64) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let opening = match state.slots.get_mut(index) {
            Some(Slot::Opening(opening)) => Some(opening),
            Some(Slot::Active { opening, .. } | Slot::Retiring { opening, .. }) => opening.as_mut(),
            _ => None,
        };
        let Some(opening) = opening else {
            return false;
        };
        if opening.sequence != sequence || opening.holders >= 8 {
            return false;
        }
        opening.holders += 1;
        true
    }
    fn release_empty_opening(&self, index: usize, sequence: u64) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if matches!(state.slots.get(index), Some(Slot::Opening(opening)) if opening.sequence == sequence && opening.holders == 0)
        {
            state.slots[index] = Slot::Empty;
        }
    }
    fn release_opening(&self, index: usize, sequence: u64) {
        let displaced = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let Some(slot) = state.slots.get_mut(index) else {
                return;
            };
            let opening = match slot {
                Slot::Opening(opening) => Some(opening),
                Slot::Active { opening, .. } | Slot::Retiring { opening, .. } => opening.as_mut(),
                Slot::Empty => None,
            };
            let Some(opening) = opening else {
                return;
            };
            if opening.sequence != sequence || opening.holders == 0 {
                return;
            }
            opening.holders -= 1;
            if opening.holders != 0 {
                return;
            }
            match slot {
                Slot::Opening(_) => Some(std::mem::replace(slot, Slot::Empty)),
                Slot::Active { opening, .. } | Slot::Retiring { opening, .. } => {
                    *opening = None;
                    None
                }
                Slot::Empty => None,
            }
        };
        drop(displaced);
    }
    /// Close publication and capture all registered owners under the same
    /// bounded lock. Callers must abort/drop the returned owners after the
    /// lock is released; retirement must never skip a contended slot.
    pub fn close_and_snapshot(&self) -> [Option<ConnectionOwner>; CAPACITY] {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.closed = true;
        std::array::from_fn(|index| state.slots[index].owner())
    }
    #[cfg(all(test, unix))]
    pub fn lock_for_test(&self) -> impl Drop + '_ {
        self.state.lock().unwrap()
    }
    #[cfg(all(test, unix))]
    pub fn pause_next_registration(
        &self,
    ) -> (std::sync::mpsc::Receiver<()>, std::sync::mpsc::Sender<()>) {
        let (reached, wait) = std::sync::mpsc::channel();
        let (resume, release) = std::sync::mpsc::channel();
        let mut pause = self.registration_pause.lock().unwrap();
        assert!(pause.is_none());
        *pause = Some((reached, release));
        (wait, resume)
    }
    #[cfg(all(test, unix))]
    pub fn pause_next_release(
        &self,
    ) -> (std::sync::mpsc::Receiver<()>, std::sync::mpsc::Sender<()>) {
        let (reached, wait) = std::sync::mpsc::channel();
        let (resume, release) = std::sync::mpsc::channel();
        let mut pause = self.release_pause.lock().unwrap();
        assert!(pause.is_none());
        *pause = Some((reached, release));
        (wait, resume)
    }
    #[cfg(all(test, unix))]
    fn pause_release_for_test(&self) {
        let pause = self.release_pause.lock().unwrap().take();
        if let Some((reached, release)) = pause {
            let _ = reached.send(());
            let _ = release.recv_timeout(std::time::Duration::from_secs(20));
        }
    }
    #[cfg(all(test, unix))]
    pub fn pause_when_opening_empty(
        &self,
    ) -> (std::sync::mpsc::Receiver<()>, std::sync::mpsc::Sender<()>) {
        let (reached, wait) = std::sync::mpsc::channel();
        let (resume, release) = std::sync::mpsc::channel();
        let mut pause = self.empty_release_pause.lock().unwrap();
        assert!(pause.is_none());
        *pause = Some((reached, release));
        (wait, resume)
    }
    #[cfg(all(test, unix))]
    fn pause_empty_release_for_test(&self, index: usize) {
        let empty = {
            let state = self.state.lock().unwrap();
            state
                .slots
                .get(index)
                .is_some_and(|slot| !slot.has_opening())
        };
        if empty {
            let pause = self.empty_release_pause.lock().unwrap().take();
            if let Some((reached, release)) = pause {
                let _ = reached.send(());
                let _ = release.recv_timeout(std::time::Duration::from_secs(20));
            }
        }
    }
    #[cfg(feature = "development-read-witness")]
    pub fn sole_owner(&self) -> Result<Option<ConnectionOwner>, StreamError> {
        // Clone bounded original owners under the table lock, then release all
        // clones only outside it. There is no callback or destructor under the
        // registry lock, including the multiple-owner refusal path.
        let (owners, missing_opening): ([Option<ConnectionOwner>; CAPACITY], bool) = {
            let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            let owners = std::array::from_fn(|index| state.slots[index].owner());
            let missing = state
                .slots
                .iter()
                .zip(&owners)
                .any(|(slot, owner)| owner.is_none() && slot.has_opening());
            (owners, missing)
        };
        if missing_opening {
            return Ok(None);
        }
        let mut owners = owners.into_iter().flatten();
        let first = owners.next();
        if owners.next().is_some() {
            return Ok(None);
        }
        Ok(first)
    }
    fn retain(&self, owner: &Connection) -> bool {
        let displaced = {
            // No state lock is held by stop; this mutex encloses pointer
            // comparisons/Arc moves only, never callbacks or physical Drop.
            // Contention must wait, never silently skip retiring custody.
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let Some(slot) = state.slots.iter_mut().find(|slot| match slot {
                Slot::Active { weak, .. } => std::ptr::eq(weak.owner.as_ptr(), owner),
                Slot::Retiring { owner: current, .. } => std::ptr::eq(current.as_ptr(), owner),
                Slot::Empty | Slot::Opening(_) => false,
            }) else {
                return false;
            };
            match slot {
                Slot::Retiring { .. } => return true,
                Slot::Active { weak, opening } => {
                    let Some(current) = weak.upgrade() else {
                        return false;
                    };
                    let opening = *opening;
                    std::mem::replace(
                        slot,
                        Slot::Retiring {
                            owner: current,
                            opening,
                        },
                    )
                }
                Slot::Empty | Slot::Opening(_) => return false,
            }
        };
        drop(displaced);
        true
    }
    fn release(&self, owner: &Connection) {
        let displaced = {
            let Ok(mut state) = self.state.try_lock() else {
                return;
            };
            let Some(slot) = state.slots.iter_mut().find(|slot| {
                matches!(slot,
                Slot::Retiring { owner: current, .. } if std::ptr::eq(current.as_ptr(), owner))
            }) else {
                return;
            };
            let Slot::Retiring {
                owner: current,
                opening,
            } = slot
            else {
                return;
            };
            let weak = current.downgrade();
            let opening = *opening;
            std::mem::replace(slot, Slot::Active { weak, opening })
        };
        drop(displaced); // May destroy Connection/physical socket. No lock held.
    }
    fn detach_dead_weak(&self, index: usize, sequence: u64, pointer: *const Connection) {
        let detached = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.slots.get_mut(index).and_then(|slot| {
                let opening = match slot {
                    Slot::Active {
                        weak,
                        opening: Some(opening),
                    } if std::ptr::eq(weak.owner.as_ptr(), pointer)
                        && weak.owner.strong_count() == 0
                        && opening.sequence == sequence =>
                    {
                        *opening
                    }
                    _ => return None,
                };
                Some(std::mem::replace(slot, Slot::Opening(opening)))
            })
        };
        // The last destructor has returned. Its row remains Opening until
        // custody drops; retire weak/header/billing outside the table lock.
        drop(detached);
    }
}
impl RegistryWeak {
    pub fn retain(&self, owner: &Connection) -> bool {
        self.owner
            .upgrade()
            .is_some_and(|registry| registry.retain(owner))
    }
    pub fn release(&self, owner: &Connection) {
        if let Some(registry) = self.owner.upgrade() {
            registry.release(owner);
        }
    }
}
impl Drop for Registry {
    fn drop(&mut self) {
        // get_mut holds no MutexGuard. Remove every strong owner first, then
        // run their original Drop/quarantine outside any registry lock.
        let state = self
            .state
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let original = std::mem::replace(&mut state.slots, std::array::from_fn(|_| Slot::Empty));
        drop(original);
    }
}

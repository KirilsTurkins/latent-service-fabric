//! Bounded live namespace ownership, independent of native engine/file owners.
//! Every production lifecycle writer advances this fence at logical acceptance
//! and resolves it from the actual committed row before admitting new resources.
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc, Mutex, RwLock,
};

use latent_core::native_capacity::{NativeCapacityOwner, NativeReservation};

use super::{catalog::NamespaceRead, NamespaceError, NamespaceRecord, NamespaceStatus};

mod resident;
use resident::ResidentMetadata;

#[derive(Clone, Copy, Debug)]
pub struct NamespaceLifecycleLimits {
    pub namespaces: usize,
    pub owners: usize,
}
impl Default for NamespaceLifecycleLimits {
    fn default() -> Self {
        Self {
            namespaces: 4096,
            owners: 4096,
        }
    }
}
struct Owner {
    fence: RwLock<()>,
    live: AtomicBool,
    pins: AtomicUsize,
    maximum: usize,
    // LAST: every registry/handle/completion also drops its stamps before this
    // owner. The original native charge cannot retire ahead of actual metadata.
    resident: Option<ResidentMetadata>,
}
struct State {
    record: NamespaceRecord,
    epoch: u64,
    pending: Option<NamespaceRecord>,
}
struct Stamp {
    state: Mutex<State>,
    pins: AtomicUsize,
    #[cfg(test)]
    retirement_observer: Option<Arc<dyn Fn() + Send + Sync>>,
}

/// No engine Arc, file, background task or provider pool is retained here.
pub struct NamespaceLifecycleRegistry {
    entries: Mutex<Vec<Arc<Stamp>>>,
    maximum: usize,
    owner: Arc<Owner>,
}
impl NamespaceLifecycleRegistry {
    pub fn new(limits: NamespaceLifecycleLimits) -> Result<Self, NamespaceError> {
        Self::new_inner(limits, None)
    }

    /// Prepay resident lifecycle metadata before constructing the registry.
    /// The original Recovery reservation is retained by every actual handle
    /// and unresolved completion; it is physical ownership, not permission.
    pub fn with_retained_capacity(
        limits: NamespaceLifecycleLimits,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<Self, NamespaceError> {
        let resident = ResidentMetadata::new(limits, native, original)?;
        Self::new_inner(limits, Some(resident))
    }

    /// Finite native Work required by this metadata owner. It does not reserve
    /// capacity, publish a namespace or create a policy/lifecycle grant.
    pub fn retained_memory_bytes(limits: NamespaceLifecycleLimits) -> Result<u64, NamespaceError> {
        resident::memory_bytes(limits)
    }

    #[must_use]
    pub fn uses_native_capacity(&self, native: &NativeCapacityOwner) -> bool {
        self.owner
            .resident
            .as_ref()
            .is_some_and(|resident| resident.uses_native_capacity(native))
    }

    fn new_inner(
        limits: NamespaceLifecycleLimits,
        resident: Option<ResidentMetadata>,
    ) -> Result<Self, NamespaceError> {
        if limits.namespaces == 0
            || limits.namespaces > 4096
            || limits.owners == 0
            || limits.owners > 4096
        {
            return Err(NamespaceError::Invalid);
        }
        let mut entries = Vec::new();
        if resident.is_some() {
            entries
                .try_reserve_exact(limits.namespaces)
                .map_err(|_| NamespaceError::Capacity)?;
            if entries.capacity() > limits.namespaces {
                return Err(NamespaceError::Capacity);
            }
        }
        let registry = Self {
            owner: Arc::new(Owner {
                fence: RwLock::new(()),
                live: AtomicBool::new(true),
                pins: AtomicUsize::new(0),
                maximum: limits.owners,
                resident,
            }),
            entries: Mutex::new(entries),
            maximum: limits.namespaces,
        };
        if let Some(resident) = &registry.owner.resident {
            resident.check_live()?;
        }
        Ok(registry)
    }
    /// The record must be read by the configured protected-store worker. This
    /// owner provides lifecycle currentness only, never policy permission.
    pub fn pin(&self, read: &NamespaceRead) -> Result<NamespaceLifecycleHandle, NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_read()
            .map_err(|_| NamespaceError::Unavailable)?;
        self.check()?;
        let stamp = self.stamp(read.record())?;
        let state = stamp
            .state
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        if state.pending.is_some()
            || !same_lifecycle(&state.record, read.record())
            || state.record.status == NamespaceStatus::Tombstone
        {
            return Err(NamespaceError::PermissionDenied);
        }
        self.owner
            .pins
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                (value < self.owner.maximum).then_some(value + 1)
            })
            .map_err(|_| NamespaceError::Capacity)?;
        stamp.pins.fetch_add(1, Ordering::AcqRel);
        let epoch = state.epoch;
        drop(state);
        Ok(NamespaceLifecycleHandle {
            owner: Arc::clone(&self.owner),
            stamp,
            epoch,
        })
    }
    /// Reserve the bounded metadata slot ONLY after the actual writer has
    /// verified the missing namespace row. Creation stays closed until a fresh
    /// durable row resolves the returned completion.
    pub fn begin_create(
        &self,
        after: &NamespaceRecord,
    ) -> Result<NamespaceLifecycleCompletion, NamespaceError> {
        self.begin_create_with(after, || Ok(()))
    }
    /// Final short gate runs with the lifecycle bookkeeping locked, after every
    /// fallible lifecycle check and immediately before logical acceptance.
    /// Retain the returned guard through the metadata update; drop it before I/O.
    pub fn begin_create_with<R>(
        &self,
        after: &NamespaceRecord,
        accept: impl FnOnce() -> Result<R, NamespaceError>,
    ) -> Result<NamespaceLifecycleCompletion, NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_read()
            .map_err(|_| NamespaceError::Unavailable)?;
        self.check()?;
        after.validate()?;
        if after.version.incarnation != 1
            || after.version.generation != 1
            || after.status != NamespaceStatus::Active
            || !after.pins.is_empty()
        {
            return Err(NamespaceError::Invalid);
        }
        let mut entries = self
            .entries
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        for entry in entries.iter() {
            let state = entry
                .state
                .try_lock()
                .map_err(|_| NamespaceError::Unavailable)?;
            if state.record.tenant == after.tenant && state.record.id == after.id {
                return Err(NamespaceError::Conflict);
            }
        }
        if entries.len() >= self.maximum {
            return Err(NamespaceError::Capacity);
        }
        let accepted = accept()?;
        let epoch = 1;
        let stamp = Arc::new(Stamp {
            state: Mutex::new(State {
                record: after.clone(),
                epoch,
                pending: Some(after.clone()),
            }),
            pins: AtomicUsize::new(0),
            #[cfg(test)]
            retirement_observer: None,
        });
        entries.push(Arc::clone(&stamp));
        drop(accepted);
        Ok(NamespaceLifecycleCompletion {
            owner: Arc::clone(&self.owner),
            stamp,
            epoch,
        })
    }
    /// ONLY inside the actual writer's final current-policy callback, after
    /// namespace row CAS/pins/quota checks. Closing is before physical commit IO.
    /// The returned affine completion stays unresolved on uncertain durability.
    pub fn begin_transition(
        &self,
        before: &NamespaceRead,
        after: &NamespaceRecord,
        requires_drain: bool,
    ) -> Result<NamespaceLifecycleCompletion, NamespaceError> {
        self.begin_transition_with(before, after, requires_drain, || Ok(()))
    }
    /// The final no-I/O gate follows exact lifecycle and real owner checks.
    pub fn begin_transition_with<R>(
        &self,
        before: &NamespaceRead,
        after: &NamespaceRecord,
        requires_drain: bool,
        accept: impl FnOnce() -> Result<R, NamespaceError>,
    ) -> Result<NamespaceLifecycleCompletion, NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_read()
            .map_err(|_| NamespaceError::Unavailable)?;
        self.check()?;
        after.validate()?;
        if before.record().tenant != after.tenant
            || before.record().id != after.id
            || before.record().version.generation >= after.version.generation
        {
            return Err(NamespaceError::Conflict);
        }
        let stamp = self.stamp(before.record())?;
        let mut state = stamp
            .state
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        if state.pending.is_some() || !same_lifecycle(&state.record, before.record()) {
            return Err(NamespaceError::Conflict);
        }
        if requires_drain && stamp.pins.load(Ordering::Acquire) != 0 {
            return Err(NamespaceError::InUse);
        }
        let epoch = state.epoch.checked_add(1).ok_or(NamespaceError::Capacity)?;
        let accepted = accept()?;
        state.epoch = epoch;
        state.pending = Some(after.clone());
        drop(accepted);
        drop(state);
        Ok(NamespaceLifecycleCompletion {
            owner: Arc::clone(&self.owner),
            stamp,
            epoch,
        })
    }
    /// Bounded live pin count for readiness/drain reporting. It carries no grant.
    #[must_use]
    pub fn retained_owners(&self) -> usize {
        self.owner.pins.load(Ordering::Acquire)
    }

    /// Descriptive owner identity only. A matching handle still needs current
    /// policy and its own lifecycle fence before any resource is exposed.
    #[must_use]
    pub fn owns_handle(&self, handle: &NamespaceLifecycleHandle) -> bool {
        Arc::ptr_eq(&self.owner, &handle.owner)
    }

    /// Current metadata inspection also checks pending lifecycle acceptance.
    pub fn with_current_record<T>(
        &self,
        read: &NamespaceRead,
        action: impl FnOnce() -> Result<T, NamespaceError>,
    ) -> Result<T, NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_read()
            .map_err(|_| NamespaceError::Unavailable)?;
        self.check()?;
        let stamp = self.stamp(read.record())?;
        let state = stamp
            .state
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        if state.pending.is_some() || !same_lifecycle(&state.record, read.record()) {
            return Err(NamespaceError::PermissionDenied);
        }
        action()
    }

    pub fn retire(&self) -> Result<(), NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_write()
            .map_err(|_| NamespaceError::Unavailable)?;
        self.owner.live.store(false, Ordering::Release);
        Ok(())
    }
    fn check(&self) -> Result<(), NamespaceError> {
        if self.owner.live.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(NamespaceError::Unavailable)
        }
    }
    fn stamp(&self, record: &NamespaceRecord) -> Result<Arc<Stamp>, NamespaceError> {
        let mut entries = self
            .entries
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        for entry in entries.iter() {
            let state = entry
                .state
                .try_lock()
                .map_err(|_| NamespaceError::Unavailable)?;
            if state.record.tenant == record.tenant && state.record.id == record.id {
                return Ok(Arc::clone(entry));
            }
        }
        if entries.len() >= self.maximum {
            return Err(NamespaceError::Capacity);
        }
        record.validate()?;
        let stamp = Arc::new(Stamp {
            state: Mutex::new(State {
                record: record.clone(),
                epoch: record.version.generation,
                pending: None,
            }),
            pins: AtomicUsize::new(0),
            #[cfg(test)]
            retirement_observer: None,
        });
        entries.push(Arc::clone(&stamp));
        Ok(stamp)
    }
}

impl Drop for NamespaceLifecycleRegistry {
    fn drop(&mut self) {
        // Handles retain metadata only. Their owner cannot outlive the registry
        // as a usable grant, even if an activation is still being retired.
        self.owner.live.store(false, Ordering::Release);
    }
}

/// Actual activation/query/page ownership. Dropping a transport waiter must not
/// drop this while guest/accepted storage work still retains namespace resources.
pub struct NamespaceLifecycleHandle {
    stamp: Arc<Stamp>,
    epoch: u64,
    owner: Arc<Owner>,
}
impl NamespaceLifecycleHandle {
    /// Short no-I/O fence nested inside current policy/publication evaluation.
    pub fn with_current<T>(
        &self,
        read: &NamespaceRead,
        write: bool,
        action: impl FnOnce() -> Result<T, NamespaceError>,
    ) -> Result<T, NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_read()
            .map_err(|_| NamespaceError::Unavailable)?;
        if !self.owner.live.load(Ordering::Acquire) {
            return Err(NamespaceError::Unavailable);
        }
        let state = self
            .stamp
            .state
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        if state.epoch != self.epoch
            || state.pending.is_some()
            || !same_lifecycle(&state.record, read.record())
            || state.record.status == NamespaceStatus::Tombstone
            || (write && state.record.status != NamespaceStatus::Active)
        {
            return Err(NamespaceError::PermissionDenied);
        }
        action()
    }
}
impl Drop for NamespaceLifecycleHandle {
    fn drop(&mut self) {
        self.stamp.pins.fetch_sub(1, Ordering::AcqRel);
        self.owner.pins.fetch_sub(1, Ordering::AcqRel);
    }
}

/// No completion means fail closed. Resolve from a fresh native row only after
/// actual commit/recovery, never by fabricating a successful descriptor.
pub struct NamespaceLifecycleCompletion {
    stamp: Arc<Stamp>,
    epoch: u64,
    owner: Arc<Owner>,
}
impl NamespaceLifecycleCompletion {
    pub fn resolve(self, actual: &NamespaceRead) -> Result<(), NamespaceError> {
        let _fence = self
            .owner
            .fence
            .try_read()
            .map_err(|_| NamespaceError::Unavailable)?;
        if !self.owner.live.load(Ordering::Acquire) {
            return Err(NamespaceError::Unavailable);
        }
        let mut state = self
            .stamp
            .state
            .try_lock()
            .map_err(|_| NamespaceError::Unavailable)?;
        if state.epoch != self.epoch || state.pending.as_ref() != Some(actual.record()) {
            return Err(NamespaceError::Conflict);
        }
        state.record = actual.record().clone();
        state.pending = None;
        Ok(())
    }
}
fn same_lifecycle(a: &NamespaceRecord, b: &NamespaceRecord) -> bool {
    a.tenant == b.tenant
        && a.id == b.id
        && a.version.incarnation == b.version.incarnation
        && a.state_schema == b.state_schema
        && a.status == b.status
}

#[cfg(test)]
impl Drop for Stamp {
    fn drop(&mut self) {
        // The deterministic schedule observes actual final stamp destruction,
        // while its namespace record and pending record are still retained.
        if let Some(observer) = self.retirement_observer.take() {
            observer();
        }
    }
}

#[cfg(test)]
mod tests;

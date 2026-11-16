//! One prepaid table: active paid weak owners become retiring strong owners.
//! No destructor/callback runs while the registry mutex is held.
use crate::{connection::Connection, error, StreamError, StreamErrorCode};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use std::sync::{Arc, Mutex, Weak};

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

struct PaidWeak {
    owner: Weak<Connection>,
    // The SAME original connection charge, not another reservation. A dead
    // Weak still physically retains the Arc allocation until header retirement.
    _billing: Arc<ProviderMetadata>,
}
enum Slot {
    Empty,
    Active(PaidWeak),
    Retiring(Arc<Connection>),
}
impl Slot {
    fn owner(&self) -> Option<Arc<Connection>> {
        match self {
            Self::Empty => None,
            Self::Active(weak) => weak.owner.upgrade(),
            Self::Retiring(owner) => Some(Arc::clone(owner)),
        }
    }
    fn reusable(&self) -> bool {
        matches!(self, Self::Empty)
            || matches!(self, Self::Active(weak) if weak.owner.strong_count() == 0)
    }
}

pub(crate) struct Registry {
    state: Mutex<RegistryState>,
    #[cfg(all(test, unix))]
    registration_pause: Mutex<Option<(std::sync::mpsc::Sender<()>, std::sync::mpsc::Receiver<()>)>>,
    // Last field: actual table and Arc-owned connection refs drop first.
    billing: Arc<ProviderMetadata>,
}
struct RegistryState {
    closed: bool,
    slots: [Slot; CAPACITY],
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
        let bytes = arc_bytes::<Self>() + arc_bytes::<ProviderMetadata>();
        let billing = Arc::new(pools.reserve_protocol_metadata(bytes)?);
        Ok(Arc::new(Self {
            state: Mutex::new(RegistryState {
                closed: false,
                slots: std::array::from_fn(|_| Slot::Empty),
            }),
            #[cfg(all(test, unix))]
            registration_pause: Mutex::new(None),
            billing,
        }))
    }
    pub fn downgrade(self: &Arc<Self>) -> RegistryWeak {
        RegistryWeak {
            owner: Arc::downgrade(self),
            _billing: Arc::clone(&self.billing),
        }
    }
    pub fn register(&self, owner: &Arc<Connection>) -> Result<(), StreamError> {
        #[cfg(all(test, unix))]
        if let Some((reached, resume)) = self.registration_pause.lock().unwrap().take() {
            let _ = reached.send(());
            let _ = resume.recv_timeout(std::time::Duration::from_secs(20));
        }
        let weak = PaidWeak {
            owner: Arc::downgrade(owner),
            _billing: owner.metadata_billing(),
        };
        let displaced = {
            let mut state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            if state.closed {
                return Err(error(StreamErrorCode::Revoked));
            }
            let slot = state
                .slots
                .iter_mut()
                .find(|slot| slot.reusable())
                .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
            std::mem::replace(slot, Slot::Active(weak))
        };
        drop(displaced); // Last paid weak/header retirement is outside mutex.
        Ok(())
    }
    pub fn snapshot(&self, index: usize) -> Result<Option<Arc<Connection>>, StreamError> {
        let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
        Ok(state.slots.get(index).and_then(Slot::owner))
    }
    /// Close publication and capture all registered owners under the same
    /// bounded lock. Callers must abort/drop the returned owners after the
    /// lock is released; retirement must never skip a contended slot.
    pub fn close_and_snapshot(&self) -> [Option<Arc<Connection>>; CAPACITY] {
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
    #[cfg(feature = "development-read-witness")]
    pub fn sole_owner(&self) -> Result<Option<Arc<Connection>>, StreamError> {
        // Clone bounded original owners under the table lock, then release all
        // clones only outside it. There is no callback or destructor under the
        // registry lock, including the multiple-owner refusal path.
        let owners: [Option<Arc<Connection>>; CAPACITY] = {
            let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            std::array::from_fn(|index| state.slots[index].owner())
        };
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
                Slot::Active(weak) => std::ptr::eq(weak.owner.as_ptr(), owner),
                Slot::Retiring(current) => std::ptr::eq(current.as_ref(), owner),
                Slot::Empty => false,
            }) else {
                return false;
            };
            match slot {
                Slot::Retiring(_) => return true,
                Slot::Active(weak) => {
                    let Some(current) = weak.owner.upgrade() else {
                        return false;
                    };
                    std::mem::replace(slot, Slot::Retiring(current))
                }
                Slot::Empty => return false,
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
                Slot::Retiring(current) if std::ptr::eq(current.as_ref(), owner))
            }) else {
                return;
            };
            let Slot::Retiring(current) = slot else {
                return;
            };
            let weak = PaidWeak {
                owner: Arc::downgrade(current),
                _billing: current.metadata_billing(),
            };
            std::mem::replace(slot, Slot::Active(weak))
        };
        drop(displaced); // May destroy Connection/physical socket. No lock held.
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

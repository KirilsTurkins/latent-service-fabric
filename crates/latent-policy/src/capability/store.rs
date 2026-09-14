mod authority;
mod codec;
mod ledger;
mod model;
mod mutation;
mod ownership;
mod reads;
#[cfg(all(test, target_os = "linux"))]
mod tests;

use super::{invalid, unavailable, CapabilityPolicy, ProviderBinding};
pub use authority::{
    CallRestrictions, CapabilityPolicyRevision, EvaluationInput, Explanation, PolicySnapshot,
    PolicySnapshotState, SealedPolicyDecision,
};
use latent_artifacts::LifecycleAuthorityHandle;
use latent_core::PlatformError;
use model::Image;
pub use model::{MutationRequest, OperationReceipt, PolicyStoreLimits, RecordKind, RecordView};
use ownership::{Owner, Stamp};
pub use ownership::{PolicyRead, PolicyReadLease};
pub use reads::{PolicyPage, PolicyPageRequest};
use std::{
    path::Path,
    sync::{Arc, Mutex, MutexGuard},
    time::Instant,
};

pub(super) enum Compiled {
    Policy(CapabilityPolicy),
    Binding(Box<ProviderBinding>),
}
impl Compiled {
    fn parse(kind: RecordKind, tenant: &str, bytes: &[u8]) -> Result<Self, PlatformError> {
        let value = match kind {
            RecordKind::Policy => Self::Policy(CapabilityPolicy::parse(bytes)?),
            RecordKind::ProviderBinding => Self::Binding(Box::new(ProviderBinding::parse(bytes)?)),
        };
        let actual = match &value {
            Self::Policy(v) => v.tenant(),
            Self::Binding(v) => v.tenant(),
        };
        if actual != tenant {
            return Err(invalid());
        }
        Ok(value)
    }
    fn canonical(&self) -> &[u8] {
        match self {
            Self::Policy(v) => v.canonical(),
            Self::Binding(v) => v.canonical(),
        }
    }
    fn digest(&self) -> &str {
        match self {
            Self::Policy(v) => v.digest(),
            Self::Binding(v) => v.digest(),
        }
    }
}
struct Loaded {
    stamp: Arc<Stamp>,
    document: Option<Arc<Compiled>>,
}
struct State {
    ledger: ledger::Ledger,
    image: Image,
    loaded: Vec<Loaded>,
}

/// One configured node-owned store. Synchronous disk work belongs on the
/// existing bounded control runtime. Contention is prompt rejection (zero
/// internal queue), not a dedicated thread or waiter per policy.
pub struct PolicyStore {
    state: Mutex<State>,
    owner: Arc<Owner>,
    catalog: LifecycleAuthorityHandle,
    limits: PolicyStoreLimits,
    started: Instant,
}
impl PolicyStore {
    /// Bounded ownership for a redacted management inspection response. The
    /// caller must preflight its response before releasing the control job.
    pub fn reserve_inspection(&self) -> Result<PolicyReadLease, PlatformError> {
        self.owner.check()?;
        self.owner.lease()
    }
    pub fn open(
        path: &Path,
        limits: PolicyStoreLimits,
        catalog: LifecycleAuthorityHandle,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        let (ledger, image) = ledger::Ledger::open(path, limits)?;
        let loaded = image
            .records
            .iter()
            .map(|row| {
                Ok(Loaded {
                    stamp: Stamp::new(row.revision),
                    document: row
                        .document
                        .as_ref()
                        .map(|bytes| {
                            Compiled::parse(row.kind, &row.tenant, bytes.as_bytes()).map(Arc::new)
                        })
                        .transpose()?,
                })
            })
            .collect::<Result<Vec<_>, PlatformError>>()?;
        Ok(Self {
            state: Mutex::new(State {
                ledger,
                image,
                loaded,
            }),
            owner: Owner::new(limits.maximum_read_owners),
            catalog,
            limits,
            started: Instant::now(),
        })
    }
    #[must_use]
    pub fn catalog_owner_matches(&self, catalog: &LifecycleAuthorityHandle) -> bool {
        self.catalog.same_owner(catalog)
    }
    #[must_use]
    pub fn limits(&self) -> PolicyStoreLimits {
        self.limits
    }
    #[must_use]
    pub fn retained_read_owners(&self) -> usize {
        self.owner.readers()
    }
    pub fn retire(&self) {
        self.owner.retire();
    }
    fn lock(&self) -> Result<MutexGuard<'_, State>, PlatformError> {
        self.owner.check()?;
        let state = self.state.try_lock().map_err(|_| unavailable())?;
        self.owner.check()?;
        Ok(state)
    }
}
impl Drop for PolicyStore {
    fn drop(&mut self) {
        self.owner.retire();
    }
}

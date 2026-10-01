//! One fixed node dispatcher. Durable backlog stays indexed in the shared store;
//! accepted provider work and buffers remain owned until actual cleanup.

mod adapter;
mod admission;
mod config;
pub mod control;
mod driver;
mod owner;
mod reconciliation;
mod state;
mod store;
mod worker;

pub use adapter::{AdapterOutcome, DeferredEffectAdapter, EffectTimeSource};
pub use admission::{CommandAdmission, CommandAdmissionSource};
pub use config::{DispatchOrdering, DispatcherConfig};
pub use control::{
    DispatcherControlAction, DispatcherControlError, DispatcherControlGeneration,
    DispatcherControlJob, DispatcherControlLookup, DispatcherControlOutcome,
    DispatcherControlReceipt, DispatcherControlRequest, DispatcherControlSnapshot,
    PreparedDispatcherControl,
};
pub use owner::DispatcherOwner;
pub use reconciliation::{
    ProviderConfirmation, ProviderReconciliationOutcome, ProviderReconciliationReason,
    ProviderReconciliationRequest,
};
pub use state::{DispatcherShutdown, DispatcherSnapshot};
pub use store::{RequiredProfilePage, RequiredProfileRow};

use crate::authority::AuthorityError;
use crate::dispatch_store::DispatchStoreError;
use latent_state::protected_store::ProtectedStoreError;
use latent_state::store_io::StoreIoError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatcherError {
    InvalidConfiguration,
    UnsupportedOrdering,
    InvalidAdapter,
    CheckpointRequired,
    AdmissionClosed,
    Authority(AuthorityError),
    Store(DispatchStoreError),
    ProtectedStore(ProtectedStoreError),
    Worker(StoreIoError),
}

impl From<AuthorityError> for DispatcherError {
    fn from(error: AuthorityError) -> Self {
        Self::Authority(error)
    }
}
impl From<DispatchStoreError> for DispatcherError {
    fn from(error: DispatchStoreError) -> Self {
        Self::Store(error)
    }
}
impl From<ProtectedStoreError> for DispatcherError {
    fn from(error: ProtectedStoreError) -> Self {
        Self::ProtectedStore(error)
    }
}
impl From<StoreIoError> for DispatcherError {
    fn from(error: StoreIoError) -> Self {
        Self::Worker(error)
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

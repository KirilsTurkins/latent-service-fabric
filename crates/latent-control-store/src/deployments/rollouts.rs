//! Semantic rollout transitions committed through the deployment publication.
pub(crate) mod canary;
mod commit;
mod comparison;
mod prepare;
mod reads;
mod rollback;
pub(super) mod table;
use super::{CompiledCatalog, PublicationView};
use crate::rollouts::{capacity, Result, RolloutOperationReceipt};
use latent_core::ArtifactBlobDigest;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
pub struct PreparedRolloutMutation {
    owner: Arc<AtomicBool>,
    previous: PublicationView,
    next_routes: Arc<CompiledCatalog>,
    next_table: Arc<table::RolloutTable>,
    bytes: Vec<u8>,
    receipt: RolloutOperationReceipt,
    request_digest: ArtifactBlobDigest,
    replayed: bool,
    state_only: bool,
    canary_proof: Option<latent_telemetry::phase2_canary::SealedCanaryWindow>,
    _work: WorkReservation,
}
impl PreparedRolloutMutation {
    #[must_use]
    pub fn preview(&self) -> &RolloutOperationReceipt {
        &self.receipt
    }
    #[must_use]
    pub fn replayed(&self) -> bool {
        self.replayed
    }
}
struct WorkReservation(Arc<AtomicBool>);
impl WorkReservation {
    fn acquire(owner: &Arc<AtomicBool>) -> Result<Self> {
        owner
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| capacity())?;
        Ok(Self(Arc::clone(owner)))
    }
}
impl Drop for WorkReservation {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

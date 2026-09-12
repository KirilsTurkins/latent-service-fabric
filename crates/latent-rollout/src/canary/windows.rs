use crate::{coordinator::Shared, Result, RolloutObservation, RolloutObservationState};
use latent_control_store::{
    rollouts::{RolloutCanaryCohort, RolloutId, RolloutOperationReceipt, RolloutState},
    DirectoryDeploymentRepository,
};
use latent_core::TenantId;
use latent_telemetry::CanaryWindow;
use std::sync::{atomic::Ordering, Arc};

const MAXIMUM_COHORT_BYTES: usize = 8192;
pub(super) struct Observed {
    pub cohort: RolloutCanaryCohort,
    pub window: CanaryWindow,
}
/// Only the existing control worker mutates these slots. Invocation sees the
/// telemetry capture owner, never this table or a coordinator lock.
pub(crate) struct ObservationWindows {
    entries: Vec<Observed>,
    maximum: usize,
    shared: Arc<Shared>,
}
impl ObservationWindows {
    pub(crate) fn new(repository: &DirectoryDeploymentRepository, shared: Arc<Shared>) -> Self {
        let maximum = repository
            .canary_hub()
            .map_or(0, |hub| hub.config().maximum_series);
        let result = Self {
            entries: Vec::with_capacity(maximum),
            maximum,
            shared,
        };
        result.publish();
        result
    }
    fn publish(&self) {
        self.shared
            .canary_windows
            .store(self.entries.len(), Ordering::Release);
        let bytes = self.entries.capacity() * std::mem::size_of::<Observed>()
            + self
                .entries
                .iter()
                .map(|entry| entry.cohort.retained_bytes())
                .sum::<usize>();
        self.shared.canary_bytes.store(bytes, Ordering::Release);
    }
    pub(crate) fn remove(&mut self, tenant: &TenantId, id: &RolloutId) {
        self.entries.retain(|entry| {
            let identity = &entry.cohort.window_spec().identity;
            identity.tenant != *tenant || identity.rollout_id != id.0
        });
        self.publish();
    }
    pub(super) fn ensure(
        &mut self,
        repository: &DirectoryDeploymentRepository,
        cohort: RolloutCanaryCohort,
    ) -> Result<&Observed> {
        if cohort.retained_bytes() > MAXIMUM_COHORT_BYTES {
            return Err(crate::capacity("rollout-canary-metadata-limit"));
        }
        let spec = cohort.window_spec();
        if let Some(index) = self.entries.iter().position(|entry| {
            let old = entry.cohort.window_spec();
            old.identity == spec.identity
                && old.control_digest == spec.control_digest
                && old.revisions == spec.revisions
                && old.duration == spec.duration
                && entry.cohort.revision() == cohort.revision()
        }) {
            return Ok(&self.entries[index]);
        }
        self.remove(
            &spec.identity.tenant,
            &RolloutId(spec.identity.rollout_id.clone()),
        );
        let hub = repository.canary_hub().ok_or_else(unavailable)?;
        if self.entries.len() >= self.maximum {
            return Err(crate::capacity("rollout-canary-window-limit"));
        }
        let window = hub.register(spec)?;
        self.entries.push(Observed { cohort, window });
        self.publish();
        Ok(self.entries.last().expect("inserted bounded observation"))
    }
    pub(crate) fn after_mutation(
        &mut self,
        repository: &DirectoryDeploymentRepository,
        receipt: &RolloutOperationReceipt,
        replayed: bool,
    ) -> Option<RolloutObservation> {
        let Ok(Some(status)) = repository.get_rollout(&receipt.tenant, &receipt.rollout_id) else {
            return Some(RolloutObservation::unavailable());
        };
        status.canary_policy?;
        // Replaying an old command never opens a new window on a newer stage.
        if status.revision != receipt.revision {
            return Some(RolloutObservation::unavailable());
        }
        if status.state != RolloutState::Running {
            self.remove(&receipt.tenant, &receipt.rollout_id);
            return Some(RolloutObservation {
                state: RolloutObservationState::Retired,
                window_epoch: None,
            });
        }
        if replayed {
            let Ok(current) = repository.rollout_canary_cohort(
                &receipt.tenant,
                &receipt.rollout_id,
                receipt.revision,
            ) else {
                return Some(RolloutObservation::unavailable());
            };
            let existing = self.entries.iter().find(|entry| {
                let id = &entry.cohort.window_spec().identity;
                id.tenant == receipt.tenant
                    && id.rollout_id == receipt.rollout_id.0
                    && entry.cohort.revision() == receipt.revision
                    && entry.cohort.window_spec().identity == current.window_spec().identity
                    && entry.cohort.window_spec().control_digest
                        == current.window_spec().control_digest
            });
            return Some(
                existing
                    .and_then(|entry| observation(entry).ok())
                    .unwrap_or_else(RolloutObservation::unavailable),
            );
        }
        let result = repository
            .rollout_canary_cohort(&receipt.tenant, &receipt.rollout_id, receipt.revision)
            .and_then(|cohort| self.ensure(repository, cohort))
            .and_then(observation);
        Some(result.unwrap_or_else(|_| RolloutObservation::unavailable()))
    }
}
impl Drop for ObservationWindows {
    fn drop(&mut self) {
        drop(std::mem::take(&mut self.entries));
        self.shared.canary_windows.store(0, Ordering::Release);
        self.shared.canary_bytes.store(0, Ordering::Release);
    }
}
pub(super) fn observation(entry: &Observed) -> Result<RolloutObservation> {
    let snapshot = entry.window.snapshot(1)?;
    Ok(RolloutObservation {
        state: if snapshot.elapsed() < snapshot.duration() {
            RolloutObservationState::Collecting
        } else {
            RolloutObservationState::AwaitingEvaluation
        },
        window_epoch: Some(snapshot.epoch()),
    })
}
pub(super) fn unavailable() -> latent_core::PlatformError {
    crate::error(
        latent_core::PlatformErrorCode::Unavailable,
        "rollout-canary-unavailable",
    )
}

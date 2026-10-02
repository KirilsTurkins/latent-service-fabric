use super::plan::Plan;
use crate::atomic::{
    command_identity,
    writer::{fenced_error, Usage},
    AtomicError, MaintenanceClock, MaintenanceProgress, ResultMaintenanceOwner,
};
use latent_core::{transaction_contract::CommandKey, StateNamespaceId, TenantId};
use latent_state::embedded::EmbeddedStore;

impl ResultMaintenanceOwner {
    /// Install an explicitly authorized clock observation in the namespace's
    /// already charged quota row. This needs no new physical row or reservation
    /// and never expires a result, terminalizes an effect or resumes history.
    /// Re-anchoring after a boot requires fresh host proof and current policy.
    pub fn anchor_review(
        &self,
        store: &EmbeddedStore,
        key: &CommandKey,
        expected_generation: Option<u64>,
        clock: MaintenanceClock,
        mut authorize: impl FnMut(&CommandKey) -> Result<(), AtomicError>,
    ) -> Result<MaintenanceProgress, AtomicError> {
        let _physical_step = self.enter()?;
        authorize(key)?;
        command_identity(key)?;
        clock.validate()?;
        let view = store.snapshot()?;
        let mut plan = Plan::default();
        for row in latent_state::recovery::maintenance::namespace_expectations(
            &view,
            &TenantId(key.tenant.clone()),
            &StateNamespaceId(key.namespace.clone()),
            crate::atomic::incarnation(key)?,
        )? {
            plan.expect(row)?;
        }
        let (mut usage, usage_key, old) = Usage::read(&view, key)?;
        if old.is_none() || !usage.accounted {
            return Err(AtomicError::UnsupportedFormat);
        }
        if usage.review_clock.as_ref().map(|p| p.generation) != expected_generation {
            return Err(AtomicError::Conflict);
        }
        let generation = usage.review_clock.as_ref().map_or(Ok(1), |previous| {
            clock.time.check(previous.unix_millis)?;
            previous.generation.checked_add(1).ok_or(AtomicError::Limit)
        })?;
        let mut progress = MaintenanceProgress::anchor(clock, generation);
        if let Some(previous) = usage.review_clock.take() {
            progress.visited = previous.visited;
            progress.retired = previous.retired;
            progress.reclaimed_bytes = previous.reclaimed_bytes;
        }
        usage.review_clock = Some(progress.clone());
        plan.replace(usage_key, old, Some(usage.encode()?))?;
        drop(view);
        store
            .apply_fenced(plan.batch, || authorize(key))
            .map_err(fenced_error)?;
        Ok(progress)
    }
}

use super::plan::Plan;
use crate::atomic::{
    command_identity,
    writer::{fenced_error, Usage},
    AtomicError, MaintenanceClock, MaintenanceProgress, ResultMaintenanceOwner,
};
use latent_core::{transaction_contract::CommandKey, StateNamespaceId, TenantId};
use latent_state::embedded::{EmbeddedStore, ExpectedRow};

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
        let previous = usage.review_clock.take();
        let progress = if previous.is_some() {
            MaintenanceProgress::reanchor(clock, generation, previous)?
        } else {
            // A first namespace anchor must not bypass an already installed
            // global same-boot reference. Fence even its absence so a global
            // anchor cannot appear between this observation and acceptance.
            let global_key = MaintenanceProgress::key();
            let global_bytes =
                view.get_bounded(&global_key, super::super::clock::PROGRESS_BYTES)?;
            let global = global_bytes
                .as_deref()
                .map(MaintenanceProgress::decode)
                .transpose()?;
            if let Some(global) = &global {
                clock.time.check(global.unix_millis)?;
            }
            plan.expect(ExpectedRow {
                key: global_key,
                value: global_bytes,
            })?;
            let mut progress = MaintenanceProgress::reanchor(clock, generation, global)?;
            progress.visited = 0;
            progress.retired = 0;
            progress.reclaimed_bytes = 0;
            progress
        };
        usage.review_clock = Some(progress.clone());
        plan.replace(usage_key, old, Some(usage.encode()?))?;
        drop(view);
        store
            .apply_fenced(plan.batch, || authorize(key))
            .map_err(fenced_error)?;
        Ok(progress)
    }
}

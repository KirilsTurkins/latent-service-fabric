//! Explicit destructive release, one original effect or attempt per callback.
mod attempt;
mod effect;

use super::{
    operation::Captured, plan, RetentionAction, RetentionAudit, RetentionProgress, RetentionRequest,
};
use crate::atomic::{
    writer::{fenced_error, Usage},
    AtomicError, MaintenanceClock, ResultMaintenanceOwner,
};
use latent_state::{embedded::EmbeddedStore, namespace::namespace_record_key};

impl ResultMaintenanceOwner {
    /// The earlier terminalization review has already stopped future sends.
    /// Purge needs a separate current destructive-policy check, the original
    /// retention horizon, no active claim, and physically retired native views.
    /// Interrupted progress remains in the same audited envelope after reopen.
    pub fn purge(
        &self,
        store: &EmbeddedStore,
        request: &RetentionRequest,
        clock: MaintenanceClock,
        mut authorize: impl FnMut(
            RetentionAction,
            &RetentionRequest,
            Option<&crate::atomic::CommandRecord>,
        ) -> Result<(), AtomicError>,
    ) -> Result<RetentionProgress, AtomicError> {
        let _physical_step = self.enter()?;
        authorize(RetentionAction::Purge, request, None)?;
        let view = store.snapshot()?;
        let (progress, progress_fence) = plan::progress(&view, &request.key, clock)?;
        let mut captured = Captured::read(&view, request)?;
        if let Some(fence) = progress_fence {
            captured.plan.expect(fence)?;
        }
        authorize(RetentionAction::Purge, request, Some(&captured.record))?;
        clock.time.check(captured.record.clock_floor)?;
        let mut audit = captured
            .audit
            .clone()
            .ok_or(AtomicError::RecoveryRequired)?;
        if audit.terminalized != audit.effect_count {
            return Err(AtomicError::RecoveryRequired);
        }
        if clock.time.unix_millis < audit.retain_until {
            return Err(AtomicError::Expired);
        }
        audit.purging = true;
        let (mut usage, usage_key, usage_bytes) = Usage::read(&view, &captured.record.key)?;
        if !usage.accounted {
            return Err(AtomicError::UnsupportedFormat);
        }
        let (reclaimed, complete) = if audit.purged < audit.effect_count {
            (
                effect::one(&view, &mut captured, &mut audit, &mut usage)?,
                false,
            )
        } else if audit.purged_attempts + 1 < captured.record.attempt {
            (
                attempt::prior(&view, &mut captured, &mut audit, &mut usage)?,
                false,
            )
        } else {
            (
                attempt::finish(&view, &mut captured, &audit, &mut usage, clock)?,
                true,
            )
        };
        if !complete {
            update_audit(&mut captured, &audit, &mut usage)?;
        }
        plan::advance(&mut usage, progress, clock, reclaimed, complete)?;
        captured.namespace.version.generation = captured
            .namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        usage.check(&captured.namespace)?;
        captured
            .plan
            .replace(usage_key, usage_bytes, Some(usage.encode()?))?;
        let key = latent_state::embedded::RowKey {
            family: latent_state::embedded::Family::Namespace,
            key: namespace_record_key(&captured.namespace.tenant, &captured.namespace.id)
                .map_err(|_| AtomicError::Corrupt)?,
        };
        captured.plan.mutation(
            key,
            Some(
                captured
                    .namespace
                    .encode()
                    .map_err(|_| AtomicError::Invalid)?,
            ),
        )?;
        let mut result = audit.progress(&captured.record, RetentionAction::Purge);
        result.complete = complete;
        if complete {
            result.purged_attempts = captured.record.attempt;
        }
        drop(view);
        store
            .apply_reclamation_fenced(captured.plan.batch, || {
                authorize(RetentionAction::Purge, request, None)?;
                authorize(RetentionAction::Purge, request, Some(&captured.record))
            })
            .map_err(fenced_error)?;
        Ok(result)
    }
}

fn update_audit(
    captured: &mut Captured,
    audit: &RetentionAudit,
    usage: &mut Usage,
) -> Result<(), AtomicError> {
    let old = captured.audit_bytes.as_ref().ok_or(AtomicError::Corrupt)?;
    let new = audit.encode()?;
    usage.result_bytes = usage
        .result_bytes
        .checked_sub(old.len() as u64 * 2)
        .and_then(|value| value.checked_add(new.len() as u64 * 2))
        .ok_or(AtomicError::Corrupt)?;
    captured.publish_audit(audit)
}

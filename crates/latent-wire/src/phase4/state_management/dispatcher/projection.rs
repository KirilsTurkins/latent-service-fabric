use super::{c, native_error, unsupported, PlatformError};
use latent_effects::runtime::{
    DispatcherControlAction, DispatcherControlGeneration, DispatcherControlReceipt,
    DispatcherSnapshot,
};
fn generation(value: DispatcherControlGeneration) -> c::DispatcherGeneration {
    c::DispatcherGeneration {
        owner_epoch: value.owner_epoch(),
        revision: value.revision(),
    }
}
pub(super) fn receipt(
    value: &DispatcherControlReceipt,
) -> Result<c::DispatcherOperationReceipt, PlatformError> {
    let original = value.request();
    Ok(c::DispatcherOperationReceipt {
        operation_id: original.operation_id().into(),
        receipt_id: format!(
            "sha256:{}",
            super::super::response::hex(&value.digest().map_err(|v| native_error(v.into()))?)
        ),
        action: match original.action() {
            DispatcherControlAction::Pause => c::DispatcherAction::Pause,
            DispatcherControlAction::Resume => c::DispatcherAction::Resume,
        } as i32,
        authenticated_operator: original.actor_subject().into(),
        actor_tenant: original.actor_tenant().into(),
        before_generation: Some(generation(original.expected())),
        after_generation: Some(generation(value.generation())),
        observed_at_unix_millis: value.observed_at_millis(),
        clock_continuity_proven: value.clock_continuity_proven(),
        restore_review_required: value.restore_review(),
        disposition: c::StateOperationDisposition::Committed as i32,
    })
}
pub(super) fn snapshot(
    value: &DispatcherSnapshot,
    clock_continuity_proven: bool,
) -> Result<c::DispatcherSnapshot, PlatformError> {
    let failure = match value.failure {
        None => c::DispatcherFailure::None,
        Some("effect-authority") => c::DispatcherFailure::Authority,
        Some("shared-store") => c::DispatcherFailure::Store,
        Some("physical-worker") => c::DispatcherFailure::Worker,
        Some("restore-checkpoint-required") => c::DispatcherFailure::RestoreCheckpoint,
        Some("admission-closed") => c::DispatcherFailure::AdmissionClosed,
        Some("configuration") => c::DispatcherFailure::Configuration,
        _ => return Err(unsupported()),
    };
    Ok(c::DispatcherSnapshot {
        generation: Some(generation(value.control.generation)),
        paused: value.paused,
        pending_control: value.control.pending,
        restore_review_required: value.control.restore_review_required,
        admission_closed: value.admission_closed,
        quarantined: value.quarantined,
        failure: failure as i32,
        queued: value.queued as u64,
        active_jobs: value.active_jobs as u64,
        retained_attempt_bytes: value.retained_attempt_bytes,
        live_workers: value.live_workers as u64,
        accepted_effects: value.accepted_effects as u64,
        physical_owners: value.physical_owners as u64,
        quarantined_physical_owners: value.quarantined_physical_owners as u64,
        command_owners: value.command_owners as u64,
        claims: value.claims,
        pending_effects: value.durable.pending,
        uncertain_effects: value.durable.uncertain,
        blocked_effects: value.durable.blocked,
        dead_letter_effects: value.durable.dead_lettered,
        counts_observed_at_unix_millis: value.counts_observed_at_millis,
        clock_continuity_proven,
    })
}

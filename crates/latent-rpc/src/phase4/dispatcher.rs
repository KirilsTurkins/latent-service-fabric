//! Node-control shape/association only; these descriptions create no grants.
use super::{
    bounds::{required, Budget},
    request, ValidationError,
};
use crate::control::v1 as c;

fn scope(value: i32) -> Result<(), ValidationError> {
    if value == c::DispatcherScope::Node as i32 {
        Ok(())
    } else {
        Err(ValidationError::Shape)
    }
}
fn generation(value: &c::DispatcherGeneration) -> Result<(), ValidationError> {
    if value.owner_epoch == 0 || value.revision == 0 {
        Err(ValidationError::Shape)
    } else {
        Ok(())
    }
}
pub(super) fn inspect(
    b: &mut Budget,
    value: &c::InspectDispatcherRequest,
) -> Result<(), ValidationError> {
    request::profile(b, required(value.profile.as_ref())?)?;
    scope(value.scope)
}
pub(super) fn control(
    b: &mut Budget,
    value: &c::ControlDispatcherRequest,
) -> Result<(), ValidationError> {
    request::profile(b, required(value.profile.as_ref())?)?;
    scope(value.scope)?;
    b.id(&value.operation_id)?;
    let expected = required(value.expected_generation.as_ref())?;
    generation(expected)?;
    expected
        .revision
        .checked_add(1)
        .ok_or(ValidationError::Shape)?;
    match c::DispatcherAction::try_from(value.action) {
        Ok(c::DispatcherAction::Pause | c::DispatcherAction::Resume) => Ok(()),
        _ => Err(ValidationError::Shape),
    }
}
pub(super) fn snapshot(
    _b: &mut Budget,
    value: &c::DispatcherSnapshot,
) -> Result<(), ValidationError> {
    generation(required(value.generation.as_ref())?)?;
    match c::DispatcherFailure::try_from(value.failure) {
        Ok(
            c::DispatcherFailure::None
            | c::DispatcherFailure::Authority
            | c::DispatcherFailure::Store
            | c::DispatcherFailure::Worker
            | c::DispatcherFailure::RestoreCheckpoint
            | c::DispatcherFailure::AdmissionClosed
            | c::DispatcherFailure::Configuration,
        ) => {}
        _ => return Err(ValidationError::Shape),
    }
    if (value.pending_control || value.restore_review_required) && !value.paused {
        return Err(ValidationError::Shape);
    }
    Ok(())
}
pub(super) fn receipt(
    b: &mut Budget,
    value: &c::DispatcherOperationReceipt,
    original: &c::ControlDispatcherRequest,
) -> Result<(), ValidationError> {
    match c::DispatcherAction::try_from(value.action) {
        Ok(c::DispatcherAction::Pause | c::DispatcherAction::Resume) => {}
        _ => return Err(ValidationError::Shape),
    }
    b.id(&value.operation_id)?;
    b.id(&value.receipt_id)?;
    b.id(&value.authenticated_operator)?;
    b.id(&value.actor_tenant)?;
    let before = required(value.before_generation.as_ref())?;
    let after = required(value.after_generation.as_ref())?;
    generation(before)?;
    generation(after)?;
    if value.operation_id != original.operation_id
        || value.action != original.action
        || Some(before) != original.expected_generation.as_ref()
        || after.owner_epoch != before.owner_epoch
        || before.revision.checked_add(1) != Some(after.revision)
    {
        return Err(ValidationError::Association);
    }
    if value.disposition != c::StateOperationDisposition::Committed as i32
        || (value.action == c::DispatcherAction::Resume as i32
            && (!value.clock_continuity_proven || value.restore_review_required))
    {
        return Err(ValidationError::Shape);
    }
    Ok(())
}

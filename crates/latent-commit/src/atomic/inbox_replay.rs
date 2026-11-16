//! Read-only recovery tied to the original authenticated input and source row.
use super::{
    inspect, verify_inbox_scope, AtomicError, CommandAccess, CommandRecord, CommandTime,
    DurableResult, InboxIdentity,
};
use latent_core::transaction_contract::CommandKey;
use latent_state::{embedded::ReadView, inbox_scope::InboxScope};

/// Recover an inbox command only while its exact approved source remains in
/// the same coherent view. Authorization precedes source observation, including
/// absent commands. A matching source alone grants no result-read permission.
///
/// Pending and expired-body records retain the same source fence as a full
/// result. Missing source history is never approval to install a source, retry
/// an attempt or execute a guest. The caller retains the original native view,
/// reservation and deadline; this operation creates none of those owners.
pub fn inspect_inbox(
    view: &ReadView,
    key: &CommandKey,
    inbox: &InboxIdentity,
    scope: &InboxScope,
    time: CommandTime,
    mut authorize: impl FnMut(CommandAccess, Option<&CommandRecord>) -> Result<(), AtomicError>,
) -> Result<(CommandRecord, Option<DurableResult>), AtomicError> {
    let result = inspect(view, key, time, |access, record| {
        authorize(access, record)?;
        verify_inbox_scope(view, key, inbox, scope)?;
        if record.is_some_and(|record| record.inbox_identity() != Some(inbox)) {
            return Err(AtomicError::Conflict);
        }
        Ok(())
    });
    // In particular, inspect may return Pending or an expired body without a
    // final payload read. Neither a positive reply nor absence may outlive the
    // original coherent view after authorization and source validation.
    if result.is_ok() || matches!(&result, Err(AtomicError::NotFound)) {
        let _ = view.is_empty()?;
    }
    result
}

//! An old abort proves only its original history. After older-history restore,
//! a later retry or completion may have disappeared from the retained rows.
//! The old proof therefore cannot admit a new attempt in a different history.

use crate::atomic::{record::record_scope, AtomicError, CommandRecord};
use latent_state::{
    embedded::ReadView,
    session::version::{capture_view, CapturedView, ViewIdentity},
};

pub(super) fn capture(
    view: &ReadView,
    original: &CommandRecord,
) -> Result<CapturedView, AtomicError> {
    let scope = record_scope(original)?;
    let original_token = original
        .committed_view_token()
        .ok_or(AtomicError::Corrupt)?;
    let before =
        ViewIdentity::from_token(&scope, original_token).map_err(|_| AtomicError::Corrupt)?;
    let current = capture_view(view, &scope)?;
    if before.epochs != current.identity().epochs {
        return Err(AtomicError::RecoveryRequired);
    }
    // Namespace generation may have advanced after the proven abort. The
    // original fingerprint and user expected versions still govern the retry;
    // neither this observation nor the writer refreshes those preconditions.
    Ok(current)
}

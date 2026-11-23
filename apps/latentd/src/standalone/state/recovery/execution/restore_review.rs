//! Approve exactly the operator-reviewed restored window on the paused view.
use super::{digest, Codecs};
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, StoreError},
    namespace::{
        compatibility::RetainedInventory,
        history::{history_key, HistoryStatus},
        namespace_record_key, NamespaceStatus,
    },
    recovery::{namespace_resume::NamespaceRecoveryView, RecoveryGuard, RecoveryStatus},
};

pub(super) struct PreparedReview {
    pub batch: AtomicBatch,
    pub report: serde_json::Value,
}

pub(super) fn status(guard: &RecoveryGuard) -> serde_json::Value {
    let status = match guard.status() {
        RecoveryStatus::Staging => "staging",
        RecoveryStatus::ReconciliationRequired => "reconciliation-required",
        RecoveryStatus::ReviewAccepted => "review-accepted",
    };
    serde_json::json!({
        "status": status,
        "restoreOperationDigest": digest(guard.operation_digest()),
        "snapshotDigest": digest(guard.snapshot_digest()),
        "windowDigest": digest(guard.window_digest()),
        "acceptedReviewDigest": (guard.status() == RecoveryStatus::ReviewAccepted)
            .then(|| digest(guard.review_digest())),
    })
}

pub(super) fn prepare(
    view: &ReadView,
    codecs: &Codecs,
    observed: &NamespaceRecoveryView,
    inventory: &RetainedInventory,
    expected_view: &[u8],
    snapshot: &str,
    acknowledged_window: &str,
) -> Result<PreparedReview, StoreError> {
    let snapshot = super::super::assets::digest_bytes(snapshot).map_err(|_| StoreError::Invalid)?;
    let window =
        super::super::assets::digest_bytes(acknowledged_window).map_err(|_| StoreError::Invalid)?;
    let guard = observed.guard.as_ref().ok_or(StoreError::Unavailable)?;
    if observed.namespace.status != NamespaceStatus::Quiescing
        || observed.history.status != HistoryStatus::ReconciliationRequired
        || guard.snapshot_digest() != snapshot
        || guard.window_digest() != window
        || observed.view_token()? != expected_view
    {
        return Err(StoreError::Conflict);
    }
    let replay = guard.status() == RecoveryStatus::ReviewAccepted;
    let batch = if replay {
        if guard.review_digest() != codecs.review {
            return Err(StoreError::Conflict);
        }
        AtomicBatch::default()
    } else {
        inventory
            .require_retirement_drained()
            .map_err(|_| StoreError::Unavailable)?;
        let mut batch = guard.prepare_reviewed(view, codecs.review, |_, _, _| codecs.check())?;
        let namespace = &observed.namespace;
        let record = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&namespace.tenant, &namespace.id)
                .map_err(|_| StoreError::Corrupt)?,
        };
        let history = history_key(
            &namespace.tenant,
            &namespace.id,
            namespace.version.incarnation,
        )
        .map_err(|_| StoreError::Corrupt)?;
        for key in [record, history] {
            batch.expectations.push(ExpectedRow {
                value: Some(view.get(&key)?.ok_or(StoreError::Corrupt)?),
                key,
            });
        }
        batch
    };
    Ok(PreparedReview {
        batch,
        report: serde_json::json!({
            "action":"review",
            "restoreOperationDigest": digest(guard.operation_digest()),
            "snapshotDigest": digest(snapshot),
            "windowDigest": digest(window),
            "reviewDigest": digest(codecs.review),
            "replay": replay,
        }),
    })
}

//! Original immutable input review before Root-owned fresh restore staging.
//! This composes the actual whole-unit reader and never imports control rows.

use super::{
    checkpoint, review_snapshot, RecoveryReview, RecoveryReviewError, RecoveryReviewOwners,
    RecoveryReviewRequest,
};
use latent_state::{
    embedded::{ReadView, StoreError},
    recovery::{
        restore::RestoreWindow,
        snapshot::{RequiredArtifact, SnapshotError, SnapshotReceipt},
    },
};
use sha2::{Digest, Sha256};

/// Immutable attributed operation data. The authenticated host supplies actor,
/// exact original IDs and preconditions; these descriptions grant no access.
#[derive(Debug)]
pub struct RestoreInputRequest {
    pub operation_id: String,
    pub operator_id: String,
    pub snapshot_digest: [u8; 32],
    pub manifest_digest: [u8; 32],
    pub runtime_digest: [u8; 32],
    pub window_acknowledgement: [u8; 32],
}
impl RestoreInputRequest {
    fn validate(&self) -> Result<(), RecoveryReviewError> {
        for identity in [&self.operation_id, &self.operator_id] {
            if identity.len() > 256
                || identity.capacity() > 256
                || identity.is_empty()
                || identity.chars().any(char::is_control)
            {
                return Err(RecoveryReviewError::Review(StoreError::Invalid));
            }
        }
        if [
            self.snapshot_digest,
            self.manifest_digest,
            self.runtime_digest,
            self.window_acknowledgement,
        ]
        .contains(&[0; 32])
        {
            return Err(RecoveryReviewError::Review(StoreError::Invalid));
        }
        Ok(())
    }
}

/// Finite review of the actual current unit plus exact backup/loss window. It
/// supplies no batch, fresh witness, checkpoint, clock, role, grant or resume.
/// Staged restore must separately validate all original archived row links and
/// install Root-owned current controls before it can become reviewable.
pub struct ReviewedRestoreInput {
    current: RecoveryReview,
    window: RestoreWindow,
    operation_digest: [u8; 32],
    runtime_digest: [u8; 32],
}
impl ReviewedRestoreInput {
    #[must_use]
    pub const fn current(&self) -> &RecoveryReview {
        &self.current
    }
    #[must_use]
    pub const fn window(&self) -> &RestoreWindow {
        &self.window
    }
    #[must_use]
    pub const fn operation_digest(&self) -> [u8; 32] {
        self.operation_digest
    }
    #[must_use]
    pub const fn runtime_digest(&self) -> [u8; 32] {
        self.runtime_digest
    }
}

/// `snapshot` comes from the protected SAME-file reader under original Recovery
/// custody. No decoder/artifact callback defaults to allowed. Both old and
/// current metadata are checked; current replacement evidence cannot authorize
/// an original association. Original policy/audit/deadline/capacity stay held
/// through this review and the eventual response's physical destruction.
pub fn review_restore_input(
    view: &ReadView,
    snapshot: &SnapshotReceipt,
    request: &RestoreInputRequest,
    current_request: RecoveryReviewRequest<'_>,
    owners: &mut impl RecoveryReviewOwners,
    mut verify_artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError>,
    mut current: impl FnMut() -> Result<(), StoreError>,
) -> Result<ReviewedRestoreInput, RecoveryReviewError> {
    request.validate()?;
    checkpoint(current_request.deadline, &mut current)?;
    if snapshot.snapshot_digest != request.snapshot_digest
        || snapshot.manifest_digest != request.manifest_digest
        || request.runtime_digest != current_request.metadata.runtime_digest
    {
        return Err(RecoveryReviewError::Review(StoreError::Conflict));
    }
    snapshot
        .manifest
        .validate()
        .map_err(RecoveryReviewError::Review)?;
    owners
        .require_runtime(snapshot.manifest.metadata.runtime_digest)
        .map_err(RecoveryReviewError::Review)?;
    for format in &snapshot.manifest.metadata.decoder_formats {
        checkpoint(current_request.deadline, &mut current)?;
        owners
            .require_decoder(format)
            .map_err(RecoveryReviewError::Review)?;
    }
    for artifact in &snapshot.manifest.metadata.required_artifacts {
        checkpoint(current_request.deadline, &mut current)?;
        verify_artifact(artifact).map_err(RecoveryReviewError::Review)?;
    }
    let reviewed = review_snapshot(view, current_request, owners, &mut current)?;
    let window = RestoreWindow::capture(view, snapshot, current_request.deadline, &mut current)
        .map_err(snapshot_error)?;
    let window_digest = window.digest().map_err(RecoveryReviewError::Review)?;
    if window_digest != request.window_acknowledgement {
        return Err(RecoveryReviewError::Review(StoreError::Conflict));
    }
    let mut digest = Sha256::new();
    digest.update(b"latent-original-restore-input-v2\0");
    for identity in [&request.operation_id, &request.operator_id] {
        digest.update((identity.len() as u64).to_be_bytes());
        digest.update(identity.as_bytes());
    }
    digest.update(request.runtime_digest);
    digest.update(window_digest);
    checkpoint(current_request.deadline, &mut current)?;
    Ok(ReviewedRestoreInput {
        current: reviewed,
        window,
        operation_digest: digest.finalize().into(),
        runtime_digest: request.runtime_digest,
    })
}

fn snapshot_error(error: SnapshotError) -> RecoveryReviewError {
    match error {
        SnapshotError::Source(error) => RecoveryReviewError::Source(error),
        SnapshotError::Review(error) => RecoveryReviewError::Review(error),
        SnapshotError::Deadline => RecoveryReviewError::Deadline,
        SnapshotError::Capacity => RecoveryReviewError::Capacity,
        SnapshotError::Output => RecoveryReviewError::Review(StoreError::Unavailable),
    }
}

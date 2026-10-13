use super::codecs::Codecs;
use latent_state::{
    embedded::{ReadView, RowKey, StoreError},
    protected_store::{RestoredMigrationResumeCommitFence, RestoredMigrationResumeOwners},
    recovery::{
        restored_resume::{RestoredMigrationResumeObservation, RestoredMigrationResumeRequest},
        snapshot::{RequiredArtifact, SnapshotClosure},
    },
};
impl RestoredMigrationResumeOwners for Codecs {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.row(key, bytes)
    }
    fn artifact(&self, required: &RequiredArtifact) -> Result<(), StoreError> {
        self.artifact(required)
    }
    fn linked(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        self.closure(view)
    }
    fn review(
        &self,
        view: &ReadView,
        request: &RestoredMigrationResumeRequest,
        observed: RestoredMigrationResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        self.authority.check("namespace-resume")?;
        if request.operator_id != self.authority.actor
            || request.review_digest != self.review
            || observed.snapshot.manifest.metadata.runtime_digest != self.runtime
            || observed.schema.declaration_digest()
                != self.catalog.primary().schema.declaration_digest()
            || observed.schema.proof_digest() != self.catalog.primary().schema.proof_digest()
            || !observed.progress.completed()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        self.closure(view)?
            .inventory
            .require_retirement_drained()
            .map_err(|_| StoreError::Unavailable)
    }
    fn accept(&self, original: RestoredMigrationResumeCommitFence<'_>) -> Result<(), StoreError> {
        self.fence("namespace-resume", || original.accept())
    }
}

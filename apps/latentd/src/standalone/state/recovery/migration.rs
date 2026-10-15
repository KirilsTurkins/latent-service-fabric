//! Current fixed protected migration, separate from retained v1 recipe/receipts.
use super::codecs::Codecs;
use latent_state::{
    embedded::{ReadView, RowKey, StoreError},
    protected_store::{AggregateMigrationOwners, MigrationCommitFence, MigrationResumeCommitFence},
    recovery::{
        migration::{AggregateMigrationObservation, AggregateMigrationRequest, MigrationError},
        resume::{MigrationResumeObservation, MigrationResumeRequest},
        snapshot::{RequiredArtifact, SnapshotClosure},
    },
};

impl Codecs {
    pub(super) fn migration_request(
        &self,
        view: &ReadView,
        operation_id: &str,
        expected_view: &[u8],
        checkpoint_digest: &str,
        checkpoint_manifest_digest: &str,
    ) -> Result<AggregateMigrationRequest, StoreError> {
        let mut scope = self.selected_view(view)?.scope();
        scope.state_schema =
            latent_state::namespace::compatibility::SchemaId::from_definition(super::profile::V1)
                .map_err(|_| StoreError::Invalid)?
                .as_str()
                .into();
        Ok(AggregateMigrationRequest {
            scope,
            operation_id: operation_id.into(),
            operator_id: self.authority.actor.clone(),
            expected_view: expected_view.to_vec(),
            checkpoint_digest: super::assets::digest_bytes(checkpoint_digest)
                .map_err(|_| StoreError::Invalid)?,
            checkpoint_manifest_digest: super::assets::digest_bytes(checkpoint_manifest_digest)
                .map_err(|_| StoreError::Invalid)?,
            package_digest: self.catalog.primary().schema.declaration().package_digest,
            review_digest: self.review,
        })
    }
    fn require_migration(&self, request: &AggregateMigrationRequest) -> Result<(), StoreError> {
        let operation = &self.catalog.primary().operation;
        if request.operator_id != self.authority.actor
            || request.scope.tenant != operation.target().tenant
            || request.scope.namespace.0 != operation.namespace()
            || request.scope.incarnation != operation.incarnation()
            || request.package_digest != self.catalog.primary().schema.declaration().package_digest
            || request.review_digest != self.review
        {
            return Err(StoreError::Unavailable);
        }
        self.check()
    }
}
impl AggregateMigrationOwners for Codecs {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.row(key, bytes)
    }
    fn linked(&self, view: &ReadView) -> Result<SnapshotClosure, MigrationError> {
        self.closure(view).map_err(MigrationError::Review)
    }
    fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.artifact(artifact)
    }
    fn review(
        &self,
        view: &ReadView,
        request: &AggregateMigrationRequest,
        observed: AggregateMigrationObservation<'_>,
    ) -> Result<(), StoreError> {
        self.require_migration(request)?;
        self.authority.check("namespace-schema-migrate")?;
        if observed.schema.proof_digest() != self.catalog.primary().schema.proof_digest()
            || observed.schema.declaration_digest()
                != self.catalog.primary().schema.declaration_digest()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        self.closure(view)?
            .inventory
            .require_retirement_drained()
            .map_err(|_| StoreError::Unavailable)
    }
    fn accept(&self, original: MigrationCommitFence<'_>) -> Result<(), StoreError> {
        self.fence("namespace-schema-migrate", || original.accept())
    }
    fn review_resume(
        &self,
        view: &ReadView,
        request: &MigrationResumeRequest,
        observed: MigrationResumeObservation<'_>,
        _linked: &SnapshotClosure,
    ) -> Result<(), StoreError> {
        self.require_migration(&request.migration)?;
        self.authority.check("namespace-resume")?;
        if request.operator_id != self.authority.actor
            || request.review_digest != self.review
            || observed.schema.declaration_digest()
                != self.catalog.primary().schema.declaration_digest()
            || !observed.progress.completed()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        self.closure(view)?
            .inventory
            .require_retirement_drained()
            .map_err(|_| StoreError::Unavailable)
    }
    fn accept_resume(&self, original: MigrationResumeCommitFence<'_>) -> Result<(), StoreError> {
        self.fence("namespace-resume", || original.accept())
    }
}

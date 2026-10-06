//! Installed review actions use actual native rows and retained current seals.
use super::{authority::Authority, catalog::Catalog, request::Action};
use latent_state::{
    embedded::{ReadView, RowKey, StoreError},
    namespace::{
        compatibility::{RetainedFormat, ReviewedSchema},
        NamespaceRecord,
    },
    recovery::{
        migration::{AggregateMigrationObservation, AggregateMigrationRecipe, MigrationAction},
        offline::{
            OfflineAggregateMigrationRequest, OfflineRestoreRequest,
            PreparedRetainedReconciliation, RecoveryCodecs, RecoveryReviewRequest, RestoreFence,
            RetainedReconciliationRequest, SnapshotFile,
        },
        restore::RestoreWindow,
        resume::{NamespaceRecoveryView, NamespaceResumeObservation, NamespaceResumeRequest},
        snapshot::{RequiredArtifact, SnapshotClosure, SnapshotMetadata},
    },
};
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub(super) struct Codecs {
    pub catalog: Catalog,
    pub authority: Arc<Authority>,
    pub action: Action,
    pub runtime: [u8; 32],
    pub review: [u8; 32],
}
impl Codecs {
    pub fn new(
        catalog: Catalog,
        authority: Authority,
        action: Action,
    ) -> Result<Arc<Self>, StoreError> {
        let mut runtime = Sha256::new();
        runtime.update(b"lsf.java718.installed-offline-review.v1\0");
        runtime.update(latent_state::embedded::STORE_FORMAT);
        runtime.update(serde_json::to_vec(&catalog.formats).map_err(|_| StoreError::Invalid)?);
        let runtime: [u8; 32] = runtime.finalize().into();
        let mut review = Sha256::new();
        review.update(b"lsf.java718.native-schema-review.v1\0");
        review.update(runtime);
        review.update(catalog.primary().schema.proof_digest());
        review.update(catalog.primary().schema.declaration_digest());
        review.update((authority.actor.len() as u64).to_le_bytes());
        review.update(authority.actor.as_bytes());
        Ok(Arc::new(Self {
            catalog,
            authority: Arc::new(authority),
            action,
            runtime,
            review: review.finalize().into(),
        }))
    }
    pub fn selected_view(&self, view: &ReadView) -> Result<NamespaceRecoveryView, StoreError> {
        let operation = &self.catalog.primary().operation;
        let observed = NamespaceRecoveryView::capture(
            view,
            &operation.target().tenant,
            &latent_core::StateNamespaceId(operation.namespace().into()),
        )?;
        self.require_namespace(&observed.namespace)?;
        Ok(observed)
    }
    pub fn check(&self) -> Result<(), StoreError> {
        self.authority.check(self.action.purposes()[0])?;
        self.catalog.current()
    }
    fn require_namespace(&self, namespace: &NamespaceRecord) -> Result<(), StoreError> {
        let operation = &self.catalog.primary().operation;
        if namespace.tenant != operation.target().tenant
            || namespace.id.0 != operation.namespace()
            || namespace.version.incarnation != operation.incarnation()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        self.catalog
            .primary()
            .schema
            .require_namespace(namespace)
            .map_err(|_| StoreError::UnsupportedFormat)
    }
    fn reviewed_retained(&self, view: &ReadView) -> Result<(), StoreError> {
        self.check()?;
        self.selected_view(view)?;
        // This is an observation of retained local work, never a claim that a
        // historical pending effect was unsent or completed remotely.
        self.validate_view(view)?
            .inventory
            .require_retirement_drained()
            .map_err(|_| StoreError::Unavailable)
    }
    fn require_restore(&self, request: &OfflineRestoreRequest) -> Result<(), StoreError> {
        if request.review.operator_id != self.authority.actor
            || request.review.runtime_digest != self.runtime
        {
            return Err(StoreError::Unavailable);
        }
        self.authority.check("namespace-inspect-restore")
    }
    fn require_migration(
        &self,
        request: &OfflineAggregateMigrationRequest,
    ) -> Result<(), StoreError> {
        let operation = &self.catalog.primary().operation;
        if request.review.operator_id != self.authority.actor
            || request.review.scope.tenant != operation.target().tenant
            || request.review.scope.namespace.0 != operation.namespace()
            || request.review.scope.incarnation != operation.incarnation()
            || request.review.package_digest
                != self.catalog.primary().schema.declaration().package_digest
            || request.review.review_digest != self.review
        {
            return Err(StoreError::Unavailable);
        }
        self.authority.check("namespace-schema-migrate")
    }
}
impl RecoveryCodecs for Codecs {
    fn runtime_digest(&self) -> [u8; 32] {
        self.runtime
    }
    fn retained_bytes(&self) -> u64 {
        4 * 1024 * 1024
    }
    fn scratch_bytes(&self) -> u64 {
        4 * 1024 * 1024
    }
    fn snapshot_file_bytes(&self) -> u64 {
        self.authority.file_bytes
    }
    fn installed_formats(&self) -> &[RetainedFormat] {
        &self.catalog.formats
    }
    fn validate_row(
        &self,
        source: &ReadView,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<(), StoreError> {
        self.check()?;
        let local = latent_commit::atomic::validate_row(key, bytes);
        if local != Err(StoreError::UnsupportedFormat) {
            return local;
        }
        super::super::validation::foreign(source, key, bytes)
    }
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        self.check()?;
        let owner = latent_effects::dispatch_store::DispatchCatalog::owner_checkpoint(view)?
            .ok_or(StoreError::Unavailable)?;
        let now = latent_effects::runtime::EffectTimeSource::observe(self.authority.clock.as_ref());
        let checkpoint = self.authority.clock.minimum_checkpoint();
        validate_clock_floor(owner, checkpoint, now)?;
        self.catalog.closure(view, self.authority.deadline)
    }
    fn verify_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.check()?;
        if self.catalog.artifacts.contains(artifact) {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    fn review_backup(
        &self,
        view: &ReadView,
        metadata: &SnapshotMetadata,
        _output: &SnapshotFile,
    ) -> Result<(), StoreError> {
        self.authority.check("namespace-snapshot")?;
        if metadata.operator_id != self.authority.actor
            || metadata.runtime_digest != self.runtime
            || metadata.tenant != self.catalog.primary().operation.target().tenant.0
        {
            return Err(StoreError::Unavailable);
        }
        self.validate_view(view)?.require_declared(metadata)
    }
    fn authorize_inspection(
        &self,
        view: &ReadView,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.require_restore(request)?;
        self.selected_view(view)?;
        self.validate_view(view)?;
        Ok(())
    }
    fn review_restore(
        &self,
        view: &ReadView,
        window: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.require_restore(request)?;
        self.validate_view(view)?;
        if matches!(self.action, Action::Restore { .. }) {
            self.authority.check("namespace-restore")?;
            if request.review.window_acknowledgement != window.digest()? {
                return Err(StoreError::Conflict);
            }
        }
        for pair in window.namespaces() {
            self.require_namespace(&pair.snapshot.decode()?.0)?;
            self.require_namespace(&pair.current.decode()?.0)?;
        }
        Ok(())
    }
    fn accept_restore(
        &self,
        request: &OfflineRestoreRequest,
        _fence: RestoreFence,
    ) -> Result<(), StoreError> {
        self.require_restore(request)?;
        self.authority.check("namespace-restore")?;
        self.catalog.current()
    }
    fn review_reconciliation(
        &self,
        view: &ReadView,
        request: &RecoveryReviewRequest,
    ) -> Result<(), StoreError> {
        if request.operator_id != self.authority.actor || request.review_digest != self.review {
            return Err(StoreError::Unavailable);
        }
        self.authority.check("namespace-review-recovery")?;
        self.reviewed_retained(view)
    }
    fn accept_reconciliation(&self, request: &RecoveryReviewRequest) -> Result<(), StoreError> {
        if request.operator_id != self.authority.actor || request.review_digest != self.review {
            return Err(StoreError::Unavailable);
        }
        self.authority.check("namespace-review-recovery")?;
        self.catalog.current()
    }
    fn inspect_retained_reconciliation(
        &self,
        view: &ReadView,
        request: &RetainedReconciliationRequest,
    ) -> Result<Vec<u8>, StoreError> {
        super::reconciliation::inspect(self, view, request)
    }
    fn prepare_retained_reconciliation(
        &self,
        view: &ReadView,
        request: &RetainedReconciliationRequest,
    ) -> Result<PreparedRetainedReconciliation, StoreError> {
        super::reconciliation::prepare(self, view, request)
    }
    fn accept_retained_reconciliation(
        &self,
        request: &RetainedReconciliationRequest,
    ) -> Result<(), StoreError> {
        super::reconciliation::accept(self, request)
    }
    fn review_namespace_resume(
        &self,
        view: &ReadView,
        request: &NamespaceResumeRequest,
        observed: NamespaceResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        if request.operator_id != self.authority.actor || request.review_digest != self.review {
            return Err(StoreError::Unavailable);
        }
        self.authority.check("namespace-resume")?;
        self.require_namespace(observed.namespace)?;
        self.reviewed_retained(view)
    }
    fn accept_namespace_resume(&self, request: &NamespaceResumeRequest) -> Result<(), StoreError> {
        if request.operator_id != self.authority.actor || request.review_digest != self.review {
            return Err(StoreError::Unavailable);
        }
        self.authority.check("namespace-resume")?;
        self.catalog.current()
    }
    fn authorize_namespace_inspection(
        &self,
        view: &ReadView,
        operator: &str,
        namespace: &latent_core::StateNamespaceId,
    ) -> Result<(), StoreError> {
        if operator != self.authority.actor
            || namespace.0 != self.catalog.primary().operation.namespace()
        {
            return Err(StoreError::Unavailable);
        }
        self.check()?;
        self.selected_view(view)?;
        Ok(())
    }
    fn migration_schema(
        &self,
        _view: &ReadView,
        request: &OfflineAggregateMigrationRequest,
    ) -> Result<ReviewedSchema, StoreError> {
        self.require_migration(request)?;
        Ok(self.catalog.primary().schema.clone())
    }
    fn migration_recipe(
        &self,
        _view: &ReadView,
        request: &OfflineAggregateMigrationRequest,
    ) -> Result<AggregateMigrationRecipe, StoreError> {
        self.require_migration(request)?;
        Ok(AggregateMigrationRecipe::JavaAggregate)
    }
    fn review_migration(
        &self,
        view: &ReadView,
        request: &OfflineAggregateMigrationRequest,
        observed: AggregateMigrationObservation<'_>,
    ) -> Result<(), StoreError> {
        self.require_migration(request)?;
        self.require_namespace(&observed.current.namespace)?;
        self.reviewed_retained(view)
    }
    fn accept_migration(
        &self,
        request: &OfflineAggregateMigrationRequest,
        _phase: MigrationAction,
    ) -> Result<(), StoreError> {
        self.require_migration(request)?;
        self.catalog.current()
    }
}

fn validate_clock_floor(
    owner: (u64, u64),
    minimum: (u64, u64),
    now: latent_effects::authority::EffectTime,
) -> Result<(), StoreError> {
    // Exactly the existing DispatchCatalog minimum rule, without starting an
    // epoch. A later retained owner does not promote the protected checkpoint.
    if !now.continuity_proven
        || now.unix_millis < owner.1
        || owner.0 < minimum.0
        || owner.1 < minimum.1
    {
        return Err(StoreError::Unavailable);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_effects::authority::EffectTime;

    #[test]
    fn native_offline_clock_uses_original_minimum_and_retained_floor_without_advancing_checkpoint()
    {
        let now = EffectTime {
            unix_millis: 3000,
            continuity_proven: true,
        };
        assert!(validate_clock_floor((2, 2000), (1, 1000), now).is_ok());
        for minimum in [(3, 1000), (1, 2500)] {
            assert_eq!(
                validate_clock_floor((2, 2000), minimum, now),
                Err(StoreError::Unavailable)
            );
        }
        for invalid in [
            EffectTime {
                unix_millis: 1999,
                continuity_proven: true,
            },
            EffectTime {
                unix_millis: 3000,
                continuity_proven: false,
            },
        ] {
            assert_eq!(
                validate_clock_floor((2, 2000), (1, 1000), invalid),
                Err(StoreError::Unavailable)
            );
        }
        assert!(validate_clock_floor(
            (u64::MAX, u64::MAX),
            (u64::MAX, u64::MAX),
            EffectTime {
                unix_millis: u64::MAX,
                continuity_proven: true
            },
        )
        .is_ok());
    }
}

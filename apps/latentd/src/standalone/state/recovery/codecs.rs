//! Closed current package/schema, linked rows and conservative clock owners.
use super::{authority::Authority, catalog::Catalog, request::Action};
use latent_core::native_capacity::{NativeBufferPermit, NativeReservation};
use latent_effects::{
    authority::EffectTime, dispatch_store::DispatchCatalog, runtime::EffectTimeSource,
};
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{catalog::NamespaceCatalog, NamespaceRecord},
    recovery::{
        namespace_resume::NamespaceRecoveryView,
        snapshot::{RequiredArtifact, SnapshotClosure},
    },
    store_identity::{ExternalCheckpoint, StoreIdentity},
    tenant::TenantQuota,
};
use sha2::{Digest, Sha256};
use std::sync::Arc;
type Validator = fn(&RowKey, &[u8]) -> Result<(), StoreError>;

pub(super) struct Codecs {
    pub catalog: Catalog,
    pub authority: Authority,
    pub action: Action,
    pub runtime: [u8; 32],
    pub review: [u8; 32],
    pub namespace: NamespaceRecord,
    pub identity: StoreIdentity,
    pub quotas: Vec<TenantQuota>,
    pub checkpoint: ExternalCheckpoint,
    pub original: Arc<NativeReservation>,
    pub _metadata: NativeBufferPermit,
}

impl Codecs {
    pub fn identities(catalog: &Catalog, actor: &str) -> Result<([u8; 32], [u8; 32]), StoreError> {
        let mut runtime = Sha256::new();
        runtime.update(b"latent.current.installed-offline-review.v2\0");
        runtime.update(latent_state::embedded::STORE_FORMAT);
        runtime.update(serde_json::to_vec(&catalog.formats).map_err(|_| StoreError::Invalid)?);
        let runtime: [u8; 32] = runtime.finalize().into();
        let mut review = Sha256::new();
        review.update(b"latent.current.native-schema-review.v3\0");
        review.update(runtime);
        review.update(catalog.primary().schema.proof_digest());
        review.update(catalog.primary().schema.declaration_digest());
        let mut sources = catalog.schemas.iter().collect::<Vec<_>>();
        sources.sort_by(|one, two| {
            one.operation
                .publication()
                .publication()
                .as_str()
                .cmp(two.operation.publication().publication().as_str())
        });
        for source in sources {
            for identity in [
                source.operation.publication().publication().as_str(),
                &source.operation.publication().release().0,
            ] {
                review.update((identity.len() as u64).to_le_bytes());
                review.update(identity.as_bytes());
            }
            review.update(source.schema.proof_digest());
            review.update(source.schema.declaration_digest());
        }
        review.update((actor.len() as u64).to_le_bytes());
        review.update(actor.as_bytes());
        Ok((runtime, review.finalize().into()))
    }
    pub fn check(&self) -> Result<(), StoreError> {
        self.authority.check(self.action.purposes()[0])?;
        self.catalog.current()?;
        self.original
            .with_live(|| ())
            .map_err(|_| StoreError::SnapshotExpired)
    }
    pub fn fence(
        &self,
        purpose: &str,
        action: impl FnOnce() -> Result<(), StoreError>,
    ) -> Result<(), StoreError> {
        self.check()?;
        let publications = self
            .catalog
            .schemas
            .iter()
            .map(|schema| schema.operation.publication().clone())
            .collect::<Vec<_>>();
        self.authority
            .with_current_dependencies(purpose, &publications, action)
    }
    pub fn time(&self) -> Result<EffectTime, StoreError> {
        let time = self.authority.clock.observe();
        if !time.continuity_proven || time.unix_millis < self.checkpoint.clock_floor_millis() {
            return Err(StoreError::Unavailable);
        }
        Ok(time)
    }
    pub fn selected_view(&self, view: &ReadView) -> Result<NamespaceRecoveryView, StoreError> {
        let selected = &self.catalog.primary().operation;
        let observed = NamespaceRecoveryView::capture(
            view,
            &selected.target().tenant,
            &latent_core::StateNamespaceId(selected.namespace().into()),
        )?;
        if observed.namespace.version.incarnation != selected.incarnation() {
            return Err(StoreError::Conflict);
        }
        self.catalog
            .primary()
            .schema
            .require_namespace(&observed.namespace)
            .map_err(|_| StoreError::UnsupportedFormat)?;
        Ok(observed)
    }
    pub fn closure(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        self.check()?;
        super::super::validation::validate(view, &self.identity, &self.quotas, &self.original)?;
        let owner = DispatchCatalog::checkpoint(view)?.ok_or(StoreError::Corrupt)?;
        if owner.0 < self.checkpoint.dispatch_owner_epoch()
            || owner.1 < self.checkpoint.clock_floor_millis()
            || self.time()?.unix_millis < owner.1
        {
            return Err(StoreError::Unavailable);
        }
        self.catalog.closure(view, self.authority.deadline)
    }
    pub fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.check()?;
        if self.catalog.artifacts.contains(artifact) {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    pub fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.check()?;
        match latent_commit::atomic::validate_row(key, bytes) {
            Err(StoreError::UnsupportedFormat) => {}
            result => return result,
        }
        if *key == latent_state::tenant::guard_key() {
            return latent_state::tenant::validate_guard_bytes(bytes, &self.quotas);
        }
        if key.family == Family::Maintenance
            && key.key.starts_with(latent_state::tenant::QUOTA_PREFIX)
        {
            let record = latent_state::tenant::TenantRecord::decode(bytes)?;
            return if self.quotas.contains(&record.quota)
                && *key == latent_state::tenant::quota_key(&record.quota.tenant)?
            {
                Ok(())
            } else {
                Err(StoreError::UnsupportedFormat)
            };
        }
        match latent_state::session::validate_row_in_namespace(key, bytes, &self.namespace) {
            Err(StoreError::UnsupportedFormat) => {}
            result => return result,
        }
        let validators: [Validator; 9] = [
            latent_wire::phase4::StateManagementBackend::validate_operation_bytes,
            |key, bytes| {
                NamespaceCatalog::validate_row(key, bytes).map_err(|error| match error {
                    latent_state::namespace::NamespaceError::UnsupportedFormat => {
                        StoreError::UnsupportedFormat
                    }
                    _ => StoreError::Corrupt,
                })
            },
            latent_effects::dispatch_store::validate_row,
            latent_state::store_identity::StoreIdentity::validate_row,
            latent_state::recovery::RecoveryGuard::validate_row,
            latent_state::recovery::migration::AggregateMigrationProgress::validate_row,
            latent_state::recovery::resume::MigrationResumeReceipt::validate_row,
            latent_state::recovery::namespace_resume::NamespaceResumeReceipt::validate_row,
            latent_state::recovery::restored_resume::RestoredMigrationResumeReceipt::validate_row,
        ];
        for validator in validators {
            match validator(key, bytes) {
                Err(StoreError::UnsupportedFormat) => {}
                result => return result,
            }
        }
        Err(StoreError::UnsupportedFormat)
    }
}

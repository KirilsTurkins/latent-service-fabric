//! Signed deployment schema checks against the original protected state owner.
use std::{
    collections::BTreeMap,
    sync::{atomic::AtomicBool, Arc, Weak},
    time::Duration,
};

use latent_core::{DeploymentId, PlatformError, PlatformErrorCode, StateNamespaceId, TenantId};
use latent_manifest::TransactionBinding;
use latent_state::{
    embedded::StoreError,
    namespace::catalog::{NamespaceCatalog, NamespaceRead},
    protected_store::ProtectedStoreOwner,
    store_io::StoreIoKind,
};

use super::{
    compiler::RevisionRecord,
    error,
    rollouts::{
        comparison::{bundle, state::binding, MAX_PACKAGE},
        WorkReservation,
    },
    CompiledCatalog, DirectoryDeploymentRepository,
};

const MAX_SCHEMAS_PER_APPLY: usize = 32;
type Scope = (TenantId, StateNamespaceId);
type UpdatedDeployment = (Arc<RevisionRecord>, Option<Arc<RevisionRecord>>);

pub(super) struct Owner {
    store: Weak<ProtectedStoreOwner>,
    namespaces: Weak<NamespaceCatalog>,
    work: Arc<AtomicBool>,
}

pub(super) struct PreparedSchemas {
    namespaces: Arc<NamespaceCatalog>,
    expected: BTreeMap<Scope, Option<NamespaceRead>>,
    _work: Arc<WorkReservation>,
}

impl PreparedSchemas {
    pub(super) fn replace(
        schemas: Option<&Self>,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if let Some(schemas) = schemas {
            schemas
                .namespaces
                .lifecycle()
                .with_current_deployment_schemas(&schemas.expected, action)
                .map_err(|_| {
                    error(
                        PlatformErrorCode::StateConflict,
                        "deployment-namespace-changed",
                    )
                })?
        } else {
            action()
        }
    }
}

impl DirectoryDeploymentRepository {
    /// Attach the running node's own protected state owner before exposing control.
    pub fn bind_transaction_schema_owner(
        &self,
        store: &Arc<ProtectedStoreOwner>,
        namespaces: &Arc<NamespaceCatalog>,
        native: &latent_core::native_capacity::NativeCapacityOwner,
    ) -> Result<(), PlatformError> {
        if self.admission.is_none()
            || !store.uses_native_capacity(native)
            || !namespaces.uses_native_capacity(native)
        {
            return Err(unavailable());
        }
        self.schema_owner
            .set(Owner {
                store: Arc::downgrade(store),
                namespaces: Arc::downgrade(namespaces),
                work: Arc::new(AtomicBool::new(false)),
            })
            .map_err(|_| unavailable())
    }

    pub(super) async fn prepare_apply_schemas(
        &self,
        catalog: &CompiledCatalog,
        changed: &[&DeploymentId],
        previous: Option<&CompiledCatalog>,
    ) -> Result<Option<PreparedSchemas>, PlatformError> {
        let Some(owner) = self.schema_owner.get() else {
            return Ok(None);
        };
        let records = transaction_records(catalog, changed, previous)?;
        if records.is_empty() {
            return Ok(None);
        }
        let work = Arc::new(WorkReservation::acquire(&owner.work)?);
        let store = owner.store.upgrade().ok_or_else(unavailable)?;
        let namespaces = owner.namespaces.upgrade().ok_or_else(unavailable)?;
        let mut declared = BTreeMap::<Scope, String>::new();
        for (record, prior) in records {
            let tenant = record
                .deployment
                .metadata
                .tenant
                .as_ref()
                .ok_or_else(incompatible)?;
            let declaration = self.transaction_binding(tenant, &record, true).await?;
            if let Some(prior) = prior {
                let before = self.transaction_binding(tenant, &prior, false).await?;
                if before.namespace != declaration.namespace
                    || !before
                        .operations
                        .iter()
                        .all(|operation| declaration.operations.contains(operation))
                {
                    return Err(incompatible());
                }
            }
            let scope = (tenant.clone(), StateNamespaceId(declaration.namespace));
            match declared.entry(scope) {
                std::collections::btree_map::Entry::Vacant(entry) => {
                    entry.insert(declaration.state_schema);
                }
                std::collections::btree_map::Entry::Occupied(entry)
                    if entry.get() != &declaration.state_schema =>
                {
                    return Err(incompatible())
                }
                std::collections::btree_map::Entry::Occupied(_) => {}
            }
        }
        let keeper: Arc<dyn std::any::Any + Send + Sync> = work.clone();
        let job = store
            .with_store_retaining(StoreIoKind::Read, 512 * 1024, keeper, move |engine| {
                let view = engine.snapshot()?;
                let mut expected = BTreeMap::new();
                for (scope, schema) in declared {
                    let current = NamespaceCatalog::read_in(&view, &scope.0, &scope.1)
                        .map_err(|_| StoreError::Corrupt)?;
                    if current
                        .as_ref()
                        .is_some_and(|row| row.record().state_schema != schema)
                    {
                        return Ok(Err(incompatible()));
                    }
                    expected.insert(scope, current);
                }
                Ok(Ok(expected))
            })
            .map_err(|_| unavailable())?;
        let expected = tokio::time::timeout(Duration::from_secs(5), job)
            .await
            .map_err(|_| unavailable())?
            .map_err(|_| unavailable())?
            .map_err(|_| unavailable())??;
        Ok(Some(PreparedSchemas {
            namespaces,
            expected,
            _work: work,
        }))
    }

    async fn transaction_binding(
        &self,
        tenant: &TenantId,
        record: &RevisionRecord,
        require_live: bool,
    ) -> Result<TransactionBinding, PlatformError> {
        let release = &record.deployment.release;
        let publication = record.publication.as_ref().ok_or_else(incompatible)?;
        let source = self
            .artifacts
            .retained_package_source_selected(tenant, release, Some(publication), MAX_PACKAGE)
            .await?
            .ok_or_else(incompatible)?;
        if source.publication() != publication {
            return Err(incompatible());
        }
        if require_live {
            let eligibility = self
                .artifacts
                .execution_eligibility_selected(release, Some(publication))?
                .ok_or_else(incompatible)?;
            eligibility.authorize_tenant(tenant)?;
            eligibility.check_current()?;
            if eligibility.publication() != publication
                || eligibility.package() != Some(source.package())
                || eligibility.admission().is_none()
            {
                return Err(incompatible());
            }
        }
        let package = bundle(source, tenant, release, self.config.manifest_profile)?;
        binding(&package, &record.deployment.id)?.ok_or_else(incompatible)
    }
}

fn transaction_records(
    catalog: &CompiledCatalog,
    changed: &[&DeploymentId],
    previous: Option<&CompiledCatalog>,
) -> Result<Vec<UpdatedDeployment>, PlatformError> {
    let mut records = Vec::new();
    for id in changed {
        let record = catalog.record_by_id(id).ok_or_else(incompatible)?;
        let prior = previous
            .and_then(|previous| previous.record_by_id(id))
            .filter(|prior| prior.transactional);
        if prior.is_some() && !record.transactional {
            return Err(incompatible());
        }
        if record.transactional {
            if records.len() == MAX_SCHEMAS_PER_APPLY {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "deployment-schema-batch",
                ));
            }
            let replaced = prior.filter(|prior| {
                prior.publication != record.publication
                    || prior.deployment.release != record.deployment.release
            });
            records.push((Arc::clone(record), replaced.cloned()));
        }
    }
    Ok(records)
}

fn incompatible() -> PlatformError {
    error(
        PlatformErrorCode::IncompatibleContract,
        "deployment-state-schema-incompatible",
    )
}

fn unavailable() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "deployment-namespace-unavailable",
    )
}

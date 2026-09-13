use std::collections::BTreeSet;
use std::sync::Arc;

use latent_core::{
    BoxFuture, DeploymentId, ErrorDetail, Metadata, PlatformError, PlatformErrorCode,
    RouteGeneration, TenantId,
};
use latent_manifest::{
    DeploymentManifest, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};

use super::observation::{count, CatalogWorkOperation as WorkOperation, Work};
use super::{
    compiler::compile_for_publication, error, manifest_error, next_generation, now,
    CompiledCatalog, DeploymentPage, DeploymentPageRequest, DirectoryDeploymentRepository,
};
use crate::{
    DeploymentApplyReceipt, DeploymentDeleteReceipt, DeploymentStore, VersionedDeployment,
};

pub(super) struct CommitOutcome {
    pub durability: Result<(), PlatformError>,
}

#[derive(Clone, Copy)]
enum Operation {
    Apply,
    Delete,
}

pub(super) struct ObjectPrecondition {
    tenant: TenantId,
    id: DeploymentId,
    expected: Option<u64>,
    operation: Operation,
}

impl ObjectPrecondition {
    pub(super) fn check(&self, catalog: &CompiledCatalog) -> Result<(), PlatformError> {
        if let Some(manifest) = catalog.deployments.get(&self.id) {
            if manifest.metadata.tenant.as_ref() != Some(&self.tenant) {
                return Err(match self.operation {
                    Operation::Apply => scope_conflict(),
                    Operation::Delete => not_found(),
                });
            }
        }
        let actual = catalog.versions.get(&self.id).copied().unwrap_or(0);
        if self.expected.is_some_and(|expected| expected != actual) {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "deployment-generation-conflict",
            ));
        }
        Ok(())
    }
}

impl DirectoryDeploymentRepository {
    /// Atomically applies a batch. Repeated IDs are rejected, not last-write-wins.
    /// Each affected object receives this publication's generation; untouched stamps persist.
    pub async fn apply_many(
        &self,
        deployments: Vec<DeploymentManifest>,
    ) -> Result<RouteGeneration, PlatformError> {
        let mut work = self.observation.begin(WorkOperation::ApplyMany);
        let result = async {
            if deployments.is_empty() {
                return Ok(self.read_catalog().generation);
            }
            if deployments.len() > self.config.max_deployments {
                return Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "deployment-count-limit",
                ));
            }
            let publication = self.read_publication();
            let previous = &publication.routes;
            let generation = next_generation(previous.generation)?;
            let mut next = previous.deployments.clone();
            let mut versions = previous.versions.clone();
            let mut seen = BTreeSet::new();
            for deployment in deployments {
                let deployment = normalize(deployment, &mut work)?;
                if !seen.insert(deployment.id.clone()) {
                    return Err(error(
                        PlatformErrorCode::AlreadyExists,
                        "duplicate-deployment-id",
                    ));
                }
                check_scope(next.get(&deployment.id).map(Arc::as_ref), &deployment)?;
                versions.insert(deployment.id.clone(), generation.0);
                next.insert(deployment.id.clone(), Arc::new(deployment));
            }
            let compiled = compile_for_publication(
                next,
                versions,
                generation,
                now()?,
                self.artifacts.as_ref(),
                self.config,
                Some(previous),
                &mut work,
                self.runtime_profile.as_deref(),
                self.lifecycle.as_ref(),
                publication.has_control(),
            )
            .await?;
            self.commit_versioned(
                previous.generation,
                publication.transaction,
                compiled,
                &mut work,
            )?;
            Ok(generation)
        }
        .await;
        work.finish(&result);
        result
    }

    async fn apply_with_generation(
        &self,
        tenant: &TenantId,
        deployment: DeploymentManifest,
        expected_generation: Option<u64>,
    ) -> Result<DeploymentApplyReceipt, PlatformError> {
        let mut work = self.observation.begin(WorkOperation::ApplyVersioned);
        let result = async {
            self.validate_target(tenant, &deployment.id)?;
            if deployment.metadata.tenant.as_ref() != Some(tenant) {
                return Err(scope_conflict());
            }
            let deployment = normalize(deployment, &mut work)?;
            let publication = self.read_publication();
            let previous = &publication.routes;
            check_scope(
                previous.deployments.get(&deployment.id).map(Arc::as_ref),
                &deployment,
            )?;
            let precondition = ObjectPrecondition {
                tenant: tenant.clone(),
                id: deployment.id.clone(),
                expected: expected_generation,
                operation: Operation::Apply,
            };
            precondition.check(previous)?;
            let generation = next_generation(previous.generation)?;
            let receipt = DeploymentApplyReceipt {
                deployment: VersionedDeployment {
                    manifest: deployment.clone(),
                    generation: generation.0,
                },
                catalog_generation: generation,
            };
            let mut next = previous.deployments.clone();
            let mut versions = previous.versions.clone();
            versions.insert(deployment.id.clone(), generation.0);
            next.insert(deployment.id.clone(), Arc::new(deployment));
            let compiled = compile_for_publication(
                next,
                versions,
                generation,
                now()?,
                self.artifacts.as_ref(),
                self.config,
                Some(previous),
                &mut work,
                self.runtime_profile.as_deref(),
                self.lifecycle.as_ref(),
                publication.has_control(),
            )
            .await?;
            let outcome = self.commit_checked(
                previous.generation,
                publication.transaction,
                compiled,
                Some(&precondition),
                &mut work,
            )?;
            after_commit();
            outcome.durability.map_err(|failure| {
                committed_error(failure, &receipt.deployment, generation, "apply")
            })?;
            Ok(receipt)
        }
        .await;
        work.finish(&result);
        result
    }

    async fn delete_with_generation(
        &self,
        tenant: &TenantId,
        id: &DeploymentId,
        expected_generation: Option<u64>,
    ) -> Result<DeploymentDeleteReceipt, PlatformError> {
        let mut work = self.observation.begin(WorkOperation::DeleteVersioned);
        let result = async {
            self.validate_target(tenant, id)?;
            let publication = self.read_publication();
            let previous = &publication.routes;
            let precondition = ObjectPrecondition {
                tenant: tenant.clone(),
                id: id.clone(),
                expected: expected_generation,
                operation: Operation::Delete,
            };
            precondition.check(previous)?;
            let manifest = previous
                .deployments
                .get(id)
                .ok_or_else(not_found)?
                .as_ref()
                .clone();
            let generation = next_generation(previous.generation)?;
            let receipt = DeploymentDeleteReceipt {
                deleted: VersionedDeployment {
                    manifest,
                    generation: previous.versions[id],
                },
                catalog_generation: generation,
            };
            let mut next = previous.deployments.clone();
            let mut versions = previous.versions.clone();
            next.remove(id);
            versions.remove(id);
            let compiled = compile_for_publication(
                next,
                versions,
                generation,
                now()?,
                self.artifacts.as_ref(),
                self.config,
                Some(previous),
                &mut work,
                self.runtime_profile.as_deref(),
                self.lifecycle.as_ref(),
                publication.has_control(),
            )
            .await?;
            let outcome = self.commit_checked(
                previous.generation,
                publication.transaction,
                compiled,
                Some(&precondition),
                &mut work,
            )?;
            after_commit();
            outcome.durability.map_err(|failure| {
                committed_error(failure, &receipt.deleted, generation, "delete")
            })?;
            Ok(receipt)
        }
        .await;
        work.finish(&result);
        result
    }

    pub(super) fn validate_target(
        &self,
        tenant: &TenantId,
        id: &DeploymentId,
    ) -> Result<(), PlatformError> {
        if [&tenant.0, &id.0].iter().any(|identifier| {
            identifier.is_empty()
                || identifier.len() > self.config.max_identifier_bytes
                || identifier.chars().any(char::is_control)
        }) {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-deployment-target",
            ));
        }
        Ok(())
    }
}

impl DeploymentStore for DirectoryDeploymentRepository {
    fn reserve_operation_request(
        &self,
    ) -> Result<crate::deployment_operations::DeploymentReadLease, PlatformError> {
        DirectoryDeploymentRepository::reserve_operation_request(self)
    }
    fn prepare_operation(
        &self,
        request: crate::deployment_operations::DeploymentOperationRequest,
    ) -> BoxFuture<
        '_,
        Result<crate::deployment_operations::PreparedDeploymentOperation, PlatformError>,
    > {
        Box::pin(DirectoryDeploymentRepository::prepare_operation(
            self, request,
        ))
    }
    fn commit_operation(
        &self,
        prepared: crate::deployment_operations::PreparedDeploymentOperation,
    ) -> Result<
        crate::deployment_operations::DeploymentOperationRead<
            crate::deployment_operations::DeploymentOperationCommit,
        >,
        PlatformError,
    > {
        DirectoryDeploymentRepository::commit_operation(self, prepared)
    }
    fn get_operation<'a>(
        &'a self,
        tenant: &'a TenantId,
        operation_id: &'a str,
    ) -> BoxFuture<
        'a,
        Result<
            crate::deployment_operations::DeploymentOperationRead<
                crate::deployment_operations::DeploymentOperationLookup,
            >,
            PlatformError,
        >,
    > {
        Box::pin(DirectoryDeploymentRepository::get_operation(
            self,
            tenant,
            operation_id,
        ))
    }
    fn get_operation_snapshot<'a>(
        &'a self,
        tenant: &'a TenantId,
        id: &'a DeploymentId,
    ) -> BoxFuture<
        'a,
        Result<
            crate::deployment_operations::DeploymentOperationRead<
                crate::deployment_operations::DeploymentOperationSnapshot,
            >,
            PlatformError,
        >,
    > {
        Box::pin(DirectoryDeploymentRepository::get_operation_snapshot(
            self, tenant, id,
        ))
    }
    fn apply_versioned<'a>(
        &'a self,
        tenant: &'a TenantId,
        deployment: DeploymentManifest,
        expected_generation: Option<u64>,
    ) -> BoxFuture<'a, Result<DeploymentApplyReceipt, PlatformError>> {
        Box::pin(self.apply_with_generation(tenant, deployment, expected_generation))
    }

    fn delete_versioned<'a>(
        &'a self,
        tenant: &'a TenantId,
        id: &'a DeploymentId,
        expected_generation: Option<u64>,
    ) -> BoxFuture<'a, Result<DeploymentDeleteReceipt, PlatformError>> {
        Box::pin(self.delete_with_generation(tenant, id, expected_generation))
    }

    fn get_versioned<'a>(
        &'a self,
        tenant: &'a TenantId,
        id: &'a DeploymentId,
    ) -> BoxFuture<'a, Result<Option<VersionedDeployment>, PlatformError>> {
        Box::pin(async move {
            self.validate_target(tenant, id)?;
            let catalog = self.read_catalog();
            Ok(catalog
                .deployments
                .get(id)
                .filter(|manifest| manifest.metadata.tenant.as_ref() == Some(tenant))
                .map(|manifest| VersionedDeployment {
                    manifest: manifest.as_ref().clone(),
                    generation: catalog.versions[id],
                }))
        })
    }

    fn list_page(
        &self,
        request: DeploymentPageRequest,
    ) -> BoxFuture<'_, Result<DeploymentPage, PlatformError>> {
        Box::pin(async move { self.list_deployment_page(&request) })
    }

    fn apply(&self, deployment: DeploymentManifest) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            Phase1ManifestValidator
                .validate_deployment(&deployment)
                .map_err(manifest_error)?;
            let tenant = deployment
                .metadata
                .tenant
                .clone()
                .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "missing-tenant"))?;
            self.apply_versioned(&tenant, deployment, None)
                .await
                .map(|_| ())
        })
    }

    fn get<'a>(
        &'a self,
        id: &'a DeploymentId,
    ) -> BoxFuture<'a, Result<Option<DeploymentManifest>, PlatformError>> {
        Box::pin(async move {
            Ok(self
                .read_catalog()
                .deployments
                .get(id)
                .map(|manifest| manifest.as_ref().clone()))
        })
    }

    fn list(&self) -> BoxFuture<'_, Result<Vec<DeploymentManifest>, PlatformError>> {
        Box::pin(async move {
            Ok(self
                .read_catalog()
                .deployments
                .values()
                .map(|manifest| manifest.as_ref().clone())
                .collect())
        })
    }

    fn delete<'a>(&'a self, id: &'a DeploymentId) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let tenant = self
                .read_catalog()
                .deployments
                .get(id)
                .and_then(|manifest| manifest.metadata.tenant.clone())
                .ok_or_else(not_found)?;
            self.delete_versioned(&tenant, id, None).await.map(|_| ())
        })
    }
}

pub(super) fn normalize(
    mut deployment: DeploymentManifest,
    work: &mut Work,
) -> Result<DeploymentManifest, PlatformError> {
    Phase1ManifestValidator
        .validate_deployment(&deployment)
        .map_err(manifest_error)?;
    if deployment.id.0 == "default" {
        return Err(error(
            PlatformErrorCode::AlreadyExists,
            "reserved-default-route",
        ));
    }
    deployment.release.0.make_ascii_lowercase();
    let codec = JsonManifestCodec::default();
    count!(work, normalization_deployment_encodes, 1);
    let bytes = codec
        .encode_deployment(&deployment)
        .map_err(manifest_error)?;
    // Receipts and the live catalog use the same normalized model restored from disk.
    codec.decode_deployment(&bytes).map_err(manifest_error)
}

pub(super) fn check_scope(
    existing: Option<&DeploymentManifest>,
    desired: &DeploymentManifest,
) -> Result<(), PlatformError> {
    if existing.is_some_and(|old| {
        old.metadata.tenant != desired.metadata.tenant
            || old.metadata.namespace != desired.metadata.namespace
            || old.service != desired.service
    }) {
        return Err(scope_conflict());
    }
    Ok(())
}

fn scope_conflict() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "deployment-scope-conflict",
    )
}

fn not_found() -> PlatformError {
    error(PlatformErrorCode::NotFound, "deployment-not-found")
}

fn committed_error(
    mut failure: PlatformError,
    record: &VersionedDeployment,
    catalog_generation: RouteGeneration,
    operation: &str,
) -> PlatformError {
    failure.details.push(ErrorDetail {
        kind: "deployment-mutation".to_owned(),
        fields: Metadata::from([
            ("deployment_id".to_owned(), record.manifest.id.0.clone()),
            (
                "object_generation".to_owned(),
                record.generation.to_string(),
            ),
            (
                "catalog_generation".to_owned(),
                catalog_generation.0.to_string(),
            ),
            ("operation".to_owned(), operation.to_owned()),
            ("committed".to_owned(), "true".to_owned()),
        ]),
    });
    failure
}

fn after_commit() {
    #[cfg(test)]
    faults::after_commit();
}

#[cfg(test)]
pub(super) mod faults {
    use std::cell::RefCell;
    use std::marker::PhantomData;
    use std::rc::Rc;

    type Hook = Box<dyn FnOnce()>;
    thread_local! {
        static AFTER_COMMIT: RefCell<Option<Hook>> = const { RefCell::new(None) };
    }

    pub(crate) struct AfterCommitGuard {
        previous: Option<Hook>,
        _thread: PhantomData<Rc<()>>,
    }

    impl AfterCommitGuard {
        pub(crate) fn new(hook: impl FnOnce() + 'static) -> Self {
            Self {
                previous: AFTER_COMMIT.with(|slot| slot.replace(Some(Box::new(hook)))),
                _thread: PhantomData,
            }
        }
    }

    impl Drop for AfterCommitGuard {
        fn drop(&mut self) {
            AFTER_COMMIT.with(|slot| {
                slot.replace(self.previous.take());
            });
        }
    }

    pub(super) fn after_commit() {
        let hook = AFTER_COMMIT.with(|slot| slot.borrow_mut().take());
        if let Some(hook) = hook {
            hook();
        }
    }
}
